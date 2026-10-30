"""Thin, dependency-light client for the local ComfyUI HTTP API.

Only documented endpoints are used:

    GET  /system_stats        hardware + ComfyUI version (health check)
    GET  /object_info/<node>  which checkpoints / nodes exist
    POST /prompt              submit a workflow, get a prompt_id
    GET  /history/<id>        outputs once the job finishes
    GET  /queue               running + pending jobs
    POST /interrupt           stop the running job
    POST /queue {"delete":…}  drop a pending job
    POST /upload/image        img2img input
    GET  /view                the generated image bytes
    WS   /ws?clientId=…       real step progress (optional)

`requests` is already a Keys.AI dependency; the WebSocket progress feed uses
`websocket-client` when it is installed and silently degrades to polling when
it is not, so progress is never a hard requirement.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests


class ComfyError(RuntimeError):
    """The backend answered, but with an error."""


class ComfyUnavailable(ComfyError):
    """The backend could not be reached at all."""


def normalise_url(url: str) -> str:
    """Accept bare host:port, add a scheme, drop a trailing slash."""
    url = str(url or "").strip()
    if not url:
        return "http://127.0.0.1:8188"
    if "://" not in url:
        url = "http://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported scheme: {parsed.scheme}")
    if not parsed.hostname:
        raise ValueError("ComfyUI URL has no host")
    return url.rstrip("/")


class ComfyClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188",
                 timeout: float = 15.0):
        self.base_url = normalise_url(base_url)
        self.timeout = timeout
        self._session = requests.Session()

    # ── plumbing ──────────────────────────────────────────────────────────
    def _url(self, path: str) -> str:
        return self.base_url + path

    def _get(self, path: str, timeout: float | None = None,
             **params) -> requests.Response:
        try:
            resp = self._session.get(self._url(path), params=params or None,
                                     timeout=timeout or self.timeout)
        except Exception as exc:
            raise ComfyUnavailable(
                f"Cannot reach ComfyUI at {self.base_url}: {exc}") from exc
        if resp.status_code >= 400:
            raise ComfyError(f"{path} → HTTP {resp.status_code}: "
                             f"{resp.text[:200]}")
        return resp

    def _post(self, path: str, payload=None, timeout: float | None = None,
              files=None) -> requests.Response:
        try:
            if files is not None:
                resp = self._session.post(self._url(path), files=files,
                                          timeout=timeout or self.timeout)
            else:
                resp = self._session.post(self._url(path), json=payload,
                                          timeout=timeout or self.timeout)
        except Exception as exc:
            raise ComfyUnavailable(
                f"Cannot reach ComfyUI at {self.base_url}: {exc}") from exc
        if resp.status_code >= 400:
            raise ComfyError(f"{path} → HTTP {resp.status_code}: "
                             f"{resp.text[:400]}")
        return resp

    # ── health / inventory ────────────────────────────────────────────────
    def health(self) -> dict:
        """system_stats + queue depth. Raises ComfyUnavailable when offline."""
        stats = self._get("/system_stats", timeout=6).json()
        queue = self._get("/queue", timeout=6).json()
        device = {}
        devices = stats.get("devices") or []
        if devices:
            d = devices[0]
            device = {
                "name": d.get("name", ""),
                "type": d.get("type", ""),
                "vram_total_gb": round(float(d.get("vram_total") or 0) / 1e9, 2),
                "vram_free_gb": round(float(d.get("vram_free") or 0) / 1e9, 2),
            }
        return {
            "reachable": True,
            "url": self.base_url,
            "comfy_version": (stats.get("system") or {}).get("comfyui_version", ""),
            "python_version": (stats.get("system") or {}).get("python_version", ""),
            "device": device,
            "running": len(queue.get("queue_running") or []),
            "pending": len(queue.get("queue_pending") or []),
        }

    def ping(self) -> bool:
        try:
            self._get("/system_stats", timeout=3)
            return True
        except Exception:
            return False

    def object_info(self, node: str | None = None) -> dict:
        path = "/object_info" if not node else f"/object_info/{node}"
        return self._get(path, timeout=30).json()

    def installed_assets(self) -> dict:
        """{'checkpoints': [...], 'unet': [...], 'clip': [...], 'vae': [...]}

        Comes from ComfyUI's own node definitions, which is the only reliable
        answer to "what can this server actually load right now". A missing
        node class simply yields an empty list.
        """
        wanted = {
            "checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),
            "unet": ("UNETLoader", "unet_name"),
            "clip": ("CLIPLoader", "clip_name"),
            "vae": ("VAELoader", "vae_name"),
        }
        assets: dict[str, list[str]] = {}
        for folder, (node, field) in wanted.items():
            names: list[str] = []
            try:
                info = self.object_info(node)
                spec = (info.get(node) or {}).get("input") or {}
                group = spec.get("required") or spec.get("optional") or {}
                entry = group.get(field) or []
                if entry and isinstance(entry[0], list):
                    names = [str(x) for x in entry[0]]
            except Exception:
                names = []
            assets[folder] = names
        return assets

    # ── jobs ──────────────────────────────────────────────────────────────
    def queue_prompt(self, graph: dict, client_id: str | None = None) -> str:
        client_id = client_id or uuid.uuid4().hex
        resp = self._post("/prompt", {"prompt": graph, "client_id": client_id},
                          timeout=30)
        data = resp.json()
        if data.get("node_errors"):
            raise ComfyError(f"Workflow rejected: "
                             f"{json.dumps(data['node_errors'])[:500]}")
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise ComfyError(f"ComfyUI returned no prompt_id: {str(data)[:300]}")
        self.last_client_id = client_id
        return str(prompt_id)

    def history(self, prompt_id: str) -> dict:
        data = self._get(f"/history/{prompt_id}", timeout=15).json()
        return data.get(prompt_id) or {}

    def queue_state(self, prompt_id: str) -> str:
        """'running' | 'pending' | 'absent' (finished, cancelled or unknown)."""
        data = self._get("/queue", timeout=10).json()
        for item in data.get("queue_running") or []:
            if len(item) > 1 and item[1] == prompt_id:
                return "running"
        for item in data.get("queue_pending") or []:
            if len(item) > 1 and item[1] == prompt_id:
                return "pending"
        return "absent"

    def interrupt(self) -> None:
        self._post("/interrupt", {}, timeout=10)

    def cancel(self, prompt_id: str) -> None:
        """Delete the job if it is still queued, then interrupt if running.

        ComfyUI's /interrupt stops whatever is executing; it is only sent when
        this prompt is the one running, so cancelling one job cannot silently
        kill a different user's generation.
        """
        state = "absent"
        try:
            state = self.queue_state(prompt_id)
        except ComfyError:
            return
        if state == "pending":
            self._post("/queue", {"delete": [prompt_id]}, timeout=10)
        elif state == "running":
            self._post("/queue", {"delete": [prompt_id]}, timeout=10)
            self.interrupt()

    # ── files ─────────────────────────────────────────────────────────────
    def upload_image(self, path: str | Path, name: str | None = None) -> str:
        """Upload an img2img input into ComfyUI's input folder.

        Returns the name to give ``LoadImage`` (``subfolder/name`` when the
        server places it in one).
        """
        src = Path(path)
        if not src.is_file():
            raise ComfyError(f"Input image not found: {src}")
        filename = name or src.name
        try:
            with open(src, "rb") as fh:
                resp = self._post(
                    "/upload/image",
                    files={"image": (filename, fh, "application/octet-stream")},
                    timeout=120,
                )
        except OSError as exc:
            raise ComfyError(f"Could not read input image: {exc}") from exc
        data = resp.json()
        stored = str(data.get("name") or filename)
        sub = str(data.get("subfolder") or "").strip("/")
        return f"{sub}/{stored}" if sub else stored

    def fetch_image(self, filename: str, subfolder: str = "",
                    folder_type: str = "output") -> bytes:
        params = {"filename": filename, "type": folder_type}
        if subfolder:
            params["subfolder"] = subfolder
        resp = self._get("/view", timeout=120, **params)
        return resp.content

    def ui_url(self) -> str:
        return self.base_url + "/"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ComfyClient({self.base_url!r})"


# ── optional live progress ─────────────────────────────────────────────────
def listen_progress(base_url: str, client_id: str, on_progress,
                    should_stop=None, deadline: float = 3600.0) -> None:
    """Stream ComfyUI step progress over the WebSocket.

    Best-effort: any import/connection/frame problem simply ends the listener
    and the caller keeps polling /queue and /history. Never raises.
    """
    should_stop = should_stop or (lambda: False)
    try:
        import websocket  # type: ignore
    except Exception:
        return
    ws_url = normalise_url(base_url).replace("https://", "wss://") \
        .replace("http://", "ws://") + f"/ws?clientId={client_id}"
    conn = None
    stop_at = time.monotonic() + deadline
    try:
        conn = websocket.create_connection(ws_url, timeout=5)
        conn.settimeout(1.0)
        while not should_stop() and time.monotonic() < stop_at:
            try:
                raw = conn.recv()
            except Exception as exc:
                if type(exc).__name__ in ("WebSocketTimeoutException",
                                          "TimeoutError"):
                    continue
                break
            if not raw or isinstance(raw, (bytes, bytearray)):
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            kind = msg.get("type")
            data = msg.get("data") or {}
            if kind == "progress":
                try:
                    on_progress(int(data.get("value") or 0),
                                int(data.get("max") or 0),
                                str(data.get("node") or ""))
                except Exception:
                    pass
            elif kind == "executing" and data.get("node") is None:
                break
            elif kind == "execution_error":
                break
    except Exception:
        return
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


__all__ = ["ComfyClient", "ComfyError", "ComfyUnavailable", "normalise_url",
           "listen_progress"]
