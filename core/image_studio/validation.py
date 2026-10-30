"""Validation for image-generation requests.

Everything a user (or a future tool call) supplies is checked here before a
workflow is built: prompt length, dimensions, step/CFG bounds, batch size,
seed range, upload format and image integrity. Unsupported settings are
dropped per model instead of being forwarded to ComfyUI, where they would
either be ignored or rejected with a less useful error.

Nothing in this module touches the network.
"""

from __future__ import annotations

import io
import random
import re
from pathlib import Path

from core.image_studio import registry

MAX_PROMPT_CHARS = 2000
MAX_NEGATIVE_CHARS = 2000
MIN_EDGE = 256
HARD_MAX_EDGE = 2048
MAX_STEPS = 100
MIN_STEPS = 1
MAX_CFG = 30.0
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_UPLOAD_EDGE = 8192
ALLOWED_UPLOAD_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
OUTPUT_FORMATS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP"}

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f]")


class ValidationError(ValueError):
    """A request the backend cannot honour (message is user-facing)."""


def _clean_text(value, limit: int, field: str) -> str:
    text = _CTRL.sub("", str(value or "")).strip()
    if len(text) > limit:
        raise ValidationError(
            f"{field} is {len(text)} characters — the limit is {limit}.")
    return text


def _int(value, field: str, default: int | None = None) -> int:
    if value is None or value == "":
        if default is not None:
            return default
        raise ValidationError(f"{field} is required.")
    try:
        return int(float(value))
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a whole number.")


def _float(value, field: str, default: float | None = None) -> float:
    if value is None or value == "":
        if default is not None:
            return default
        raise ValidationError(f"{field} is required.")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a number.")


def validate_input_image(path) -> Path:
    """An upload must be a real, readable image inside a sane size budget."""
    if not path:
        raise ValidationError("Image-to-image needs an input image.")
    p = Path(str(path))
    if not p.exists() or not p.is_file():
        raise ValidationError(f"Input image not found: {p.name}")
    if p.suffix.lower() not in ALLOWED_UPLOAD_SUFFIXES:
        raise ValidationError(
            f"Unsupported input format '{p.suffix}'. Use PNG, JPG or WebP.")
    size = p.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        raise ValidationError(
            f"Input image is {size / 1e6:.1f} MB — the limit is 25 MB.")
    try:
        from PIL import Image
        with Image.open(p) as im:
            im.verify()
        with Image.open(p) as im:
            w, h = im.size
        if max(w, h) > MAX_UPLOAD_EDGE:
            raise ValidationError(
                f"Input image is {w}×{h} — the maximum edge is {MAX_UPLOAD_EDGE} px.")
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"Input image could not be read: {exc}")
    return p


