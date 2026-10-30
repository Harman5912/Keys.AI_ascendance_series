"""
core/session_store.py — Session persistence for Keys.AI build jobs.

Saves/loads job state to disk so builds can resume after a crash.
Inspired by LangGraph checkpoint/resume and Goose durable sessions.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

_SESSIONS_DIR = Path(__file__).parent.parent / "sessions"


class SessionStore:
    def __init__(self):
        _SESSIONS_DIR.mkdir(exist_ok=True)

    def save(self, job_id: str, state: dict) -> None:
        p = _SESSIONS_DIR / f"{job_id}.json"
        payload = {"job_id": job_id, "saved_at": time.time(), "state": state}
        p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    def load(self, job_id: str) -> Optional[dict]:
        p = _SESSIONS_DIR / f"{job_id}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def list_sessions(self) -> list[dict]:
        sessions = []
        for p in sorted(_SESSIONS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                sessions.append({
                    "job_id": data.get("job_id", p.stem),
                    "saved_at": data.get("saved_at", 0),
                    "status": data.get("state", {}).get("status", "unknown"),
                })
            except Exception:
                pass
        return sessions

    def delete(self, job_id: str) -> bool:
        p = _SESSIONS_DIR / f"{job_id}.json"
        if p.exists():
            p.unlink()
            return True
        return False


_store = SessionStore()


def save_session(job_id: str, state: dict) -> None:
    _store.save(job_id, state)


def load_session(job_id: str) -> Optional[dict]:
    return _store.load(job_id)


def list_sessions() -> list[dict]:
    return _store.list_sessions()


def delete_session(job_id: str) -> bool:
    return _store.delete(job_id)
