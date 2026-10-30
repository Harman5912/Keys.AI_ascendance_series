"""
core/crown_jobs.py — background build jobs with live, queryable progress.

A build must not make Keys.AI deaf. A coding run used to block the conversation
until it finished, so the assistant could not answer "how is it going?" while
it was working.

Every build now gets its own thread and a small record that anyone can read:

    job = start_site(brief, kind="portfolio", workspace=..., on_event=...)
    status_text(job.id)      # "62% · writing index.html · 1m12s · ~45s left"
    cancel(job.id)           # sets the cancel flag; workers poll job.cancelled

The record is the single source of truth for the Creation Workspace and for
chat answers, so progress never depends on the model's own narration.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

_MAX_LOGS = 300
_KEEP_DONE_SECONDS = 86400      # finished jobs stay queryable for 24 hours
_HISTORY_FILE = Path.home() / '.freebuff' / 'build_history.json'


class BuildJob:
    """One build: phases, percent, log tail, result, cancellation."""

    def __init__(self, kind: str, brief: str, workspace: str = "",
                 model: str = "", title: str = ""):
        self.id = uuid.uuid4().hex[:10]
        self.kind = kind
        self.brief = brief
        self.workspace = workspace
        self.model = model
        self.title = title or _short_title(brief)
        self.status = "queued"          # queued|running|done|failed|cancelled
        self.phase = "queued"
        self.phase_detail = ""
        self.progress = 0.0
        self.started = time.time()
        self.ended: float | None = None
        self.logs: deque[str] = deque(maxlen=_MAX_LOGS)
        self.result: dict = {}
        self.error = ""
        self.cancel_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.files: list[str] = []
        self._lock = threading.Lock()

    # -- state -------------------------------------------------------------
    def update(self, *, phase: str | None = None, progress: float | None = None,
               detail: str | None = None, log: str | None = None) -> None:
        with self._lock:
            if phase is not None and phase != self.phase:
                self.phase = phase
                if self.status in ("queued",):
                    self.status = "running"
            if detail is not None:
                self.phase_detail = detail
            if progress is not None:
                self.progress = max(self.progress, min(0.99, float(progress)))
            if log:
                stamp = datetime.now().strftime("%H:%M:%S")
                self.logs.append(f"{stamp} {log}")

    def finish(self, ok: bool, result: dict | None = None,
               error: str = "") -> None:
        with self._lock:
            self.result = result or {}
            self.error = error
            self.status = "done" if ok else ("cancelled" if self.cancel_event.is_set() else "failed")
            self.phase = self.status
            self.phase_detail = error or ("finished" if ok else "failed")
            if ok:
                self.progress = 1.0
            self.ended = time.time()

    # -- views -------------------------------------------------------------
    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    @property
    def elapsed(self) -> float:
        return (self.ended or time.time()) - self.started

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running")

    @property
    def eta(self) -> float | None:
        """Rough finish estimate, or None when it would be a guess.

        Early in a run (or at a phase boundary) the remaining time is unknown;
        a confidently wrong "43m left" is worse than no number at all.
        """
        if not self.active or self.progress <= 0.12 or self.elapsed < 45:
            return None
        total = self.elapsed / self.progress
        remaining = max(0.0, total - self.elapsed)
        return remaining if remaining > 5 else None

    def status_line(self) -> str:
        if self.status == "queued":
            return f"{self.title}: queued"
        if self.active:
            pct = int(round(self.progress * 100))
            tail = f" · ~{_dur(self.eta)} left" if self.eta else ""
            detail = f" · {self.phase_detail}" if self.phase_detail else ""
            return (f"{self.title}: {pct}% · {self.phase}{detail} · "
                    f"{_dur(self.elapsed)} elapsed{tail}")
        if self.status == "done":
            files = self.result.get("bytes") or 0
            return (f"{self.title}: done in {_dur(self.elapsed)}"
                    + (f" ({files} bytes)" if files else ""))
        if self.status == "cancelled":
            return f"{self.title}: cancelled after {_dur(self.elapsed)}"
        reason = self.error or self.result.get("error") or "see the log"
        return f"{self.title}: failed after {_dur(self.elapsed)} — {reason}"

    def describe(self, log_lines: int = 6) -> str:
        """Multi-line answer for chat: state, plan, latest activity."""
        lines = [self.status_line()]
        plan = (self.result or {}).get("plan") or {}
        if plan.get("sections"):
            lines.append("Plan: " + ", ".join(s.get("heading", "") for s in plan["sections"] if s.get("heading")))
        if self.files:
            lines.append("Files: " + ", ".join(self.files[-4:]))
        if self.logs and log_lines:
            lines.append("Recent:")
            lines.extend(f"  {row}" for row in list(self.logs)[-log_lines:])
        if self.status == "done" and self.result.get("path"):
            lines.append(f"Output: {self.result['path']}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "brief": self.brief,
            "workspace": self.workspace, "model": self.model, "status": self.status,
            "phase": self.phase, "detail": self.phase_detail,
            "progress": round(self.progress, 3), "elapsed": round(self.elapsed, 1),
            "eta": round(self.eta, 1) if self.eta else None,
            "files": self.files[-8:], "error": self.error,
            "result": {k: v for k, v in (self.result or {}).items()
                       if k in ("ok", "path", "bytes", "seconds", "used_fallback", "notes", "model", "plan")},
            "logs": list(self.logs)[-20:],
        }


def _produced_anything(result: dict | None) -> bool:
    """Did this run leave evidence of work behind?

    Only results that declare their tool usage are judged. Builder results
    report a path/bytes instead and are not second-guessed here.
    """
    if not isinstance(result, dict):
        return False
    if "writes" not in result and "commands" not in result:
        return True
    return bool(result.get("writes") or result.get("commands"))


# ── Registry ──────────────────────────────────────────────────────────────

class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, BuildJob] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()

    # -- lookup ------------------------------------------------------------
    def get(self, job_id: str = "") -> BuildJob | None:
        with self._lock:
            if job_id:
                return self._jobs.get(job_id)
            for jid in reversed(self._order):
                job = self._jobs.get(jid)
                if job and job.active:
                    return job
            if self._order:
                return self._jobs.get(self._order[-1])
            return None

    def active(self) -> list[BuildJob]:
        with self._lock:
            return [j for j in self._jobs.values() if j.active]

    def all(self) -> list[BuildJob]:
        with self._lock:
            self._reap()
            return [self._jobs[j] for j in self._order if j in self._jobs]

    def status_text(self, job_id: str = "", verbose: bool = False) -> str:
        job = self.get(job_id)
        if job is None:
            return "Nothing is building right now."
        if verbose:
            return job.describe()
        running = [j for j in self.active() if j.id != job.id]
        text = job.status_line()
        if running:
            text += f"\nAlso running: {len(running)} other build(s)."
        if job.status == "failed" and job.result.get("notes"):
            text += "\nNotes: " + "; ".join(job.result["notes"][:3])
        return text

    # -- lifecycle ---------------------------------------------------------
    def start(self, name: str, target, on_event=None, kind: str = "code",
              brief: str = "", workspace: str = "", model: str = "") -> BuildJob:
        """Run ``target(job)`` on a worker thread and register the job."""
        job = BuildJob(kind=kind, brief=brief or name, workspace=workspace, model=model,
                       title=name)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._reap()

        def emit(event: dict) -> None:
            if not on_event:
                return
            try:
                on_event(event)
            except Exception:
                pass

        def runner() -> None:
            job.update(phase="starting", progress=0.01)
            emit({"type": "started", "job": job})
            try:
                result = target(job)
                ok = bool((result or {}).get("ok")) if isinstance(result, dict) else False
                summary = str((result or {}).get("summary") or "").strip()
                if ok and not _produced_anything(result):
                    # A target that reports success but declares no writes and no
                    # commands changed nothing. That is a failure: reporting it as
                    # done is how a build with only brief.json on disk was once
                    # presented as a finished dashboard.
                    ok = False
                    summary = ("Crown Code stopped without writing any file: no code "
                               "was produced. " + summary).strip()
                    result = {**result, "ok": False, "error": summary}
                job.finish(ok, result if isinstance(result, dict) else {"ok": ok},
                           error="" if ok else summary)
                emit({"type": "done" if ok else "failed", "job": job, "result": result})
            except Exception as e:                      # never kill the thread silently
                job.finish(False, error=f"{type(e).__name__}: {e}")
                emit({"type": "failed", "job": job, "error": str(e)})

        job.thread = threading.Thread(target=runner, name=f"crown-job-{job.id}", daemon=True)
        job.thread.start()
        return job

    def cancel(self, job_id: str = "") -> str:
        job = self.get(job_id)
        if job is None:
            return "Nothing is building right now."
        if not job.active:
            return f"{job.title} already {job.status}."
        job.cancel_event.set()
        job.update(log="cancel requested by user")
        return f"Stopping {job.title} — it will stop after the current step."

    def _reap(self) -> None:
        cutoff = time.time() - _KEEP_DONE_SECONDS
        keep: list[str] = []
        for jid in self._order:
            job = self._jobs.get(jid)
            if job is None:
                continue
            if not job.active and (job.ended or 0) < cutoff:
                # Persist completed jobs to history before removing from memory
                if job.status in ("done", "failed"):
                    _save_job_to_history(job)
                self._jobs.pop(jid, None)
                continue
            keep.append(jid)
        self._order = keep


# ── Module-level singleton used by the action layer / brain ───────────────

MANAGER = JobManager()


def _manager() -> JobManager:
    """Return the current job manager.

    Tests replace this with a fresh JobManager via ``mock.patch.object(crown_jobs, "_manager", return_value=JobManager())`` so the production singleton is never
    mutated and no leftover jobs leak between tests. Production code keeps using
    the real singleton through this helper.
    """
    return MANAGER
start = MANAGER.start
get = MANAGER.get
status_text = MANAGER.status_text
cancel = MANAGER.cancel
active = MANAGER.active
all = MANAGER.all          # every job this session, newest last


def get_build_history(limit: int | None = None) -> list[dict]:
    """Return all persisted build history entries, newest first.

    Returns a list of job dicts suitable for display/browsing. Each entry
    contains id, kind, title, brief, workspace, status, elapsed, files,
    and result summary — enough to let a user pick a past build and open its
    workspace folder.
    """
    try:
        history = _load_history()
        jobs = list(history.get("jobs", []))
        if limit is not None and limit > 0:
            jobs = jobs[:limit]
        return jobs
    except Exception:
        return []


def _save_job_to_history(job: BuildJob) -> None:
    """Persist a completed job to disk so it survives session restarts."""
    try:
        history = _load_history()
        entry = job.to_dict()
        entry["saved_at"] = datetime.now(timezone.utc).isoformat()
        # Enrich the entry with derived fields the UI will want to display.
        entry["saved_at_human"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        entry["status_text"] = job.status_line()
        history["jobs"].insert(0, entry)
        # Limit total persisted entries so the file never grows without bound.
        history["jobs"] = history["jobs"][:200]
        history["updated_at"] = datetime.now(timezone.utc).isoformat()
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception:
        # Never let history I/O crash a build.
        pass


def _load_history() -> dict:
    """Load the persisted history file, or return a fresh empty structure."""
    try:
        if _HISTORY_FILE.exists():
            data = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("jobs"), list):
                return data
    except Exception:
        pass
    return {"jobs": [], "updated_at": ""}


def _dur(seconds: float | None) -> str:
    if not seconds:
        return "0s"
    # A recipe build finishes in under a second; truncating that to "0s" reads
    # as if nothing ran. Keep one decimal until the number is comfortably big.
    if seconds < 10:
        return f"{seconds:.1f}s"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def clear_build_history() -> int:
    """Clear all build history. Returns count of removed entries."""
    try:
        history = _load_history()
        count = len(history["jobs"])
        history["jobs"] = []
        history["updated_at"] = datetime.now(timezone.utc).isoformat()
        _HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")
        return count
    except Exception:
        return 0


def _short_title(brief: str) -> str:
    text = " ".join((brief or "build").split())
    return text[:70] + ("…" if len(text) > 70 else "")
