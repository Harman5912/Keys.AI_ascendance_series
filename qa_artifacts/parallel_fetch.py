"""Parallel range downloader for the SD 1.5 checkpoint.

A single Hugging Face stream was measured at ~0.27 MB/s on this network (4+
hours for 4.1 GB). This fetches the same URL over several byte ranges, then
verifies the complete file against the registry's official SHA-256 before it is
installed — the same digest ``downloads.download_file`` checks.

    python qa_artifacts/parallel_fetch.py <url> <dest> <expected_sha256> [workers]
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
import time
from pathlib import Path

import requests

CHUNK = 512 * 1024


def want_ranges(url: str, workers: int) -> tuple[int, bool]:
    resp = requests.get(url, headers={"Range": "bytes=0-0"}, stream=True,
                        timeout=30, allow_redirects=True)
    try:
        content_range = resp.headers.get("Content-Range", "")
        total = int(content_range.rsplit("/", 1)[-1]) if "/" in content_range else 0
        if not total:
            total = int(resp.headers.get("Content-Length") or 0)
        ranges_ok = resp.status_code == 206 and total > 0
        return total, ranges_ok
    finally:
        resp.close()


def fetch_range(url: str, start: int, end: int, path: Path, state: dict,
                lock: threading.Lock, index: int) -> None:
    headers = {"Range": f"bytes={start}-{end - 1}"}
    for attempt in range(6):
        try:
            with requests.get(url, headers=headers, stream=True, timeout=60,
                              allow_redirects=True) as resp:
                if resp.status_code not in (200, 206):
                    raise RuntimeError(f"HTTP {resp.status_code}")
                with open(path, "r+b") as fh:
                    fh.seek(start)
                    position = start
                    for chunk in resp.iter_content(CHUNK):
                        if not chunk:
                            continue
                        if position + len(chunk) > end:
                            chunk = chunk[:end - position]
                        fh.write(chunk)
                        position += len(chunk)
                        with lock:
                            state["done"] += len(chunk)
                        if position >= end:
                            break
                if position >= end:
                    return
        except Exception as exc:
            with lock:
                state["errors"][index] = str(exc)
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"range worker {index} failed: {state['errors'].get(index)}")


def download(url: str, dest: Path, sha256: str = "", workers: int = 8) -> int:
    total, ranges_ok = want_ranges(url, workers)
    if not total:
        raise SystemExit("server did not report a size")
    print(f"size {total / 1e9:.2f} GB, ranged={ranges_ok}", flush=True)
    if not ranges_ok:
        workers = 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as fh:
        fh.truncate(total)
    span = total // workers
    bounds = []
    for i in range(workers):
        start = i * span
        end = total if i == workers - 1 else (i + 1) * span
        bounds.append((start, end))
    state = {"done": 0, "errors": {}}
    lock = threading.Lock()
    threads = [threading.Thread(target=fetch_range,
                                args=(url, s, e, dest, state, lock, i),
                                daemon=True)
               for i, (s, e) in enumerate(bounds)]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    last = 0.0
    while any(t.is_alive() for t in threads):
        time.sleep(5)
        now = time.monotonic()
        with lock:
            done = state["done"]
        if now - last > 15:
            last = now
            speed = done / max(0.001, now - started) / 1e6
            pct = done / total * 100
            print(f"  {pct:5.1f}%  {done / 1e9:.2f}/{total / 1e9:.2f} GB  "
                  f"{speed:.1f} MB/s", flush=True)
    if state["done"] < total:
        raise SystemExit(f"incomplete: {state['done']} of {total}")
    print(f"downloaded in {time.monotonic() - started:.0f}s", flush=True)
    if sha256:
        digest = hashlib.sha256()
        with open(dest, "rb") as fh:
            for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        print(f"sha256 {actual}", flush=True)
        if actual.lower() != sha256.lower():
            raise SystemExit("checksum mismatch — NOT installed")
        print("checksum OK", flush=True)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    raise SystemExit(download(sys.argv[1], Path(sys.argv[2]),
                              sys.argv[3] if len(sys.argv) > 3 else "",
                              workers))
