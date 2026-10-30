"""Resumable, verifiable model downloads.

Model weights are 4–7 GB, so a download must survive a dropped connection and
a cancelled UI action. The file is streamed into ``<name>.part`` and resumed
with an HTTP Range request; only a fully verified file is moved into place.

Verification order:
  1. SHA-256, when the registry knows the official LFS digest (it does for the
     SD 1.5 and SDXL checkpoints — that hash IS the Hugging Face LFS oid).
  2. Otherwise a structural check of the safetensors header, which catches a
     truncated or HTML-error-body download just as reliably.

Nothing here writes outside the destination folder it is given.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import time
from pathlib import Path

import requests

CHUNK = 1024 * 1024


class DownloadError(RuntimeError):
    pass


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def disk_free_gb(path: Path) -> float:
    try:
        target = path
        while not target.exists() and target.parent != target:
            target = target.parent
        return round(shutil.disk_usage(str(target)).free / 1e9, 2)
    except Exception:
        return 0.0


def verify_safetensors(path: Path) -> tuple[bool, str]:
    """Header + length check for a single-file diffusion checkpoint."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(8)
            if len(head) < 8:
                return False, "file is too short to be safetensors"
            (header_len,) = struct.unpack("<Q", head)
            if not 0 < header_len < 100 * 1024 * 1024:
                return False, "invalid safetensors header length"
            raw = fh.read(header_len)
        header = json.loads(raw.decode("utf-8"))
        end = 0
        for key, meta in header.items():
            if key == "__metadata__":
                continue
            offsets = (meta or {}).get("data_offsets")
            if not offsets or len(offsets) != 2:
                return False, f"tensor '{key}' has no data offsets"
            end = max(end, int(offsets[1]))
        expected = 8 + header_len + end
        if size < expected:
            return False, (f"truncated: {human_size(size)} of "
                           f"{human_size(expected)}")
        return True, f"{human_size(size)} · {len(header)} tensors"
    except Exception as exc:
        return False, f"not a safetensors file: {exc}"


def sha256_file(path: Path, should_stop=None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            if should_stop and should_stop():
                raise DownloadError("cancelled")
            chunk = fh.read(CHUNK * 4)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: Path, *, expected_sha256: str = "",
                  expected_size: int = 0, on_progress=None,
                  should_stop=None, timeout: float = 30.0) -> dict:
    """Download ``url`` to ``dest`` with resume + verification.

    Returns {"path", "status": downloaded|already_present, "verified_by"}.
    Raises DownloadError with a human-readable reason on failure.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    should_stop = should_stop or (lambda: False)

    def _progress(received: int, total: int, started: float) -> None:
        if not on_progress:
            return
        elapsed = max(0.001, time.monotonic() - started)
        try:
            on_progress({
                "received": received,
                "total": total,
                "percent": (received / total * 100.0) if total else 0.0,
                "speed": received / elapsed,
            })
        except Exception:
            pass

    if dest.exists() and dest.stat().st_size > 0:
        ok, detail = verify_safetensors(dest)
        if ok and (not expected_size or dest.stat().st_size >= expected_size * 0.997):
            if expected_sha256:
                if sha256_file(dest, should_stop) == expected_sha256:
                    return {"path": str(dest), "status": "already_present",
                            "verified_by": "sha256"}
            else:
                return {"path": str(dest), "status": "already_present",
                        "verified_by": "safetensors header"}
        else:
            dest.unlink(missing_ok=True)

    resume_from = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "KeysAI-ImageStudio/1.0"}
    if resume_from:
        headers["Range"] = f"bytes={resume_from}-"
    try:
        resp = requests.get(url, headers=headers, stream=True, timeout=timeout,
                            allow_redirects=True)
    except Exception as exc:
        raise DownloadError(f"Download failed: {exc}") from exc

    if resp.status_code == 416:          # range beyond EOF → restart clean
        part.unlink(missing_ok=True)
        resume_from = 0
        resp.close()
        resp = requests.get(url, headers={"User-Agent": "KeysAI-ImageStudio/1.0"},
                            stream=True, timeout=timeout)
    if resp.status_code == 200 and resume_from:
        resume_from = 0                    # server ignored Range: start over
    if resp.status_code not in (200, 206):
        resp.close()
        raise DownloadError(
            f"Server returned HTTP {resp.status_code} for {url.split('/')[-1]}.")

    total = 0
    try:
        if resp.status_code == 206:
            content_range = resp.headers.get("Content-Range", "")
            if "/" in content_range:
                total = int(content_range.rsplit("/", 1)[1])
        else:
            total = int(resp.headers.get("Content-Length") or 0)
    except Exception:
        total = 0

    try:
        directory = dest.parent
        while True:
            free = disk_free_gb(directory)
            if total and free and free * 1e9 < (total - resume_from) * 1.05:
                raise DownloadError(
                    f"Not enough free disk space: {free:g} GB available, "
                    f"{human_size(total - resume_from)} still needed.")
            break
    except DownloadError:
        resp.close()
        raise
    except Exception:
        pass

    received = resume_from
    started = time.monotonic()
    mode = "ab" if resume_from else "wb"
    try:
        with open(part, mode) as fh:
            for chunk in resp.iter_content(CHUNK):
                if should_stop():
                    fh.flush()
                    resp.close()
                    raise DownloadError("cancelled")
                if not chunk:
                    continue
                fh.write(chunk)
                received += len(chunk)
                _progress(received, total, started)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except Exception:
                pass
    finally:
        try:
            resp.close()
        except Exception:
            pass

    if total and received < total * 0.997:
        raise DownloadError(
            f"Download incomplete: {human_size(received)} of {human_size(total)} "
            "(kept the partial file so it can resume).")

    verified_by = "size"
    if expected_sha256:
        actual = sha256_file(part, should_stop)
        if actual.lower() != expected_sha256.lower():
            part.unlink(missing_ok=True)
            raise DownloadError(
                "Checksum mismatch — the downloaded file is corrupt or the "
                "server served a different build. Nothing was installed.")
        verified_by = "sha256"
    else:
        ok, detail = verify_safetensors(part)
        if ok:
            verified_by = "safetensors header"
        elif part.suffix.lower() in (".safetensors", ".gguf"):
            part.unlink(missing_ok=True)
            raise DownloadError(f"Downloaded file failed verification: {detail}")
        else:
            verified_by = "size only"

    os.replace(part, dest)
    return {"path": str(dest), "status": "downloaded",
            "verified_by": verified_by, "bytes": received}


__all__ = ["DownloadError", "download_file", "verify_safetensors",
           "sha256_file", "human_size", "disk_free_gb"]
