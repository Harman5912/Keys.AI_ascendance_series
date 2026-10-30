"""Software worker — delegates to Crown Code, then checks what exists.

Keys.AI already has a real coding agent (``actions.crown_code``) with a
requirements gate, recipe builds, an agent loop and its own verification. This
worker does not reimplement any of that: it submits the task to Crown Code's
background job manager, waits with a bound, then verifies the workspace.

A build is only reported as successful when:

* Crown Code's own job finished with status ``done``; and
* at least one real file exists in the project workspace.

The file list becomes the task's artifacts; the artifact validator then reopens
the ones it understands. Nothing is copied out of the workspace, and a
``node_modules``/``.git`` tree is skipped rather than registered.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from universal_agent import security
from universal_agent.workers import Context, title_for

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
              "dist", "build", ".next", ".cache", ".pytest_cache"}
_MAX_ARTIFACTS = 80
_MAX_FILE_BYTES = 20 * 1024 * 1024


def _project_dir(ctx: Context) -> Path:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-",
                  title_for(str(ctx.task.get("request") or "")))[:40].strip("-")
    name = slug or "project"
    project = security.resolve_within(ctx.workspace, ctx.workspace / name)
    project.mkdir(parents=True, exist_ok=True)
    return project


def _requirements_text(task: dict) -> str:
    answers = task.get("answers") or {}
    if not answers:
        return ""
    return "\n".join(f"{k}: {v}" for k, v in answers.items())


def _research_excerpt(ctx: Context) -> str:
    """Carry the previous research step's report into the build brief."""
    plan = ctx.task.get("plan") or {}
    steps = plan.get("steps") if isinstance(plan, dict) else plan
    for step in steps or []:
        if step.get("worker") != "research" or step.get("status") != "done":
            continue
        for artifact in step.get("artifacts") or []:
            path = Path(str(artifact.get("path") or ""))
            if path.is_file() and path.suffix.lower() in (".md", ".txt"):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                return text[:6000]
    return ""


def _scan(project: Path) -> list[Path]:
    found: list[Path] = []
    for path in sorted(project.rglob("*")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
            if path.stat().st_size == 0:
                continue
        except Exception:
            continue
        found.append(path)
        if len(found) >= _MAX_ARTIFACTS:
            break
    return found


def _crown_build(ctx: Context, project: Path, brief: str) -> dict:
    """Submit to Crown Code's real job manager and wait for the outcome."""
    try:
        from actions.crown_code import crown_code
        from core import crown_jobs
    except Exception as exc:
        return {"ok": False, "workspace": str(project), "summary": "",
                "error": f"Crown Code is unavailable: {exc}"}

    manager = crown_jobs._manager()
    before = {job.id for job in manager.all()}
    params = {
        "description": brief,
        "action": "build",
        "workspace": str(project),
        "project_name": project.name,
        "requirements": _requirements_text(ctx.task),
        "confirmed": True,
        "wait": True,
        "timeout": int(ctx.params.get("timeout") or 900),
    }
    try:
        text = crown_code(params)
    except Exception as exc:
        return {"ok": False, "workspace": str(project), "summary": str(exc),
                "error": f"Crown Code raised: {exc}"}

    deadline = time.time() + float(params["timeout"]) + 60
    job = None
    while time.time() < deadline:
        if ctx.check_cancel():
            try:
                manager.cancel(getattr(job, "id", ""))
            except Exception:
                pass
            return {"ok": False, "workspace": str(project), "summary": "",
                    "error": "cancelled"}
        candidates = [j for j in manager.all()
                      if j.id not in before
                      and str(getattr(j, "workspace", "")) == str(project)]
        if candidates:
            job = candidates[-1]
            if not job.active:
                break
        elif time.time() + 30 > deadline:
            break
        time.sleep(1.0)

    if job is None:
        # Crown Code refused before starting a job (missing requirements, no
        # usable local model, …). Relay its own explanation — never "done".
        return {"ok": False, "workspace": str(project), "summary": str(text),
                "error": str(text).strip()[:600] or
                         "Crown Code did not start a build job."}

    ok = str(job.status) == "done"
    detail = job.describe() if hasattr(job, "describe") else str(getattr(job, "error", ""))
    result = dict(getattr(job, "result", {}) or {})
    return {
        "ok": ok,
        "workspace": str(project),
        "summary": result.get("summary") or detail,
        "error": "" if ok else (job.error or detail or "Crown Code build failed."),
        "notes": result.get("notes") or [],
        "job_id": job.id,
        "status": job.status,
    }


def run(ctx: Context) -> dict:
    if ctx.check_cancel():
        return {"ok": False, "summary": "Build cancelled before it started.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": "cancelled", "notes": []}
    project = _project_dir(ctx)
    brief = str(ctx.task.get("request") or "").strip()
    research = _research_excerpt(ctx)
    if research and ctx.params.get("reuse_research"):
        brief += ("\n\nRESEARCH GATHERED EARLIER IN THIS TASK (use it, do not "
                  "re-research):\n" + research)
    requirements = _requirements_text(ctx.task)
    if requirements:
        brief += "\n\nCONFIRMED REQUIREMENTS:\n" + requirements

    ctx.log(f"Software: delegating to Crown Code in {project.name}")
    builder = ctx.build_project
    if builder is not None:
        try:
            result = builder({"workspace": str(project), "brief": brief,
                              "task": ctx.task, "log": ctx.log})
        except Exception as exc:
            return {"ok": False, "summary": "The project builder raised.",
                    "artifacts": [], "evidence": [], "warnings": [],
                    "error": str(exc), "notes": []}
        result = dict(result or {})
    else:
        result = _crown_build(ctx, project, brief)

    workspace = Path(str(result.get("workspace") or project))
    try:
        workspace = security.resolve_within(ctx.workspace, workspace)
    except security.SecurityError as exc:
        return {"ok": False, "summary": "The builder wrote outside the workspace.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": str(exc), "notes": []}

    files = _scan(workspace)
    if not result.get("ok"):
        return {
            "ok": False,
            "summary": result.get("summary") or "The build did not complete.",
            "artifacts": [],
            "evidence": [],
            "warnings": [f"{len(files)} file(s) exist in the workspace"] if files else [],
            "error": result.get("error") or "The build failed without a reason.",
            "notes": result.get("notes") or [],
        }

    if not files:
        return {
            "ok": False,
            "summary": "The builder reported success but wrote no files.",
            "artifacts": [], "evidence": [], "warnings": [],
            "error": ("No file exists in the project workspace, so the build "
                      "is not accepted as complete."),
            "notes": [],
        }

    artifacts = []
    for path in files:
        try:
            path = security.resolve_within(ctx.workspace, path)
        except security.SecurityError:
            continue
        artifacts.append(ctx.artifact(path, path.suffix.lstrip(".") or "file",
                                      f"{path.stat().st_size} bytes"))

    ctx.log(f"Software: {len(artifacts)} file(s) produced")
    return {
        "ok": True,
        "summary": (result.get("summary")
                    or f"Built {workspace.name} — {len(artifacts)} file(s)."),
        "artifacts": artifacts,
        "evidence": [],
        "warnings": result.get("warnings") or [],
        "error": "",
        "notes": (result.get("notes") or [])[:10],
    }


__all__ = ["run"]
