"""Settings for AI Image Studio — stored in the app's existing config file.

These are ordinary preferences (paths, URL, defaults), so they live under the
``image_studio`` key of ``config/api_keys.json`` and go through
``core.config_store`` — the single writer that already serialises every other
settings save in the app. No second config system is introduced.

The output directory defaults to the platform's normal Pictures folder via
``Path.home()``; no username is ever hard-coded.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

CONFIG_KEY = "image_studio"

DEFAULT_COMFY_URL = "http://127.0.0.1:8188"

DEFAULTS: dict = {
    "comfy_url": DEFAULT_COMFY_URL,
    "comfy_path": "",
    "output_dir": "",
    "model_id": "sd15",
    "width": 512,
    "height": 512,
    "steps": 25,
    "guidance_scale": 7.5,
    "seed": -1,
    "batch_size": 1,
    "negative_prompt": "",
    "output_format": "png",
    "enhance_prompt": False,
    "enhance_preview": True,
    "prompt_model": "",
    "sampler": "",
    "scheduler": "",
    "auto_start": False,
    "last_model": "sd15",
}


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


def default_output_dir() -> Path:
    """%USERPROFILE%\\Pictures\\KeysAI\\Generated (or the platform equivalent)."""
    pictures = Path.home() / "Pictures"
    if not pictures.parent.exists():          # unusual home dir; fall back
        pictures = Path.home()
    return pictures / "KeysAI" / "Generated"


def load() -> dict:
    """Merged settings: defaults ← stored values."""
    cfg = dict(DEFAULTS)
    try:
        from core import config_store
        stored = config_store.load().get(CONFIG_KEY) or {}
        if isinstance(stored, dict):
            for k, v in stored.items():
                if k in DEFAULTS or k in ("comfy_args",):
                    cfg[k] = v
    except Exception as exc:
        print(f"[image_studio] settings load failed: {exc}")
    return cfg


def save(patch: dict) -> dict:
    """Persist a partial settings update (never writes unrelated keys)."""
    from core import config_store
    clean = {k: v for k, v in (patch or {}).items() if k in DEFAULTS}
    cfg = load()
    cfg.update(clean)
    config_store.update({CONFIG_KEY: cfg})
    return cfg


def get(key: str, fallback=None):
    return load().get(key, DEFAULTS.get(key, fallback))


def output_dir(cfg: dict | None = None) -> Path:
    """Resolved output directory (created on demand by the caller)."""
    cfg = cfg or load()
    raw = str(cfg.get("output_dir") or "").strip()
    if not raw:
        return default_output_dir()
    try:
        path = Path(os.path.expandvars(os.path.expanduser(raw)))
    except Exception:
        return default_output_dir()
    if not path.is_absolute():
        path = (_base_dir() / path).resolve()
    return path


def comfy_url(cfg: dict | None = None) -> str:
    cfg = cfg or load()
    return str(cfg.get("comfy_url") or DEFAULT_COMFY_URL).strip().rstrip("/")


def comfy_path(cfg: dict | None = None) -> Path | None:
    cfg = cfg or load()
    raw = str(cfg.get("comfy_path") or "").strip()
    if not raw:
        return None
    try:
        p = Path(os.path.expandvars(os.path.expanduser(raw)))
    except Exception:
        return None
    return p if p.is_dir() else None


def is_remote_endpoint(url: str) -> bool:
    """True when the configured ComfyUI host is not the local machine."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return True
    return host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


__all__ = ["DEFAULTS", "DEFAULT_COMFY_URL", "CONFIG_KEY", "load", "save", "get",
           "default_output_dir", "output_dir", "comfy_url", "comfy_path",
           "is_remote_endpoint"]