def validate_request(request: dict, model: dict | None = None) -> dict:
    """Return a normalised request dict, or raise ValidationError."""
    request = dict(request or {})
    prompt = _clean_text(request.get("prompt"), MAX_PROMPT_CHARS, "Prompt")
    if not prompt:
        raise ValidationError("Enter a prompt describing the image you want.")

    model = model or registry.get_model(request.get("model_id", ""))
    if model is None:
        raise ValidationError(
            "Select an image model first — none of the supported models are "
            "installed yet.")

    caps = model.get("capabilities") or [registry.TEXT2IMG]
    defaults = model.get("defaults") or {}
    step = int(model.get("dimension_step") or 8)
    max_edge = min(int(model.get("max_edge") or 1024), HARD_MAX_EDGE)

    width = _int(request.get("width"), "Width",
                 int(defaults.get("width") or 512))
    height = _int(request.get("height"), "Height",
                  int(defaults.get("height") or 512))
    for name, value in (("Width", width), ("Height", height)):
        if value < MIN_EDGE:
            raise ValidationError(f"{name} must be at least {MIN_EDGE} px.")
        if value > max_edge:
            raise ValidationError(
                f"{name} {value} px exceeds {model['name']}'s limit of "
                f"{max_edge} px. Larger sizes also strain 6 GB of VRAM.")
        if value % step:
            raise ValidationError(
                f"{name} must be a multiple of {step} px for this model.")

    steps = _int(request.get("steps"), "Steps",
                 int(defaults.get("steps") or 25))
    if not MIN_STEPS <= steps <= MAX_STEPS:
        raise ValidationError(f"Steps must be between {MIN_STEPS} and {MAX_STEPS}.")

    cfg = _float(request.get("guidance_scale"), "Guidance scale",
                 float(defaults.get("guidance_scale") or 7.5))
    if not 0.0 <= cfg <= MAX_CFG:
        raise ValidationError(f"Guidance scale must be between 0 and {MAX_CFG:g}.")

    batch = _int(request.get("batch_size"), "Batch size", 1)
    max_batch = int(model.get("max_batch") or 1)
    if not 1 <= batch <= max_batch:
        raise ValidationError(
            f"Batch size must be between 1 and {max_batch} for {model['name']}.")
    pixels = width * height * batch
    # ~0.6 Mpx is the comfortable envelope for SD1.5 on 6 GB; above that the
    # card starts swapping and the job may die mid-way.
    if pixels > 1_200_000 and model.get("min_vram_gb", 99) > registry.TARGET_VRAM_GB:
        raise ValidationError(
            f"{width}×{height} × {batch} exceeds the safe memory envelope for "
            f"{model['name']} on this GPU. Lower the resolution or batch size.")

    seed_raw = request.get("seed", -1)
    seed = _int(seed_raw, "Seed", -1)
    if seed < 0:
        seed = random.randint(0, 2**32 - 1)
    if seed > 2**63 - 1:
        raise ValidationError("Seed is out of range.")

    negative = ""
    if model.get("supports_negative"):
        negative = _clean_text(request.get("negative_prompt"),
                               MAX_NEGATIVE_CHARS, "Negative prompt")

    fmt = str(request.get("output_format") or "png").lower().lstrip(".")
    if fmt not in OUTPUT_FORMATS:
        raise ValidationError("Output format must be PNG, JPG or WebP.")

    input_image = request.get("input_image")
    denoise = None
    if input_image:
        if registry.IMG2IMG not in caps:
            raise ValidationError(f"{model['name']} does not support image-to-image.")
        validate_input_image(input_image)
        denoise = _float(request.get("denoise_strength"),
                         "Denoise strength", 0.65)
        if not 0.05 <= denoise <= 1.0:
            raise ValidationError("Denoise strength must be between 0.05 and 1.0.")

    normalised = {
        "prompt": prompt,
        "negative_prompt": negative,
        "model_id": model["id"],
        "width": width,
        "height": height,
        "steps": steps,
        "guidance_scale": cfg,
        "seed": seed,
        "batch_size": batch,
        "output_format": fmt,
        "sampler": str(request.get("sampler") or "").strip(),
        "scheduler": str(request.get("scheduler") or "").strip(),
    }
    if input_image:
        normalised["input_image"] = str(input_image)
        normalised["denoise_strength"] = denoise
    return normalised


def unique_output_path(directory: Path, job_id: str, ext: str) -> Path:
    """A path that never overwrites an existing image.

    The name is built from the job id and a counter, never from user text, so
    a prompt cannot steer where a file lands.
    """
    directory.mkdir(parents=True, exist_ok=True)
    safe_job = re.sub(r"[^A-Za-z0-9_-]", "", job_id)[:16] or "job"
    stamp = __import__("time").strftime("%Y%m%d_%H%M%S")
    ext = ext.lower().lstrip(".")
    base = f"keysai_{stamp}_{safe_job}"
    candidate = directory / f"{base}.{ext}"
    n = 1
    while candidate.exists():
        n += 1
        candidate = directory / f"{base}_{n}.{ext}"
    return candidate


def validate_image_bytes(raw: bytes) -> dict:
    """Confirm the backend really returned an image; report its size/format."""
    if not raw:
        raise ValidationError("The backend returned an empty image.")
    if len(raw) < 100:
        raise ValidationError("The backend returned a suspiciously small file.")
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as im:
            fmt = (im.format or "").upper()
            w, h = im.size
            im.verify()
        if fmt not in ("PNG", "JPEG", "WEBP"):
            raise ValidationError(f"Unexpected image format from backend: {fmt}")
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"The backend's image could not be opened: {exc}")
    return {"format": fmt, "width": w, "height": h, "bytes": len(raw)}


__all__ = ["ValidationError", "validate_request", "validate_input_image",
           "validate_image_bytes", "unique_output_path", "OUTPUT_FORMATS"]
