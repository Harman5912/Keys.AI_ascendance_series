"""Live setup/verification harness for AI Image Studio.

Drives the *application's own* code paths against a real ComfyUI backend:

    python qa_artifacts/image_studio_live_setup.py install   # isolated ComfyUI venv
    python qa_artifacts/image_studio_live_setup.py download  # SD 1.5 checkpoint
    python qa_artifacts/image_studio_live_setup.py status    # detection + health
    python qa_artifacts/image_studio_live_setup.py generate  # real 512x512 image

Nothing here bypasses the service: install goes through
``installer.install_comfy``, download through ``service.download_model`` (resume
+ sha256), generation through ``service.generate``. That is the point — the
harness proves the shipped code works, not a parallel implementation.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.image_studio import installer, registry, settings  # noqa: E402
from core.image_studio.service import ImageGenerationService  # noqa: E402


def _log(message: str) -> None:
    # Windows consoles default to cp1252; the service logs arrows and other
    # non-ASCII characters, which must not kill a 4 GB download.
    print(str(message).encode("ascii", "replace").decode("ascii"), flush=True)


def cmd_install() -> int:
    target = installer.default_install_target()
    _log(f"target: {target}")
    result = installer.install_comfy(target, on_log=_log)
    _log("INSTALL OK " + json.dumps(result))
    settings.save({"comfy_path": str(target)})
    _log(f"settings.comfy_path = {target}")
    return 0


def cmd_download() -> int:
    service = ImageGenerationService()
    model_id = "sd15"
    last = {"pct": -1}

    def progress(info):
        pct = int(info.get("percent") or 0)
        if pct // 5 != last["pct"] // 5:
            last["pct"] = pct
            _log(f"  {pct:3d}%  {info['received'] / 1e9:.2f} GB"
                 f"  {info['speed'] / 1e6:.1f} MB/s")

    result = service.download_model(model_id, on_progress=progress,
                                    on_log=_log)
    _log("DOWNLOAD OK " + json.dumps(result))
    model = registry.get_model(model_id)
    _log(f"expected sha256: {model['files'][0]['sha256']}")
    return 0


def cmd_status() -> int:
    service = ImageGenerationService()
    status = service.backend_status(force=True)
    _log(json.dumps({"status": status}, indent=2, default=str))
    models = service.list_models(refresh=True)
    _log(json.dumps([{"id": m["id"], "installed": m["installed"],
                      "vram": m.get("vram_label"), "fits": m.get("fits")}
                     for m in models], indent=2))
    return 0 if status.get("reachable") else 1


def cmd_generate() -> int:
    service = ImageGenerationService()
    out_dir = service.output_dir()
    before = {p.name for p in out_dir.glob("*")} if out_dir.is_dir() else set()
    job = service.generate({
        "prompt": ("a silver knight in a crimson cape on a dark fantasy "
                   "battlefield, cinematic lighting, detailed armour"),
        "negative_prompt": "blurry, low quality, watermark, text",
        "model_id": "sd15",
        "width": 512,
        "height": 512,
        "steps": 20,
        "guidance_scale": 7.5,
        "seed": 12345,
        "batch_size": 1,
        "output_format": "png",
    })
    job_id = job["job_id"]
    _log(f"job {job_id} queued")
    deadline = time.time() + 900
    last = None
    while time.time() < deadline:
        cur = service.get_job(job_id) or {}
        stage = (cur.get("stage"), int(cur.get("progress") or 0))
        if stage != last:
            last = stage
            _log(f"  [{cur.get('status')}] {stage[0]} {stage[1]}%")
        if cur.get("status") in ("completed", "failed", "cancelled"):
            _log(json.dumps(cur, indent=2, default=str))
            if cur.get("status") == "completed":
                path = Path(cur["image_path"])
                _log(f"file exists: {path.is_file()}  size: "
                     f"{path.stat().st_size if path.is_file() else 0} bytes")
                after = {p.name for p in out_dir.glob("*")}
                _log(f"new files in output dir: {sorted(after - before)}")
            return 0 if cur.get("status") == "completed" else 1
        time.sleep(1.0)
    _log("TIMEOUT")
    return 1


COMMANDS = {"install": cmd_install, "download": cmd_download,
            "status": cmd_status, "generate": cmd_generate}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in COMMANDS:
        _log("usage: image_studio_live_setup.py " + "|".join(COMMANDS))
        return 2
    return COMMANDS[argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
