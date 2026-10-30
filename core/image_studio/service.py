"""Image generation service — the whole local pipeline behind AI Image Studio.

    generate() → validate → backend health → model check → workflow → submit
              → live progress → fetch image → validate → save → history

`generate()` returns immediately with a job record; a daemon thread does the
work, so the Qt event loop (and the voice session) never block. The UI polls
`get_job(job_id)`, which is cheap and lock-protected.

Recovery rules:
* backend offline / model missing / rejected workflow → job FAILED with a
  diagnostic message, never a spinner that never ends;
* cancellation asks ComfyUI to drop the queued job and only interrupts when
  *this* job is the one running;
* a terminal state is always written to history, including failures.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from core.image_studio import (comfy_client, downloads, installer, registry,
                               settings, store, validation, workflows)

QUEUED = "queued"
RUNNING = "running"
SAVING = "saving"
COMPLETED = "completed"
CANCELLED = "cancelled"
FAILED = "failed"

TERMINAL = {COMPLETED, CANCELLED, FAILED}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class ImageGenerationService:
    # ── lifecycle ─────────────────────────────────────────────────────────
    def __init__(self):
        self._lock = threading.RLock()
        self._jobs: dict[str, dict] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._health_cache: dict | None = None
        self._health_at = 0.0
        self._health_ttl = 4.0
        self._log: list[str] = []

    # ── settings ──────────────────────────────────────────────────────────
    def get_settings(self) -> dict:
        return settings.load()

    def save_settings(self, patch: dict) -> dict:
        return settings.save(patch)

    def output_dir(self) -> Path:
        return settings.output_dir(self.get_settings())

    # ── backend ───────────────────────────────────────────────────────────
    def client(self) -> comfy_client.ComfyClient:
        return comfy_client.ComfyClient(settings.comfy_url(self.get_settings()))

    def backend_status(self, force: bool = False) -> dict:
        cfg = self.get_settings()
        url = settings.comfy_url(cfg)
        now = time.monotonic()
        with self._lock:
            if (not force and self._health_cache is not None
                    and now - self._health_at < self._health_ttl):
                return dict(self._health_cache)
        install = installer.detect(str(cfg.get("comfy_path") or ""))
        health = installer.health(url)
        status = {
            "url": url,
            "remote": settings.is_remote_endpoint(url),
            "installed": bool(install.get("found")),
            "install_path": install.get("path", ""),
            "install_python": install.get("python", ""),
            "reachable": bool(health.get("reachable")),
            "device": health.get("device") or {},
            "comfy_version": health.get("comfy_version", ""),
            "python_version": health.get("python_version", ""),
            "queue_running": health.get("running", 0),
            "queue_pending": health.get("pending", 0),
            "error": health.get("error", ""),
            "started_by_keysai": installer.manager.started_by_us,
            "checked_at": _now(),
        }
        with self._lock:
            self._health_cache = status
            self._health_at = now
        return dict(status)

    def start_backend(self, on_log=None) -> dict:
        cfg = self.get_settings()
        url = settings.comfy_url(cfg)
        install = installer.detect(str(cfg.get("comfy_path") or ""))
        try:
            result = installer.manager.start(url, install, on_log=on_log)
            result["ok"] = True
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        self.invalidate_health()
        return result

    def stop_backend(self) -> dict:
        result = installer.manager.stop()
        self.invalidate_health()
        return result

    def invalidate_health(self) -> None:
        with self._lock:
            self._health_cache = None
            self._health_at = 0.0

    # ── models ────────────────────────────────────────────────────────────
    def _installed_assets(self) -> dict:
        """ComfyUI's own view first; fall back to scanning the install folder."""
        try:
            return self.client().installed_assets()
        except Exception:
            assets = {}
            cfg = self.get_settings()
            root = settings.comfy_path(cfg)
            if root:
                for folder in ("checkpoints", "unet", "clip", "vae"):
                    d = root / "models" / folder
                    try:
                        assets[folder] = sorted(
                            str(p.relative_to(d)).replace("\\", "/")
                            for p in d.rglob("*")
                            if p.suffix.lower() in (".safetensors", ".ckpt", ".pt"))
                    except Exception:
                        assets[folder] = []
            return assets

    def list_models(self, refresh: bool = False) -> list[dict]:
        if refresh:
            self.invalidate_health()
        assets = self._installed_assets()
        checkpoints = assets.get("checkpoints") or []
        cfg = self.get_settings()
        vram = None
        try:
            dev = self.backend_status().get("device") or {}
            if dev.get("vram_total_gb"):
                vram = float(dev["vram_total_gb"])
        except Exception:
            vram = None

        out: list[dict] = []
        known_files = set()
        for model in registry.generator_models():
            entry = dict(model)
            files = []
            for f in model.get("files") or []:
                known_files.add(f["filename"].split("/")[-1])
                names = assets.get(f["folder"]) or []
                matched = ""
                for n in names:
                    if n.split("/")[-1] == f["filename"].split("/")[-1]:
                        matched = n
                        break
                files.append({
                    "filename": f["filename"],
                    "folder": f["folder"],
                    "present": bool(matched),
                    "discovered_as": matched,
                    "size_bytes": f.get("size_bytes", 0),
                    "kind": "safetensors",
                })
            entry["files"] = files
            entry["installed"] = bool(files) and all(x["present"] for x in files)
            if not files:
                entry["installed"] = False
            entry["missing"] = [x["filename"] for x in files if not x["present"]]
            entry["vram_label"] = registry.vram_label(model["id"], vram)
            entry["fits"] = registry.fits_vram(model["id"], vram)
            entry["selected"] = model["id"] == cfg.get("model_id")
            out.append(entry)

        # Checkpoints the user installed outside this app: list them honestly as
        # usable (ComfyUI can load any of them) but with generic defaults.
        for name in checkpoints:
            base = name.split("/")[-1]
            if base in known_files:
                continue
            out.append({
                "id": f"local:{name}",
                "name": base,
                "short": base,
                "capability": registry.TEXT2IMG,
                "capabilities": [registry.TEXT2IMG, registry.IMG2IMG],
                "family": "checkpoint",
                "type_label": "Checkpoint found in ComfyUI/models/checkpoints",
                "description": ("Installed outside AI Image Studio. Uses the "
                                "generic SD-compatible workflow and defaults."),
                "files": [{
                    "filename": name, "folder": "checkpoints", "present": True,
                    "discovered_as": name, "size_bytes": 0, "kind": "safetensors",
                }],
                "installed": True,
                "missing": [],
                "vram_gb": 4.0,
                "min_vram_gb": 4.0,
                "max_edge": 768,
                "preferred_edge": 512,
                "dimension_step": 8,
                "defaults": {"width": 512, "height": 512, "steps": 25,
                             "guidance_scale": 7.5, "sampler": "euler",
                             "scheduler": "normal", "negative_prompt": ""},
                "supports_negative": True,
                "supports_img2img": True,
                "max_batch": 4,
                "custom_nodes": [],
                "license": "Unknown — check the file's source",
                "license_url": "",
                "license_note": ("This file was not installed by Keys.AI, so its "
                                 "licence is unknown. Verify it before "
                                 "commercial use."),
                "status": "local",
                "status_note": "Not verified by Keys.AI.",
                "vram_label": registry.vram_label("sd15", vram),
                "fits": True,
                "selected": False,
            })
        return out

    def model_info(self, model_id: str) -> dict | None:
        for m in self.list_models():
            if m["id"] == model_id:
                return m
        return None

    def reset_health(self) -> None:
        self.invalidate_health()

    # ── diagnostics ───────────────────────────────────────────────────────
    def diagnostics(self) -> dict:
        cfg = self.get_settings()
        status = self.backend_status(force=True)
        out_dir = settings.output_dir(cfg)
        writable = False
        free_gb = downloads.disk_free_gb(out_dir)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            probe = out_dir / ".keysai_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            writable = True
        except Exception:
            writable = False
        return {
            "backend": status,
            "output_dir": str(out_dir),
            "output_writable": writable,
            "disk_free_gb": free_gb,
            "history_path": str(store.HISTORY_PATH),
            "models": self.list_models(),
            "vision_models": registry.vision_models(),
            "remote_warning": (
                f"ComfyUI is configured at {status['url']}, which is not this "
                "machine. Prompts and images travel over the network — only do "
                "this on a trusted LAN." if status.get("remote") else ""),
        }

    # ── generation ────────────────────────────────────────────────────────
    def generate(self, request: dict) -> dict:
        """Validate, record and queue a generation. Returns the job snapshot."""
        cfg = self.get_settings()
        request = dict(request or {})
        model_id = str(request.get("model_id") or cfg.get("model_id") or "")
        model = None
        for m in self.list_models():
            if m["id"] == model_id:
                model = m
                break
        if model is None:
            model = registry.get_model(model_id)
        if model is None:
            raise validation.ValidationError(
                "Choose an installed image model before generating.")

        normalised = validation.validate_request(request, model)

        job_id = uuid.uuid4().hex[:12]
        seed = normalised["seed"]
        summary = workflows.workflow_summary(model, normalised)
        job = {
            "job_id": job_id,
            "status": QUEUED,
            "stage": "Queued",
            "progress": 0.0,
            "created_at": _now(),
            "started_at": "",
            "finished_at": "",
            "prompt": normalised["prompt"],
            "original_prompt": str(request.get("original_prompt")
                                   or normalised["prompt"]),
            "negative_prompt": normalised["negative_prompt"],
            "model_id": normalised["model_id"],
            "model": model.get("name", ""),
            "seed": seed,
            "settings": summary,
            "image_path": "",
            "images": [],
            "error": "",
            "diagnostics": [],
            "prompt_id": "",
            "backend": settings.comfy_url(cfg),
        }
        with self._lock:
            self._jobs[job_id] = job
            self._stop_events[job_id] = threading.Event()
        store.add({
            "job_id": job_id,
            "created_at": job["created_at"],
            "prompt": job["prompt"],
            "original_prompt": job["original_prompt"],
            "negative_prompt": job["negative_prompt"],
            "model": job["model"],
            "model_id": job["model_id"],
            "settings": summary,
            "seed": seed,
            "status": QUEUED,
            "image_path": "",
            "images": [],
            "error": "",
        })
        thread = threading.Thread(
            target=self._run_job,
            args=(job_id, normalised, model),
            name=f"img-gen-{job_id}", daemon=True,
        )
        with self._lock:
            self._threads[job_id] = thread
        thread.start()
        return self.get_job(job_id) or dict(job)

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def active_job(self) -> dict | None:
        with self._lock:
            for job in self._jobs.values():
                if job.get("status") not in TERMINAL:
                    return dict(job)
        return None

    def cancel_job(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            event = self._stop_events.get(job_id)
            prompt_id = (job or {}).get("prompt_id") or ""
        if job is None:
            return {"ok": False, "error": "Unknown job."}
        if job.get("status") in TERMINAL:
            return {"ok": False, "error": "That generation already finished."}
        if event is not None:
            event.set()
        if prompt_id:
            try:
                ComfyClient = comfy_client.ComfyClient
                ComfyClient(settings.comfy_url(self.get_settings())).cancel(prompt_id)
            except Exception as exc:
                self._note(job_id, f"Cancellation request failed: {exc}")
        self._update(job_id, stage="Cancelling")
        return {"ok": True, "message": "Cancellation requested."}

    def shutdown(self) -> None:
        """Cancel everything this service is running (app exit)."""
        with self._lock:
            events = list(self._stop_events.values())
        for ev in events:
            ev.set()

    # ── worker ────────────────────────────────────────────────────────────
    def _update(self, job_id: str, **patch) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.update(patch)

    def _note(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.setdefault("diagnostics", []).append(f"{_now()}  {message}")
            self._log.append(message)
        print(f"[image_studio] {message}")

    def _set_progress(self, job_id: str, value: int, maximum: int) -> None:
        if maximum <= 0:
            return
        pct = max(1.0, min(99.0, value / maximum * 100.0))
        self._update(job_id, progress=pct, stage=f"Sampling {value}/{maximum}")

    def _stop_requested(self, job_id: str) -> bool:
        ev = self._stop_events.get(job_id)
        return bool(ev and ev.is_set())

    def _run_job(self, job_id: str, request: dict, model: dict) -> None:
        cfg = self.get_settings()
        url = settings.comfy_url(cfg)
        client = comfy_client.ComfyClient(url)
        uploaded = None
        ws_thread = None
        try:
            self._update(job_id, status=RUNNING, stage="Checking ComfyUI",
                         started_at=_now(), progress=0.0)
            if self._stop_requested(job_id):
                return self._finish_cancelled(job_id)

            health = client.health()
            device = health.get("device") or {}
            self._note(job_id, f"ComfyUI {health.get('comfy_version', '')} · "
                               f"{device.get('name', 'device unknown')} · "
                               f"{device.get('vram_total_gb', '?')} GB VRAM")

            assets = client.installed_assets()
            checkpoint = self._resolve_checkpoint(model, request, assets)
            if checkpoint is None:
                names = ", ".join(f["filename"] for f in model.get("files") or [])
                raise validation.ValidationError(
                    f"{model.get('name')} is not installed in ComfyUI "
                    f"(missing {names}). Install it from the Models tab, then "
                    "try again.")
            self._note(job_id, f"Checkpoint: {checkpoint}")

            if request.get("input_image"):
                self._update(job_id, stage="Uploading input image")
                uploaded = client.upload_image(request["input_image"])
                self._note(job_id, f"Uploaded input image as {uploaded}")

            if self._stop_requested(job_id):
                return self._finish_cancelled(job_id)

            graph = workflows.build_graph(
                model, request, job_id=job_id, uploaded_image=uploaded,
                checkpoint=checkpoint)
            self._update(job_id, stage="Submitting workflow")
            client_id = uuid.uuid4().hex
            prompt_id = client.queue_prompt(graph, client_id=client_id)
            self._update(job_id, prompt_id=prompt_id,
                         stage="Queued in ComfyUI", progress=1.0)
            self._note(job_id, f"ComfyUI accepted the job as {prompt_id}")

            stop = lambda: self._stop_requested(job_id)  # noqa: E731
            try:
                ws_thread = threading.Thread(
                    target=comfy_client.listen_progress,
                    args=(url, client_id,
                          lambda v, m, n: self._set_progress(job_id, v, m),
                          stop),
                    name=f"img-progress-{job_id}", daemon=True,
                )
                ws_thread.start()
            except Exception:
                ws_thread = None

            entry = self._wait_for_result(client, job_id, prompt_id)
            if self._stop_requested(job_id):
                return self._finish_cancelled(job_id)
            if entry is None:
                raise RuntimeError(
                    "ComfyUI did not report a finished job. The backend may "
                    "have run out of memory — check its console output.")

            status = entry.get("status") or {}
            if str(status.get("status_str", "")).lower() == "error":
                raise RuntimeError(self._execution_error(status))

            images = self._collect_images(entry)
            if not images:
                raise RuntimeError(
                    "ComfyUI finished the workflow but returned no image output.")

            self._update(job_id, status=SAVING, stage="Fetching image",
                         progress=100.0)
            saved = []
            for item in images:
                raw = client.fetch_image(item.get("filename", ""),
                                        item.get("subfolder", ""),
                                        item.get("type", "output"))
                info = validation.validate_image_bytes(raw)
                path = self._save_image(raw, info, request["output_format"],
                                        job_id)
                saved.append({"path": str(path),
                              "width": info["width"],
                              "height": info["height"],
                              "bytes": info["bytes"],
                              "format": path.suffix.lstrip(".").upper()})
                self._note(job_id, f"Saved {path.name} "
                                   f"({info['width']}×{info['height']})")
            self._finish_completed(job_id, saved)
        except validation.ValidationError as exc:
            self._fail(job_id, str(exc))
        except comfy_client.ComfyUnavailable as exc:
            self._fail(job_id, f"{exc}. Start ComfyUI, or fix the URL in "
                               f"Settings, then try again.")
        except comfy_client.ComfyError as exc:
            self._fail(job_id, f"ComfyUI error: {exc}")
        except Exception as exc:
            self._fail(job_id, f"Generation failed: {exc}")
        finally:
            ev = self._stop_events.get(job_id)
            if ev is not None:
                ev.clear()

    # ── worker helpers ────────────────────────────────────────────────────
    def _resolve_checkpoint(self, model: dict, request: dict,
                            assets: dict) -> str | None:
        names = assets.get("checkpoints") or []
        wanted = ""
        for f in model.get("files") or []:
            wanted = f["filename"]
            break
        if not wanted:
            return None
        for name in names:
            if name == wanted or name.split("/")[-1] == wanted.split("/")[-1]:
                return name
        return None

    def _wait_for_result(self, client, job_id: str, prompt_id: str,
                         timeout: float = 900.0) -> dict | None:
        deadline = time.monotonic() + timeout
        missing_since = None
        while time.monotonic() < deadline:
            if self._stop_requested(job_id):
                try:
                    client.cancel(prompt_id)
                except Exception:
                    pass
                return None
            try:
                entry = client.history(prompt_id)
            except comfy_client.ComfyUnavailable:
                raise
            except comfy_client.ComfyError as exc:
                self._note(job_id, f"History poll: {exc}")
                entry = {}
            if entry:
                status = entry.get("status") or {}
                if status.get("completed") or status.get("status_str"):
                    return entry
                if entry.get("outputs"):
                    return entry
            state = "absent"
            try:
                state = client.queue_state(prompt_id)
            except Exception:
                pass
            if state == "running":
                missing_since = None
                progress = (self.get_job(job_id) or {}).get("progress") or 0.0
                if progress <= 1.0:
                    # ComfyUI loads the checkpoint into VRAM before the first
                    # step; saying so is more useful than a frozen 0%.
                    self._update(job_id, stage="Running (loading model into VRAM)")
            elif state == "pending":
                missing_since = None
                self._update(job_id, stage="Queued behind other jobs")
            else:
                # Absent + no history yet: give ComfyUI a moment to publish it.
                missing_since = missing_since or time.monotonic()
                if time.monotonic() - missing_since > 20:
                    return None
            time.sleep(0.7)
        return None

    @staticmethod
    def _execution_error(status: dict) -> str:
        parts = []
        for msg in status.get("messages") or []:
            if not isinstance(msg, (list, tuple)) or not msg:
                continue
            if msg[0] == "execution_error":
                data = msg[1] if len(msg) > 1 and isinstance(msg[1], dict) else {}
                parts.append(str(data.get("exception_message")
                                 or data.get("exception_type") or "").strip())
        return "; ".join(p for p in parts if p) or \
            "ComfyUI reported an execution error."

    @staticmethod
    def _collect_images(entry: dict) -> list[dict]:
        images = []
        for node in (entry.get("outputs") or {}).values():
            for img in (node or {}).get("images") or []:
                if isinstance(img, dict) and img.get("filename"):
                    images.append(img)
        return images

    def _save_image(self, raw: bytes, info: dict, fmt: str,
                    job_id: str) -> Path:
        out_dir = settings.output_dir(self.get_settings())
        ext = "jpg" if fmt in ("jpg", "jpeg") else fmt
        dest = validation.unique_output_path(out_dir, job_id, ext)
        wanted = validation.OUTPUT_FORMATS.get(fmt, "PNG")
        if info.get("format") == wanted and ext == wanted.lower():
            dest.write_bytes(raw)
            return dest
        # ComfyUI's SaveImage always writes PNG; honour the requested format by
        # transcoding a verified copy (quality 95 keeps JPEG/WebP faithful).
        try:
            import io
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as im:
                if wanted in ("JPEG",) and im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                kwargs = {"quality": 95} if wanted in ("JPEG", "WEBP") else {}
                im.save(dest, format=wanted, **kwargs)
        except Exception:
            dest = dest.with_suffix(".png")
            dest.write_bytes(raw)
        return dest

    def _finish_completed(self, job_id: str, saved: list[dict]) -> None:
        first = saved[0] if saved else {}
        patch = {
            "status": COMPLETED,
            "stage": "Completed",
            "progress": 100.0,
            "finished_at": _now(),
            "image_path": first.get("path", ""),
            "images": saved,
            "error": "",
        }
        self._update(job_id, **patch)
        job = self.get_job(job_id) or {}
        store.update(job_id, {
            "status": COMPLETED,
            "image_path": patch["image_path"],
            "images": saved,
            "finished_at": patch["finished_at"],
            "width": first.get("width"),
            "height": first.get("height"),
        })

    def _finish_cancelled(self, job_id: str) -> None:
        self._update(job_id, status=CANCELLED, stage="Cancelled",
                     finished_at=_now(), error="")
        store.update(job_id, {"status": CANCELLED, "finished_at": _now()})
        self._note(job_id, "Generation cancelled.")
        self._cleanup_worker(job_id)

    def _fail(self, job_id: str, message: str) -> None:
        self._update(job_id, status=FAILED, stage="Failed",
                     finished_at=_now(), error=message, progress=0.0)
        store.update(job_id, {"status": FAILED, "error": message,
                              "finished_at": _now()})
        self._note(job_id, message)
        self._cleanup_worker(job_id)

    def _cleanup_worker(self, job_id: str) -> None:
        with self._lock:
            self._threads.pop(job_id, None)

    # ── history ───────────────────────────────────────────────────────────
    def history(self, limit: int = 100) -> list[dict]:
        records = store.list_records(limit)
        with self._lock:
            live = {jid: dict(j) for jid, j in self._jobs.items()}
        for rec in records:
            job = live.get(rec.get("job_id"))
            if job and job.get("status") not in TERMINAL:
                rec["status"] = job.get("status")
                rec["progress"] = job.get("progress")
                rec["stage"] = job.get("stage")
            path = rec.get("image_path") or ""
            rec["file_exists"] = bool(path) and Path(path).is_file()
        return records

    def remove_record(self, job_id: str, delete_file: bool = False) -> dict:
        rec = store.get(job_id)
        if rec is None:
            return {"ok": False, "error": "Record not found."}
        removed_files = []
        if delete_file:
            paths = [rec.get("image_path")] + [i.get("path") for i in
                                              (rec.get("images") or [])]
            for raw in {p for p in paths if p}:
                try:
                    p = Path(raw).resolve()
                    out_dir = settings.output_dir(self.get_settings()).resolve()
                    # Only delete files this app wrote into its output folder.
                    if out_dir in p.parents and p.is_file():
                        p.unlink()
                        removed_files.append(str(p))
                except Exception:
                    continue
        store.remove(job_id)
        with self._lock:
            self._jobs.pop(job_id, None)
            self._stop_events.pop(job_id, None)
        return {"ok": True, "deleted_files": removed_files}

    # ── prompt enhancement ────────────────────────────────────────────────
    def enhance_prompt(self, prompt: str) -> dict:
        from core.image_studio import prompt_enhancer
        return prompt_enhancer.enhance(prompt)

    def enhancement_status(self) -> dict:
        from core.image_studio import prompt_enhancer
        try:
            return prompt_enhancer.resolve()
        except Exception as exc:
            return {"ok": False, "error": str(exc), "model": "", "url": ""}

    # ── downloads ─────────────────────────────────────────────────────────
    def download_model(self, model_id: str, *, on_progress=None,
                       should_stop=None, on_log=None) -> dict:
        """Download every file a registry model needs into ComfyUI's folders.

        Refuses to guess: the ComfyUI install (or its configured path) must be
        known, otherwise there is nowhere safe to put the weights.
        """
        on_log = on_log or (lambda _m: None)
        cfg = self.get_settings()
        model = registry.get_model(model_id)
        if model is None:
            raise downloads.DownloadError(f"Unknown model id: {model_id}")
        files = model.get("files") or []
        if not files:
            raise downloads.DownloadError(
                f"{model['name']} has no automatic download — it needs several "
                "model-specific files. See its notes for the official guide.")

        install = installer.detect(str(cfg.get("comfy_path") or ""))
        root = Path(install["path"]) if install.get("found") else settings.comfy_path(cfg)
        if root is None:
            raise downloads.DownloadError(
                "ComfyUI was not found. Install it first (Backend tab), or set "
                "its folder path, so the model can be placed in "
                "ComfyUI/models/checkpoints/.")

        results = []
        for f in files:
            dest = root / "models" / f["folder"] / f["filename"]
            on_log(f"{f['filename']} → {dest.parent}")
            result = downloads.download_file(
                f["url"], dest,
                expected_sha256=f.get("sha256", ""),
                expected_size=int(f.get("size_bytes") or 0),
                on_progress=on_progress, should_stop=should_stop,
            )
            on_log(f"{f['filename']}: {result['status']} "
                   f"(verified by {result['verified_by']})")
            results.append(result)
        self.invalidate_health()
        return {"ok": True, "files": results, "path": str(root)}

    def delete_model(self, model_id: str, confirm: bool = False) -> dict:
        """Delete the files of a registry model. Requires confirm=True."""
        if not confirm:
            return {"ok": False, "error": "Deletion needs explicit confirmation."}
        cfg = self.get_settings()
        install = installer.detect(str(cfg.get("comfy_path") or ""))
        root = Path(install["path"]) if install.get("found") else settings.comfy_path(cfg)
        if root is None:
            return {"ok": False, "error": "ComfyUI folder is unknown."}
        model = registry.get_model(model_id)
        if model is None:
            return {"ok": False, "error": "Only models installed by this app can "
                                          "be deleted here."}
        removed = []
        for f in model.get("files") or []:
            p = root / "models" / f["folder"] / f["filename"]
            if p.is_file():
                try:
                    p.unlink()
                    removed.append(str(p))
                except Exception as exc:
                    return {"ok": False, "error": f"Could not delete {p.name}: {exc}"}
        self.invalidate_health()
        return {"ok": True, "deleted": removed}

    # ── misc ──────────────────────────────────────────────────────────────
    def open_output_dir(self) -> dict:
        out_dir = settings.output_dir(self.get_settings())
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        try:
            if os.name == "nt":
                os.startfile(str(out_dir))          # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(out_dir)])
            else:
                subprocess.Popen(["xdg-open", str(out_dir)])
            return {"ok": True, "path": str(out_dir)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "path": str(out_dir)}

    def reveal_file(self, path: str) -> dict:
        p = Path(str(path or ""))
        if not p.is_file():
            return {"ok": False, "error": "That file is no longer on disk."}
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", str(p)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p.parent)])
            return {"ok": True, "path": str(p)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


__all__ = ["ImageGenerationService", "QUEUED", "RUNNING", "SAVING",
           "COMPLETED", "CANCELLED", "FAILED", "TERMINAL"]
