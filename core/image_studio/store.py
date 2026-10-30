"""Persistent generation history for AI Image Studio.

The app has no database, and the existing storage convention is a small JSON
file in ``config/`` (window_state.json, brain.json, pairing.json …). History
follows that convention: one JSON file, one process-wide lock, atomic replace —
so a crash during a write cannot leave a half-written index.

Only the fields needed to reopen a generation are stored. No prompt is uploaded
anywhere, no API credentials are recorded, and generated images are written to
the configured output directory rather than into the repository.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

_LOCK = threading.RLock()
MAX_RECORDS = 500


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


HISTORY_PATH = _base_dir() / "config" / "image_studio_history.json"


def _read() -> list[dict]:
    try:
        raw = HISTORY_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except Exception:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        # Never destroy an unreadable history: keep it for inspection.
        try:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            os.replace(HISTORY_PATH,
                       HISTORY_PATH.with_name(f"image_studio_history.corrupt-{stamp}.json"))
        except Exception:
            pass
        return []
    records = data.get("records") if isinstance(data, dict) else data
    return [r for r in records if isinstance(r, dict)] if isinstance(records, list) else []


def _write(records: list[dict]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_PATH.with_name(HISTORY_PATH.name + f".tmp{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "records": records}, fh,
                      indent=2, ensure_ascii=False)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except Exception:
                pass
        os.replace(tmp, HISTORY_PATH)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def add(record: dict) -> dict:
    with _LOCK:
        records = _read()
        records.append(dict(record))
        records = records[-MAX_RECORDS:]
        _write(records)
        return dict(record)


def update(job_id: str, patch: dict) -> dict | None:
    """Merge ``patch`` into the record with this id. Returns the new record."""
    with _LOCK:
        records = _read()
        found = None
        for rec in records:
            if rec.get("job_id") == job_id:
                rec.update(patch or {})
                found = dict(rec)
                break
        if found is not None:
            _write(records)
        return found


def get(job_id: str) -> dict | None:
    with _LOCK:
        for rec in _read():
            if rec.get("job_id") == job_id:
                return dict(rec)
    return None


def list_records(limit: int = 200) -> list[dict]:
    """Newest first."""
    with _LOCK:
        records = _read()
    records.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return records[:max(1, int(limit))]


def remove(job_id: str) -> bool:
    with _LOCK:
        records = _read()
        kept = [r for r in records if r.get("job_id") != job_id]
        if len(kept) == len(records):
            return False
        _write(kept)
        return True


def clear() -> int:
    with _LOCK:
        n = len(_read())
        _write([])
        return n


__all__ = ["HISTORY_PATH", "add", "update", "get", "list_records", "remove",
           "clear"]
