"""Image worker — real Pillow operations plus the local image backend.

Inspection, resize, crop and format conversion run through Pillow on the actual
file. The original is always preserved: every write goes to a new file in the
task workspace.

Generation delegates to the AI Image Studio's local ComfyUI pipeline (or an
injected backend). It reports the backend's real state when unavailable — it
does not fall back to a cloud API and it never pretends an image exists.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from universal_agent import intake, security
from universal_agent.workers import Context

_EXT_FORMAT = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}


def _input_path(ctx: Context) -> Path:
    answers = ctx.task.get("answers") or {}
    raw = str(ctx.params.get("input_file") or answers.get("input_file")
              or intake.extract_input_file(ctx.task.get("request") or ""))
    if not raw:
        raise security.SecurityError(
            "No image file was supplied — this operation needs an input image.")
    return intake.resolve_input_path(raw)


def _operation(ctx: Context) -> str:
    op = str(ctx.params.get("operation") or "").lower()
    if op:
        return op
    text = str(ctx.task.get("request") or "").lower()
    # Generation and the deterministic Pillow operations are matched first;
    # editing verbs that Pillow does not implement are matched too, so they are
    # answered with "not supported, here is what is" instead of being quietly
    # treated as an inspection of the unchanged file.
    for candidate in ("generate", "resize", "crop", "convert", "rotate",
                      "edit", "blur", "sharpen", "retouch", "background",
                      "inpaint", "inspect"):
        if candidate in text:
            return candidate
    return "inspect"


def _dimensions(ctx: Context):
    width = ctx.params.get("width")
    height = ctx.params.get("height")
    if width or height:
        # One dimension is legal: the other is derived from the aspect ratio.
        return (int(width) if width else None,
                int(height) if height else None)
    m = re.search(r"\b(\d{2,4})\s*[x×]\s*(\d{2,4})\b",
                  str(ctx.task.get("request") or ""))
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _aspect(ctx: Context) -> float | None:
    text = str(ctx.task.get("request") or "").lower()
    m = re.search(r"\b(\d{1,2})\s*[:x×]\s*(\d{1,2})\b", text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return a / b if b else None
    if "square" in text or "1:1" in text:
        return 1.0
    return None


def _report(ctx: Context, title: str, rows: list[tuple[str, str]],
            notes: list[str] | None = None) -> Path:
    body = [f"# {title}", "",
            f"Generated: {time.strftime('%Y-%m-%d %H:%M')}", "",
            "| Property | Value |", "|---|---|"]
    body += [f"| {k} | {v} |" for k, v in rows]
    if notes:
        body += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    return ctx.write_text("image-report.md", "\n".join(body).strip() + "\n")


def _generate(ctx: Context) -> dict:
    prompt = str(ctx.task.get("request") or "").strip()
    backend = ctx.image_backend
    if backend is None:
        backend = _default_generate
    try:
        result = backend({
            "prompt": prompt,
            "task": ctx.task,
            "workspace": str(ctx.workspace),
            "log": ctx.log,
            "should_cancel": ctx.check_cancel,
        })
    except security.SecurityError:
        raise
    except Exception as exc:
        return {"ok": False, "summary": "Image generation failed.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": str(exc), "notes": []}

    images = [Path(p) for p in (result.get("images") or []) if Path(p).is_file()]
    if not result.get("ok") or not images:
        return {"ok": False,
                "summary": "No image was produced.",
                "artifacts": [], "evidence": [],
                "warnings": result.get("warnings") or [],
                "error": result.get("error") or "The backend returned no file.",
                "notes": result.get("notes") or []}

    artifacts = []
    for src in images:
        try:
            from PIL import Image
            with Image.open(src) as im:
                size = im.size
                fmt = im.format
            dest = security.unique_path(ctx.workspace, f"generated-{src.name}")
            dest.write_bytes(src.read_bytes())
            artifacts.append(ctx.artifact(dest, dest.suffix.lstrip("."),
                                          f"Generated {fmt} {size[0]}×{size[1]}"))
        except Exception as exc:
            return {"ok": False, "summary": "A generated image was unreadable.",
                    "artifacts": artifacts, "evidence": [], "warnings": [],
                    "error": f"Generated file could not be opened: {exc}",
                    "notes": []}
    report = _report(ctx, "Image generation", [
        ("Prompt", prompt[:300]),
        ("Model", str(result.get("model") or "local backend")),
        ("Seed", str(result.get("seed") or "")),
        ("Output", ", ".join(a["path"] for a in artifacts)),
    ], result.get("notes") or [])
    artifacts.append(ctx.artifact(report, "markdown", "Generation record"))
    return {"ok": True,
            "summary": (f"Generated {len(artifacts) - 1} image(s) with the "
                        "local backend."),
            "artifacts": artifacts, "evidence": [],
            "warnings": result.get("warnings") or [], "error": "",
            "notes": []}


def _default_generate(job: dict) -> dict:
    """Delegate to the local AI Image Studio service."""
    from core.image_studio import get_service
    svc = get_service()
    status = svc.backend_status(force=True)
    if not status.get("reachable"):
        return {"ok": False,
                "error": ("The local image backend (ComfyUI) is not running. "
                          "Open AI Image Studio → Backend to start it. No "
                          "cloud fallback is used.")}
    models = [m for m in svc.list_models() if m.get("installed")]
    if not models:
        return {"ok": False,
                "error": ("No image model is installed in ComfyUI. Install one "
                          "from AI Image Studio → Models.")}
    model = models[0]
    try:
        created = svc.generate({
            "prompt": job["prompt"],
            "model_id": model["id"],
            "width": model.get("preferred_edge") or 512,
            "height": model.get("preferred_edge") or 512,
            "output_format": "png",
            "seed": -1,
        })
    except Exception as exc:
        return {"ok": False, "error": f"Generation could not start: {exc}"}

    job_id = created.get("job_id", "")
    deadline = time.time() + 600
    while time.time() < deadline:
        if job.get("should_cancel") and job["should_cancel"]():
            svc.cancel_job(job_id)
            return {"ok": False, "error": "Generation cancelled."}
        current = svc.get_job(job_id) or {}
        if current.get("status") in ("completed", "failed", "cancelled"):
            if current.get("status") != "completed":
                return {"ok": False,
                        "error": current.get("error") or "Generation failed."}
            paths = [i.get("path") for i in current.get("images") or []
                     if i.get("path")]
            return {"ok": True, "images": paths, "model": model.get("name"),
                    "seed": current.get("seed")}
        time.sleep(0.5)
    svc.cancel_job(job_id)
    return {"ok": False, "error": "Generation timed out after 10 minutes."}


def run(ctx: Context) -> dict:
    operation = _operation(ctx)
    if operation == "generate":
        return _generate(ctx)

    try:
        source = _input_path(ctx)
    except security.SecurityError as exc:
        return {"ok": False, "summary": "The image path was refused.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": str(exc), "notes": []}

    from PIL import Image, ImageOps

    try:
        with Image.open(source) as im:
            im.load()
            original_size = im.size
            original_mode = im.mode
            original_format = im.format
            work = im.copy()
    except Exception as exc:
        return {"ok": False, "summary": "The image could not be opened.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": f"'{source.name}' is not a readable image: {exc}",
                "notes": []}

    notes = [f"Original preserved unchanged: {source}"]
    width, height = _dimensions(ctx)
    ext = source.suffix.lower() if source.suffix.lower() in _EXT_FORMAT else ".png"
    stem = security.safe_filename(source.stem, default="image", suffix="")
    stem = stem.rsplit(".", 1)[0]

    try:
        if operation == "resize":
            pct = re.search(r"\b(\d{1,3})\s*%\b",
                            str(ctx.task.get("request") or ""))
            if width and height:
                pass
            elif width:
                height = max(1, round(work.height * width / work.width))
            elif height:
                width = max(1, round(work.width * height / work.height))
            elif pct:
                ratio = max(1, min(1000, int(pct.group(1)))) / 100.0
                width = max(1, round(work.width * ratio))
                height = max(1, round(work.height * ratio))
            else:
                width = max(1, work.width // 2)
                height = max(1, work.height // 2)
            work = work.resize((int(width), int(height)), Image.LANCZOS)
            notes.append(f"Resized from {original_size[0]}×{original_size[1]} "
                         f"to {work.size[0]}×{work.size[1]}")
        elif operation == "crop":
            ratio = _aspect(ctx) or 1.0
            w, h = work.size
            if w / h > ratio:
                new_w = int(h * ratio)
                left = (w - new_w) // 2
                box = (left, 0, left + new_w, h)
            else:
                new_h = int(w / ratio)
                top = (h - new_h) // 2
                box = (0, top, w, top + new_h)
            work = work.crop(box)
            notes.append(f"Centre-cropped to aspect {ratio:.3f} "
                         f"({work.size[0]}×{work.size[1]})")
        elif operation == "rotate":
            angle = 90
            m = re.search(r"(\d{1,3})\s*(?:degrees|deg|°)",
                          str(ctx.task.get("request") or ""), re.I)
            if m:
                angle = int(m.group(1)) % 360
            work = work.rotate(-angle, expand=True)
            notes.append(f"Rotated {angle}°")
        elif operation == "convert":
            fmt = str(ctx.params.get("format") or "").lower().lstrip(".")
            if fmt not in ("png", "jpg", "jpeg", "webp"):
                m = re.search(r"\bto\s+(png|jpe?g|webp)\b",
                              str(ctx.task.get("request") or ""), re.I)
                fmt = (m.group(1).lower() if m else "png")
            ext = ".jpg" if fmt in ("jpg", "jpeg") else f".{fmt}"
            notes.append(f"Converted {original_format} → {ext[1:].upper()}")
        elif operation == "inspect":
            pass
        else:
            return {"ok": False,
                    "summary": f"Unsupported image operation '{operation}'.",
                    "artifacts": [], "evidence": [], "warnings": [],
                    "error": (f"'{operation}' is not implemented. Supported: "
                              "inspect, resize, crop, convert, rotate, generate."),
                    "notes": []}
    except Exception as exc:
        return {"ok": False, "summary": "The image operation failed.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": f"{operation} failed: {exc}", "notes": []}

    target_format = _EXT_FORMAT.get(ext, "PNG")
    if target_format == "JPEG" and work.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", work.size, (255, 255, 255))
        rgba = work.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        work = background
        notes.append("Transparency flattened onto white for JPEG")
    elif target_format in ("PNG", "WEBP") and work.mode not in ("RGB", "RGBA", "L"):
        work = work.convert("RGBA" if "A" in work.getbands() else "RGB")

    dest = security.unique_path(
        ctx.workspace,
        f"{stem}-{operation}{ext if operation != 'inspect' else '.png'}")
    dest = security.resolve_within(ctx.workspace, dest)
    try:
        save_kwargs = {"quality": 92} if target_format in ("JPEG", "WEBP") else {}
        work.save(dest, format=target_format, **save_kwargs)
    except Exception as exc:
        return {"ok": False, "summary": "The edited image could not be saved.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": f"Save failed: {exc}", "notes": []}

    with Image.open(dest) as check:
        out_size = check.size
        out_format = check.format

    rows = [
        ("Source", source.name),
        ("Source size", f"{original_size[0]}×{original_size[1]}"),
        ("Source mode", original_mode),
        ("Operation", operation),
        ("Output", dest.name),
        ("Output size", f"{out_size[0]}×{out_size[1]}"),
        ("Output format", out_format),
    ]
    report = _report(ctx, f"Image {operation}: {source.name}", rows, notes)
    ctx.log(f"Image {operation}: {dest.name} ({out_size[0]}×{out_size[1]})")

    return {
        "ok": True,
        "summary": (f"{operation.capitalize()} complete — "
                    f"{out_size[0]}×{out_size[1]} {out_format}."),
        "artifacts": [
            ctx.artifact(dest, out_format.lower() if out_format else "png",
                         f"{operation} output"),
            ctx.artifact(report, "markdown", "Image operation record"),
        ],
        "evidence": [],
        "warnings": [],
        "error": "",
        "notes": notes,
    }


__all__ = ["run"]
