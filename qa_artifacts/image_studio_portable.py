"""Fetch + extract the official ComfyUI Windows portable bundle.

Windows' Store-only Python cannot build a working venv, so the portable bundle
(embedded Python + CUDA PyTorch) is the reliable backend for this machine. This
script downloads it into %LOCALAPPDATA%\\KeysAI and extracts it with py7zr.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import requests

URL = ("https://github.com/comfyanonymous/ComfyUI/releases/latest/download/"
       "ComfyUI_windows_portable_nvidia.7z")
BASE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "KeysAI"
ARCHIVE = BASE / "ComfyUI_windows_portable_nvidia.7z"
# Not under %LOCALAPPDATA%: the Microsoft Store Python silently redirects writes
# there into its MSIX package sandbox, and ComfyUI's embedded Python (a normal
# process) would then not see the files. A folder directly under the home
# directory is not redirected.
DEST = Path.home() / "KeysAI" / "ComfyUI_portable"


def log(msg: str) -> None:
    print(msg, flush=True)


def download() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    part = ARCHIVE.with_name(ARCHIVE.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "KeysAI-ImageStudio-test/1.0"}
    if have:
        headers["Range"] = f"bytes={have}-"
    resp = requests.get(URL, headers=headers, stream=True, timeout=60,
                        allow_redirects=True)
    log(f"HTTP {resp.status_code}  resuming at {have / 1e9:.2f} GB")
    if resp.status_code == 200 and have:
        have = 0
        mode = "wb"
    elif resp.status_code == 206:
        mode = "ab"
    elif resp.status_code == 200:
        mode = "wb"
    else:
        raise SystemExit(f"download failed: HTTP {resp.status_code}")
    total = int(resp.headers.get("Content-Length") or 0) + have
    got = have
    started = time.monotonic()
    last = 0.0
    with open(part, mode) as fh:
        for chunk in resp.iter_content(1024 * 1024):
            if not chunk:
                continue
            fh.write(chunk)
            got += len(chunk)
            now = time.monotonic()
            if now - last > 5:
                last = now
                pct = (got / total * 100) if total else 0
                speed = got / max(0.001, now - started) / 1e6
                log(f"  {pct:5.1f}%  {got / 1e9:.2f}/{total / 1e9:.2f} GB"
                    f"  {speed:.1f} MB/s")
    os.replace(part, ARCHIVE)
    log(f"downloaded {ARCHIVE} ({ARCHIVE.stat().st_size / 1e9:.2f} GB)")


def extract() -> None:
    import py7zr
    if DEST.exists() and any(DEST.iterdir()):
        log(f"{DEST} already exists — leaving it alone")
        return
    DEST.mkdir(parents=True, exist_ok=True)
    log(f"extracting into {DEST} (this takes a few minutes)")
    with py7zr.SevenZipFile(ARCHIVE, "r") as z:
        names = z.getnames()
        log(f"archive entries: {len(names)}")
        z.extractall(path=DEST)
    log("extracted")


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("download", "all"):
        download()
    if step in ("extract", "all"):
        extract()
    root = DEST / "ComfyUI" / "main.py"
    if root.is_file():
        log(f"OK main.py at {root}")
    else:
        log("main.py not found after extraction")
