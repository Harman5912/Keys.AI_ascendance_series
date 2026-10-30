"""Real asset retrieval with validation.

A URL is not an asset: what matters is the bytes that arrive. Everything here
streams with a hard size cap, identifies the file from its content (never the
extension or the Content-Type alone), decodes images before calling them
usable, and refuses HTML error pages that servers happily return with a 200.

Downloads land in a task workspace under a generated name, so a hostile URL
cannot choose a path or overwrite an existing file.
"""

from __future__ import annotations

import hashlib
import io
import re
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from core.research_browser import paths

CHUNK = 256 * 1024
IMAGE_FORMATS = {
    "PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "WEBP": ".webp",
    "BMP": ".bmp", "TIFF": ".tiff",
}
DOC_FORMATS = {"pdf": ".pdf", "docx": ".docx", "pptx": ".pptx", "xlsx": ".xlsx",
               "zip": ".zip", "text": ".txt"}


class AssetError(RuntimeError):
    """The resource could not be retrieved or is not usable."""


def _safe_name(url: str, fallback: str = "asset") -> str:
    raw = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    stem = Path(raw).stem if raw else fallback
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", stem).strip("._") or fallback
    return stem[:60]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff_kind(data: bytes) -> str:
    """Identify a file from its magic bytes."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    if data.startswith(b"BM"):
        return "BMP"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "TIFF"
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        # Office Open XML is a zip; the mimetype entry names the real type.
        head = data[:4096]
        if b"word/" in head or b"wordprocessingml" in head:
            return "docx"
        if b"ppt/" in head or b"presentationml" in head:
            return "pptx"
        if b"xl/" in head or b"spreadsheetml" in head:
            return "xlsx"
        return "zip"
    if b"<html" in data[:2048].lower() or b"<!doctype html" in data[:2048].lower():
        return "html"
    try:
        data[:4096].decode("utf-8")
        return "text"
    except Exception:
        return "binary"


def decode_image(data: bytes) -> dict:
    """PIL must be able to open and verify the bytes, or they are not an image."""
    try:
        from PIL import Image
    except Exception as exc:                     # pragma: no cover
        raise AssetError(f"Pillow is unavailable: {exc}")
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").upper()
            width, height = im.size
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            im.convert("RGB").load()
    except Exception as exc:
        raise AssetError(f"The downloaded data is not a readable image ({exc}).")
    if fmt not in IMAGE_FORMATS:
        raise AssetError(f"Unsupported image format: {fmt}.")
    if width < 2 or height < 2:
        raise AssetError(f"The image is {width}×{height} — too small to use.")
    return {"format": fmt, "width": width, "height": height,
            "extension": IMAGE_FORMATS[fmt]}


def validate_bytes(data: bytes, *, declared_type: str = "",
                   expect: str = "image") -> dict:
    """Return metadata for usable bytes, or raise AssetError."""
    if not data:
        raise AssetError("The server returned an empty response.")
    kind = sniff_kind(data)
    if kind == "html":
        raise AssetError("The server returned an HTML page, not the file itself "
                         "(often a login wall or a 404 page).")
    if expect == "image":
        if kind not in IMAGE_FORMATS:
            raise AssetError(
                f"Expected an image but the content is {kind}. "
                f"Declared type was {declared_type or 'unknown'}.")
        meta = decode_image(data)
        meta.update({"kind": "image", "content_kind": kind,
                     "sha256": _sha256_bytes(data), "bytes": len(data)})
        return meta
    if kind not in DOC_FORMATS and kind not in IMAGE_FORMATS:
        raise AssetError(f"Unsupported file content: {kind}.")
    if kind == "text" and len(data) > 5_000_000:
        raise AssetError("Text resources larger than 5 MB are not collected.")
    extension = IMAGE_FORMATS.get(kind) or DOC_FORMATS.get(kind, ".bin")
    return {"kind": "document" if kind not in IMAGE_FORMATS else "image",
            "content_kind": kind, "format": kind.upper(),
            "extension": extension, "sha256": _sha256_bytes(data),
            "bytes": len(data), "width": 0, "height": 0}


def unique_path(directory: Path, stem: str, extension: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    base = f"{stem}_{uuid.uuid4().hex[:8]}"
    candidate = directory / f"{base}{extension}"
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = directory / f"{base}_{counter}{extension}"
    return candidate


def fetch(url: str, *, task_id: str = "", dest_dir: Path | None = None,
          expect: str = "image", max_bytes: int | None = None,
          timeout: float = 30.0, should_cancel=None,
          headers: dict | None = None) -> dict:
    """Download a real resource and return its verified metadata.

    Raises AssetError with a user-facing reason on any failure.
    """
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise AssetError(f"'{parsed.scheme or 'unknown'}:' URLs cannot be fetched.")
    if not parsed.hostname:
        raise AssetError("That URL has no host.")
    limit = int(max_bytes if max_bytes is not None else paths.max_download_bytes())
    target_dir = Path(dest_dir) if dest_dir else (
        paths.task_workspace(task_id) / "assets")
    request_headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/126.0.0.0 Safari/537.36"),
        "Accept": "image/*,*/*;q=0.8",
    }
    request_headers.update(headers or {})
    started = time.monotonic()
    try:
        resp = requests.get(url, headers=request_headers, stream=True,
                            timeout=timeout, allow_redirects=True)
    except requests.Timeout:
        raise AssetError(f"Timed out after {timeout:g}s fetching {parsed.netloc}.")
    except Exception as exc:
        raise AssetError(f"Download failed: {exc}")
    if resp.status_code >= 400:
        resp.close()
        raise AssetError(f"The server returned HTTP {resp.status_code}.")
    declared = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
    declared_len = resp.headers.get("Content-Length")
    if declared_len and declared_len.isdigit() and int(declared_len) > limit:
        resp.close()
        raise AssetError(
            f"That file is {int(declared_len) / 1e6:.1f} MB — the limit is "
            f"{limit / 1e6:.0f} MB.")
    buffer = bytearray()
    try:
        for chunk in resp.iter_content(CHUNK):
            if should_cancel and should_cancel():
                resp.close()
                raise AssetError("Download cancelled.")
            if not chunk:
                continue
            buffer.extend(chunk)
            if len(buffer) > limit:
                resp.close()
                raise AssetError(
                    f"Download exceeded the {limit / 1e6:.0f} MB limit and was "
                    "stopped.")
    except AssetError:
        raise
    except requests.Timeout:
        raise AssetError("The download stalled and timed out.")
    except Exception as exc:
        raise AssetError(f"Download failed while reading: {exc}")
    finally:
        try:
            resp.close()
        except Exception:
            pass
    data = bytes(buffer)
    meta = validate_bytes(data, declared_type=declared, expect=expect)
    dest = unique_path(target_dir, _safe_name(url), meta["extension"])
    dest.write_bytes(data)
    # Re-open what was written; a partial write must not become an asset.
    if dest.stat().st_size != len(data):
        dest.unlink(missing_ok=True)
        raise AssetError("The file on disk does not match what was downloaded.")
    if meta["kind"] == "image":
        decode_image(dest.read_bytes())
    return {
        "ok": True,
        "path": str(dest),
        "filename": dest.name,
        "source_url": url,
        "final_url": resp.url,
        "content_type": declared,
        "kind": meta["kind"],
        "format": meta.get("format", ""),
        "width": meta.get("width", 0),
        "height": meta.get("height", 0),
        "bytes": meta["bytes"],
        "sha256": meta["sha256"],
        "elapsed_s": round(time.monotonic() - started, 2),
        "retrieved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def import_local(path: str, *, task_id: str = "", dest_dir: Path | None = None,
                 expect: str = "image") -> dict:
    """Copy a user-provided file into the task workspace after validating it."""
    source = Path(str(path or ""))
    if not source.is_file():
        raise AssetError(f"File not found: {source}")
    data = source.read_bytes()
    meta = validate_bytes(data, expect=expect)
    target_dir = Path(dest_dir) if dest_dir else (
        paths.task_workspace(task_id) / "assets")
    dest = unique_path(target_dir, _safe_name(source.name), meta["extension"])
    dest.write_bytes(data)
    return {"ok": True, "path": str(dest), "filename": dest.name,
            "source_url": f"file://{source.resolve()}", "final_url": "",
            "content_type": "", "kind": meta["kind"],
            "format": meta.get("format", ""), "width": meta.get("width", 0),
            "height": meta.get("height", 0), "bytes": meta["bytes"],
            "sha256": meta["sha256"], "elapsed_s": 0.0,
            "retrieved_at": time.strftime("%Y-%m-%d %H:%M:%S")}


__all__ = ["AssetError", "fetch", "import_local", "validate_bytes",
           "decode_image", "sniff_kind", "unique_path", "IMAGE_FORMATS",
           "DOC_FORMATS"]
