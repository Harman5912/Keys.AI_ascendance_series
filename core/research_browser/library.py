"""Persistent research library: sources, collected assets and evidence.

One JSON file in ``config/`` (the app's existing storage convention — the same
approach as the chat history, image-studio history and window state), guarded
by a process lock and written atomically so a crash cannot leave half a record.

The important rule this module enforces: a record only exists because something
was actually retrieved. ``add_source`` requires a URL, ``add_asset`` requires
real bytes on disk, and an asset's licence status is explicit rather than
assumed — "unknown" is a value, not an omission.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path

from core.research_browser import paths

_LOCK = threading.RLock()
MAX_RECORDS = 2000

LICENSE_STATUSES = ("unknown", "public-domain", "open-licence", "stock-licence",
                    "user-provided", "permission-granted", "do-not-reuse")


def _read() -> dict:
    path = paths.library_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"version": 1, "sources": [], "assets": [], "evidence": []}
    except Exception:
        return {"version": 1, "sources": [], "assets": [], "evidence": []}
    try:
        data = json.loads(raw)
    except Exception:
        # Keep an unreadable library for inspection instead of overwriting it.
        try:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            os.replace(path, path.with_name(f"research_library.corrupt-{stamp}.json"))
        except Exception:
            pass
        return {"version": 1, "sources": [], "assets": [], "evidence": []}
    if not isinstance(data, dict):
        return {"version": 1, "sources": [], "assets": [], "evidence": []}
    for key in ("sources", "assets", "evidence"):
        if not isinstance(data.get(key), list):
            data[key] = []
    return data


def _write(data: dict) -> None:
    path = paths.library_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except Exception:
                pass
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ── sources ────────────────────────────────────────────────────────────────
def add_source(url: str, *, title: str = "", task_id: str = "",
               question: str = "", source_type: str = "web",
               excerpt: str = "", published: str = "", method: str = "browser",
               inspected: bool = False, verification: str = "unverified",
               note: str = "") -> dict:
    if not str(url or "").strip():
        raise ValueError("A source needs a URL — nothing was retrieved.")
    with _LOCK:
        data = _read()
        for existing in data["sources"]:
            if existing.get("url") == url and existing.get("task_id") == task_id:
                return dict(existing)
        record = {
            "source_id": _new_id("src"),
            "url": url,
            "title": title,
            "domain": _domain(url),
            "task_id": task_id,
            "question": question,
            "source_type": source_type,
            "excerpt": excerpt[:4000],
            "published": published,
            "retrieved_at": _now(),
            "method": method,
            "inspected": bool(inspected),
            "verification": verification,
            "status": "inspected" if inspected else "discovered",
            "note": note,
            "screenshots": [],
            "assets": [],
            "evidence": [],
        }
        data["sources"].append(record)
        data["sources"] = data["sources"][-MAX_RECORDS:]
        _write(data)
        return dict(record)


def update_source(source_id: str, **patch) -> dict | None:
    with _LOCK:
        data = _read()
        for record in data["sources"]:
            if record.get("source_id") == source_id:
                record.update(patch or {})
                _write(data)
                return dict(record)
    return None


def mark_inspected(source_id: str, *, title: str = "", excerpt: str = "",
                   screenshot: str = "") -> dict | None:
    with _LOCK:
        data = _read()
        for record in data["sources"]:
            if record.get("source_id") == source_id:
                record["inspected"] = True
                record["status"] = "inspected"
                record["verification"] = "retrieved"
                record["inspected_at"] = _now()
                if title:
                    record["title"] = title
                if excerpt:
                    record["excerpt"] = excerpt[:4000]
                if screenshot:
                    shots = record.setdefault("screenshots", [])
                    if screenshot not in shots:
                        shots.append(screenshot)
                _write(data)
                return dict(record)
    return None


def record_failure(url: str, *, task_id: str = "", error: str = "",
                   question: str = "") -> dict:
    with _LOCK:
        data = _read()
        record = {
            "source_id": _new_id("src"),
            "url": url,
            "title": "",
            "domain": _domain(url),
            "task_id": task_id,
            "question": question,
            "source_type": "web",
            "excerpt": "",
            "published": "",
            "retrieved_at": _now(),
            "method": "browser",
            "inspected": False,
            "verification": "failed",
            "status": "unreachable",
            "note": error[:500],
            "screenshots": [],
            "assets": [],
            "evidence": [],
        }
        data["sources"].append(record)
        data["sources"] = data["sources"][-MAX_RECORDS:]
        _write(data)
        return dict(record)


def list_sources(task_id: str = "", limit: int = 200) -> list[dict]:
    with _LOCK:
        data = _read()
    records = [r for r in data["sources"]
               if not task_id or r.get("task_id") == task_id]
    records.sort(key=lambda r: str(r.get("retrieved_at") or ""), reverse=True)
    return [dict(r) for r in records[:max(1, limit)]]


def get_source(source_id: str) -> dict | None:
    with _LOCK:
        for record in _read()["sources"]:
            if record.get("source_id") == source_id:
                return dict(record)
    return None


def remove_source(source_id: str) -> bool:
    with _LOCK:
        data = _read()
        kept = [r for r in data["sources"] if r.get("source_id") != source_id]
        if len(kept) == len(data["sources"]):
            return False
        data["sources"] = kept
        _write(data)
        return True


# ── assets ─────────────────────────────────────────────────────────────────
def add_asset(path: str, *, source_url: str = "", page_url: str = "",
              task_id: str = "", width: int = 0, height: int = 0,
              fmt: str = "", size_bytes: int = 0, sha256: str = "",
              license_status: str = "unknown", attribution: str = "",
              filename: str = "", kind: str = "image",
              project_id: str = "", captured_at: str = "") -> dict:
    local = Path(str(path or ""))
    if not local.is_file():
        raise ValueError("An asset record needs a file that exists on disk.")
    digest = sha256 or _sha256(local)
    with _LOCK:
        data = _read()
        for existing in data["assets"]:
            if existing.get("sha256") == digest and existing.get("task_id") == task_id:
                return dict(existing)
        record = {
            "asset_id": _new_id("ast"),
            "path": str(local),
            "filename": filename or local.name,
            "source_url": source_url,
            "page_url": page_url,
            "task_id": task_id,
            "project_id": project_id,
            "kind": kind,
            "format": (fmt or local.suffix.lstrip(".")).upper(),
            "width": int(width or 0),
            "height": int(height or 0),
            "size_bytes": int(size_bytes or local.stat().st_size),
            "sha256": digest,
            "license_status": (license_status
                               if license_status in LICENSE_STATUSES else "unknown"),
            "attribution": attribution,
            "collected_at": captured_at or _now(),
            "approved": False,
            "used_by": [],
        }
        data["assets"].append(record)
        data["assets"] = data["assets"][-MAX_RECORDS:]
        _write(data)
        return dict(record)


def update_asset(asset_id: str, **patch) -> dict | None:
    with _LOCK:
        data = _read()
        for record in data["assets"]:
            if record.get("asset_id") == asset_id:
                if "license_status" in patch and \
                        patch["license_status"] not in LICENSE_STATUSES:
                    patch["license_status"] = "unknown"
                record.update(patch or {})
                _write(data)
                return dict(record)
    return None


def approve_asset(asset_id: str, approved: bool = True) -> dict | None:
    return update_asset(asset_id, approved=bool(approved))


def list_assets(task_id: str = "", limit: int = 200) -> list[dict]:
    with _LOCK:
        data = _read()
    records = [r for r in data["assets"]
               if not task_id or r.get("task_id") == task_id]
    records.sort(key=lambda r: str(r.get("collected_at") or ""), reverse=True)
    return [dict(r) for r in records[:max(1, limit)]]


def get_asset(asset_id: str) -> dict | None:
    with _LOCK:
        for record in _read()["assets"]:
            if record.get("asset_id") == asset_id:
                return dict(record)
    return None


def find_asset_by_hash(sha256: str, task_id: str = "") -> dict | None:
    with _LOCK:
        for record in _read()["assets"]:
            if record.get("sha256") == sha256 and \
                    (not task_id or record.get("task_id") == task_id):
                return dict(record)
    return None


def link_usage(asset_id: str, artifact: str, *, role: str = "embedded") -> dict | None:
    with _LOCK:
        data = _read()
        for record in data["assets"]:
            if record.get("asset_id") == asset_id:
                used = record.setdefault("used_by", [])
                if not any(u.get("artifact") == artifact and u.get("role") == role
                           for u in used):
                    used.append({"artifact": artifact, "role": role,
                                 "linked_at": _now()})
                _write(data)
                return dict(record)
    return None


def remove_asset(asset_id: str, delete_file: bool = False) -> dict:
    with _LOCK:
        data = _read()
        target = None
        kept = []
        for record in data["assets"]:
            if record.get("asset_id") == asset_id:
                target = record
            else:
                kept.append(record)
        if target is None:
            return {"ok": False, "error": "Asset not found."}
        if delete_file:
            try:
                path = Path(target["path"]).resolve()
                root = paths.workspace_root().resolve()
                if root in path.parents and path.is_file():
                    path.unlink()
            except Exception:
                pass
        data["assets"] = kept
        _write(data)
        return {"ok": True, "asset": target}


# ── evidence ───────────────────────────────────────────────────────────────
def add_evidence(claim: str, *, source_id: str = "", url: str = "",
                 excerpt: str = "", task_id: str = "", method: str = "browser",
                 confidence: str = "medium", asset_id: str = "",
                 question: str = "") -> dict:
    if not str(claim or "").strip():
        raise ValueError("Evidence needs a claim to support.")
    with _LOCK:
        data = _read()
        record = {
            "evidence_id": _new_id("evd"),
            "claim": claim[:2000],
            "source_id": source_id,
            "url": url,
            "excerpt": excerpt[:4000],
            "task_id": task_id,
            "question": question,
            "method": method,
            "confidence": confidence,
            "asset_id": asset_id,
            "retrieved_at": _now(),
        }
        data["evidence"].append(record)
        data["evidence"] = data["evidence"][-MAX_RECORDS:]
        for source in data["sources"]:
            if source.get("source_id") == source_id:
                source.setdefault("evidence", []).append(record["evidence_id"])
        _write(data)
        return dict(record)


def list_evidence(task_id: str = "", limit: int = 500) -> list[dict]:
    with _LOCK:
        data = _read()
    records = [r for r in data["evidence"]
               if not task_id or r.get("task_id") == task_id]
    return records[-max(1, limit):]


def coverage(task_id: str = "") -> dict:
    """What the task actually collected — no estimates, just stored records."""
    sources = list_sources(task_id)
    assets = list_assets(task_id)
    evidence = list_evidence(task_id)
    return {
        "sources": len(sources),
        "inspected": sum(1 for s in sources if s.get("inspected")),
        "failed": sum(1 for s in sources if s.get("verification") == "failed"),
        "assets": len(assets),
        "approved_assets": sum(1 for a in assets if a.get("approved")),
        "unknown_licence": sum(1 for a in assets
                               if a.get("license_status") == "unknown"),
        "evidence": len(evidence),
        "questions": sorted({s.get("question") for s in sources
                             if s.get("question")}),
    }


def clear_task(task_id: str) -> int:
    """Drop a task's records without touching other tasks' work."""
    with _LOCK:
        data = _read()
        before = sum(len(data[k]) for k in ("sources", "assets", "evidence"))
        for key in ("sources", "assets", "evidence"):
            data[key] = [r for r in data[key] if r.get("task_id") != task_id]
        after = sum(len(data[k]) for k in ("sources", "assets", "evidence"))
        _write(data)
        return before - after


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


__all__ = ["LICENSE_STATUSES", "add_source", "update_source", "mark_inspected",
           "record_failure", "list_sources", "get_source", "remove_source",
           "add_asset", "update_asset", "approve_asset", "list_assets",
           "get_asset", "find_asset_by_hash", "link_usage", "remove_asset",
           "add_evidence", "list_evidence", "coverage", "clear_task"]
