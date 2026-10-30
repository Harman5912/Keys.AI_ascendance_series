"""Project Agent service — orchestrates intake → plan → work → validate → report.

This is the only place that decides a task is finished. A worker's success flag
is an input, not a verdict: artifacts are re-opened by
``universal_agent.validation`` and the task only becomes COMPLETED when every
artifact verifies.

Cooperative limits (documented, not hidden): a step runs on a daemon thread and
is abandoned when its deadline passes; Python cannot force-kill a thread, so
workers poll ``should_cancel`` and subprocess-based tools carry their own
timeouts.

State is persisted after every milestone, so a task interrupted by an
application restart can be resumed with :meth:`resume`.
"""

from __future__ import annotations

import copy
import threading
import time
import uuid
from pathlib import Path

from universal_agent import (intake, models, planner, security, validation)
from universal_agent import workers as worker_pkg
from universal_agent.models import Status
from universal_agent.workers import Context

STEP_TIMEOUT = {"research": 420, "software": 1500, "documents": 300,
                "data": 300, "images": 900, "browser": 180}
APPROVAL_TIMEOUT = 300.0
MAX_REPAIRS = 1


def _default_browser(url: str, dest: str = "") -> dict:
    """Screenshot through the app's own browser (lazy import, optional).

    Importing QtWebEngine without a running application aborts the process, so
    a headless run (tests, cron) must decline *before* the import — an optional
    feature reporting itself unavailable, never a crash.
    """
    try:
        from PyQt6.QtWidgets import QApplication
    except Exception:
        return {"ok": False, "error": "Qt is not available in this run."}
    if QApplication.instance() is None:
        return {"ok": False,
                "error": "No running app window, so no screenshot can be taken."}
    from core.research_browser.tools import capture_reference
    return capture_reference(url, dest)


class TaskFailure(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


class ProjectAgentService:
    def __init__(self, *, executors: dict | None = None, complete=None,
                 search=None, fetch=None, build_project=None,
                 image_backend=None, browser=None, use_model_planner: bool = True,
                 workspace_root=None, approval_workers=(),
                 step_timeout_overrides=None):
        self._lock = threading.RLock()
        self._tasks: dict[str, dict] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancels: dict[str, threading.Event] = {}
        self._approvals: dict[str, threading.Event] = {}
        self._executors = dict(executors or {})
        self._complete = complete
        self._search = search
        self._fetch = fetch
        self._build_project = build_project
        self._image_backend = image_backend
        # Design-reference capture: a callable (url, dest_dir) -> screenshot.
        # Defaults to the in-app browser; None disables it for headless runs.
        self._browser = browser or _default_browser
        self._use_model_planner = use_model_planner
        self._root = Path(workspace_root) if workspace_root else intake.workspace_root()
        # Workers whose steps always need an explicit decision. Empty by
        # default (new files inside a task workspace are not destructive); a
        # caller can require approval for e.g. software builds.
        self._approval_workers = set(approval_workers or ())
        # Per-worker execution budgets. A caller may shorten a build deadline
        # without editing the plan or the production defaults.
        self._step_timeouts = dict(step_timeout_overrides or {})
        self._listeners: list = []

    # ── listeners (UI / voice) ────────────────────────────────────────────
    def add_listener(self, fn) -> None:
        self._listeners.append(fn)

    def _emit(self, task: dict, event: dict) -> None:
        for fn in list(self._listeners):
            try:
                fn(copy.deepcopy(task), dict(event))
            except Exception:
                pass

    # ── task lookup ───────────────────────────────────────────────────────
    def _get(self, task_id: str) -> dict:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                stored = models.load(task_id)
                if stored is None:
                    raise KeyError(f"Unknown task: {task_id}")
                stored.setdefault("logs", [])
                self._tasks[task_id] = stored
                task = stored
            return task

    def get_task(self, task_id: str) -> dict | None:
        try:
            with self._lock:
                task = copy.deepcopy(self._get(task_id))
        except KeyError:
            return None
        task["needs_resume"] = (str(task.get("status")) in {
            Status.RUNNING.value, Status.PLANNING.value,
            Status.VALIDATING.value, Status.REPAIRING.value,
            Status.WAITING_FOR_APPROVAL.value}
            and task_id not in self._threads)
        task["active"] = task_id in self._threads and \
            self._threads[task_id].is_alive()
        return task

    def list_tasks(self, limit: int = 30) -> list[dict]:
        out = []
        for task in models.list_tasks(limit):
            task_id = task.get("id", "")
            out.append({
                "id": task_id,
                "request": task.get("request", ""),
                "status": task.get("status", ""),
                "intent": task.get("intent", ""),
                "created_at": task.get("created_at", ""),
                "updated_at": task.get("updated_at", ""),
                "workspace": task.get("workspace", ""),
                "artifacts": len(task.get("artifacts") or []),
                "needs_resume": models.recoverable(task),
            })
        return out

    def list_artifacts(self, task_id: str = "") -> list[dict]:
        out = []
        if task_id:
            task = self.get_task(task_id)
            return list((task or {}).get("artifacts") or [])
        for summary in models.list_tasks(200):
            for item in summary.get("artifacts") or []:
                out.append({**item, "task_id": summary.get("id")})
        return out

    def report_text(self, task_id: str) -> str:
        task = self.get_task(task_id)
        if not task:
            return "That task no longer exists."
        lines = [f"Task {task['id']} — {task['status']}",
                 f"Request: {task['request'][:200]}",
                 f"Workspace: {task.get('workspace', '')}", ""]
        if task.get("error"):
            lines.append(f"Error: {task['error']}")
        plan = task.get("plan") or {}
        for step in plan.get("steps") or []:
            mark = {"done": "✓", "failed": "✕", "running": "→"}.get(
                step.get("status"), "○")
            lines.append(f"{mark} {step.get('title')} [{step.get('worker')}]")
            if step.get("error"):
                lines.append(f"   {step['error']}")
        result = task.get("result") or {}
        if result.get("summary"):
            lines += ["", f"Outcome: {result['summary']}"]
        validated = ((task.get("validation") or {}).get("detail")
                     or result.get("validation") or "")
        if validated:
            lines.append(f"Validation: {validated}")
        if task.get("artifacts"):
            lines += ["", "Artifacts:"]
            for item in task["artifacts"]:
                state = "verified" if item.get("validated") else "not verified"
                detail = item.get("validation_detail") or item.get("detail", "")
                lines.append(f"• {item.get('path')} — {state}"
                             + (f" ({detail})" if detail else ""))
        if task.get("warnings"):
            lines += ["", "Warnings:"] + [f"! {w}" for w in task["warnings"]]
        return "\n".join(lines)

    # ── creation and clarification ────────────────────────────────────────
    def create(self, request: str, workspace: str = "", answers: dict | None = None,
               intent: str = "", auto_start: bool = True) -> dict:
        request = str(request or "").strip()
        if not request:
            raise ValueError("Describe what you want the agent to do.")
        intent = intent or intake.classify(request)
        task = models.new_task(request, intent)
        task["logs"] = []

        analysis = intake.analyse(request, intent, answers)
        task["questions"] = analysis["questions"]
        task["answers"] = analysis["answers"]
        task["assumptions"] = analysis["assumptions"]
        task["brief"] = analysis["brief"]

        if workspace:
            ws = Path(workspace).expanduser()
            try:
                ws.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                raise ValueError(f"Workspace could not be created: {exc}")
            task["workspace"] = str(ws.resolve())
        else:
            task["workspace"] = str(
                intake.create_workspace(request, task["id"], self._root))

        models.add_event(task, "task_created",
                         f"{intent} task created in {Path(task['workspace']).name}")
        models.audit(security.audit_line(
            "task.create", f"{task['id']} {intent}", task["workspace"]))

        pending = analysis["pending_required"]
        if pending:
            models.set_status(task, Status.WAITING_FOR_USER, "missing requirements")
            models.add_event(task, "requirements_needed",
                             f"{len(pending)} question(s) awaiting an answer")
        else:
            models.set_status(task, Status.READY)
            if analysis["assumptions"]:
                task.setdefault("warnings", []).extend(analysis["assumptions"])

        with self._lock:
            self._tasks[task["id"]] = task
        models.save(task)
        self._emit(task, {"type": "created", "task_id": task["id"],
                          "status": task["status"]})
        if auto_start and not pending:
            self._start(task["id"])
        return self.get_task(task["id"]) or task

    def answer(self, task_id: str, answers: dict) -> dict:
        task = self._get(task_id)
        if str(task.get("status")) != Status.WAITING_FOR_USER.value:
            raise ValueError("This task is not waiting for an answer.")
        incoming = {str(k): str(v).strip() for k, v in (answers or {}).items()
                    if str(v or "").strip()}
        if not incoming:
            raise ValueError("Enter at least one answer before submitting.")
        merged = {**(task.get("answers") or {}), **incoming}
        analysis = intake.analyse(task["request"], task.get("intent", ""), merged)
        task["questions"] = analysis["questions"]
        task["answers"] = analysis["answers"]
        task["assumptions"] = analysis["assumptions"]
        task["brief"] = analysis["brief"]
        pending = analysis["pending_required"]
        models.add_event(task, "answers_received",
                         f"{len(incoming)} answer(s) recorded")
        if pending:
            models.save(task)
            self._emit(task, {"type": "requirements_needed",
                              "task_id": task_id})
            return self.get_task(task_id) or task
        models.set_status(task, Status.READY, "requirements complete")
        if analysis["assumptions"]:
            task.setdefault("warnings", []).extend(
                a for a in analysis["assumptions"] if a not in task["warnings"])
        models.save(task)
        self._start(task_id)
        return self.get_task(task_id) or task

    def start(self, task_id: str) -> dict:
        task = self._get(task_id)
        if str(task.get("status")) in (Status.WAITING_FOR_USER.value,):
            raise ValueError("Answer the pending questions first.")
        if task_id in self._threads and self._threads[task_id].is_alive():
            return self.get_task(task_id) or task
        if str(task.get("status")) in (Status.COMPLETED.value,
                                       Status.CANCELLED.value):
            raise ValueError(f"Task is already {task['status'].lower()}.")
        if str(task.get("status")) == Status.FAILED.value:
            models.set_status(task, Status.READY, "retry requested")
            models.save(task)
        self._start(task_id)
        return self.get_task(task_id) or task

    def resume(self, task_id: str) -> dict:
        task = self._get(task_id)
        status = str(task.get("status"))
        if status == Status.COMPLETED.value:
            return self.get_task(task_id) or task
        if status == Status.CANCELLED.value:
            raise ValueError("A cancelled task is not resumed; start a new one.")
        if task_id in self._threads and self._threads[task_id].is_alive():
            return self.get_task(task_id) or task
        for step in (task.get("plan") or {}).get("steps") or []:
            if step.get("status") in ("running", "failed"):
                step["status"] = "pending"
                step.pop("approved", None)
        if status == Status.WAITING_FOR_APPROVAL.value:
            models.set_status(task, Status.RUNNING, "resume after restart")
        elif status in (Status.RUNNING.value, Status.PLANNING.value,
                        Status.VALIDATING.value, Status.REPAIRING.value):
            models.set_status(task, Status.READY, "resume after interruption")
        elif status == Status.FAILED.value:
            models.set_status(task, Status.READY, "resume requested")
        models.add_event(task, "resumed", "task resumed from saved state")
        models.save(task)
        self._start(task_id)
        return self.get_task(task_id) or task

    # ── decisions ─────────────────────────────────────────────────────────
    def approve(self, task_id: str, approved: bool, reason: str = "") -> dict:
        task = self._get(task_id)
        if str(task.get("status")) != Status.WAITING_FOR_APPROVAL.value:
            raise ValueError("This task is not waiting for an approval.")
        approval = task.get("approval") or {}
        if not approval:
            raise ValueError("There is no pending approval request.")
        approval["approved"] = bool(approved)
        approval["decided_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        approval["reason"] = str(reason or "")[:300]
        approval["status"] = "approved" if approved else "rejected"
        task["approval"] = approval
        models.add_event(task, "approval_decision",
                         f"{approval['status']}: {approval.get('title', '')}")
        models.audit(security.audit_line(
            "task.approval", f"{task_id} {approval['status']}",
            approval.get("title", "")))
        models.save(task)
        event = self._approvals.get(str(approval.get("id")))
        if event is not None:
            event.set()
        self._emit(task, {"type": "approval_decided", "task_id": task_id,
                          "approved": bool(approved)})
        return self.get_task(task_id) or task

    def cancel(self, task_id: str) -> dict:
        task = self._get(task_id)
        status = str(task.get("status"))
        if status in (Status.COMPLETED.value, Status.CANCELLED.value):
            return self.get_task(task_id) or task
        event = self._cancels.setdefault(task_id, threading.Event())
        event.set()
        approval_event = self._approvals.get(
            str((task.get("approval") or {}).get("id")))
        if approval_event is not None:
            approval_event.set()
        if status != Status.FAILED.value:
            try:
                models.set_status(task, Status.CANCELLED, "cancelled by user")
            except models.StateError:
                task["status"] = Status.CANCELLED.value
        task["error"] = "Cancelled by user."
        models.add_event(task, "cancelled", "task cancelled by the user")
        models.audit(security.audit_line("task.cancel", task_id, "user"))
        models.save(task)
        self._emit(task, {"type": "cancelled", "task_id": task_id})
        return self.get_task(task_id) or task

    def cancel_all(self) -> None:
        """Signal every running task (called on application exit)."""
        for task_id in list(self._threads):
            try:
                self.cancel(task_id)
            except Exception:
                pass

    # ── execution ─────────────────────────────────────────────────────────
    def _start(self, task_id: str) -> None:
        with self._lock:
            thread = self._threads.get(task_id)
            if thread is not None and thread.is_alive():
                return
            self._cancels[task_id] = threading.Event()
            thread = threading.Thread(target=self._run, args=(task_id,),
                                      name=f"ua-task-{task_id}", daemon=True)
            self._threads[task_id] = thread
        thread.start()

    def _is_cancelled(self, task_id: str) -> bool:
        event = self._cancels.get(task_id)
        return bool(event and event.is_set())

    def _transition(self, task: dict, status: Status, reason: str = "") -> None:
        models.set_status(task, status, reason)
        models.save(task)
        self._emit(task, {"type": "status", "task_id": task["id"],
                          "status": status.value, "reason": reason})

    def _log(self, task: dict, step: dict | None, text: str,
             event_type: str = "worker_log") -> None:
        clean = security.redact_secrets(str(text))[:800]
        entry = {"ts": time.strftime("%H:%M:%S"), "text": clean,
                 "step": (step or {}).get("id", "")}
        task.setdefault("logs", []).append(entry)
        task["logs"] = task["logs"][-300:]
        if event_type:
            models.add_event(task, event_type, clean,
                             step=(step or {}).get("id", ""))
        self._emit(task, {"type": event_type, "task_id": task["id"],
                          "text": clean, "step": (step or {}).get("id", "")})

    def _build_context(self, task: dict, step: dict) -> Context:
        attempt_cancel = threading.Event()
        timeout = float(step.get("params", {}).get("timeout")
                        or self._step_timeouts.get(step.get("worker"), 0)
                        or STEP_TIMEOUT.get(step.get("worker"), 300))

        def should_cancel() -> bool:
            return attempt_cancel.is_set() or self._is_cancelled(task["id"])

        def request_approval(title: str, detail: str) -> bool:
            return self._await_approval(task, step, title, detail)

        ctx = Context(
            task=task,
            workspace=Path(task["workspace"]),
            params=dict(step.get("params") or {}),
            log=lambda m, s=step: self._log(task, s, m),
            should_cancel=should_cancel,
            request_approval=request_approval,
            complete=self._complete or worker_pkg.default_complete,
            search=self._search or worker_pkg.default_search,
            fetch=self._fetch or worker_pkg.default_fetch,
            build_project=self._build_project,
            image_backend=self._image_backend,
            browser=self._browser,
        )
        ctx._attempt_cancel = attempt_cancel       # used by the timeout guard
        ctx._timeout = timeout
        return ctx

    def _run(self, task_id: str) -> None:
        task = self._get(task_id)
        try:
            if str(task.get("status")) == Status.READY.value:
                self._transition(task, Status.PLANNING, "building the plan")

            plan = task.get("plan") or {}
            if not plan.get("steps"):
                input_file = (task.get("answers", {}).get("input_file")
                              or intake.extract_input_file(task["request"]))
                task["error"] = ""
                plan = planner.build_plan(
                    task["request"], task.get("brief") or {},
                    task.get("intent", ""), task.get("answers") or {},
                    input_file=input_file,
                    complete=(None if self._use_model_planner
                              else self._no_model),
                    use_model=self._use_model_planner)
                task["plan"] = plan
                if plan.get("note"):
                    self._log(task, None, f"Planner: {plan['note']}", "")
                models.add_event(
                    task, "plan_created",
                    f"{len(plan.get('steps') or [])} step(s), source: "
                    f"{plan.get('source')}")
                self._transition(task, Status.READY, "plan ready")
                self._emit(task, {"type": "plan", "task_id": task_id,
                                  "plan": copy.deepcopy(plan)})

            self._transition(task, Status.RUNNING)

            for index, step in enumerate(task["plan"]["steps"]):
                if self._is_cancelled(task_id):
                    raise Cancelled()
                if step.get("status") == "done":
                    continue
                task["current_step"] = index
                needs_approval = (step.get("requires_approval")
                                  or step.get("worker") in self._approval_workers)
                if needs_approval and not step.get("approved"):
                    if not self._await_approval(
                            task, step, step.get("title", "Approval required"),
                            "This step is marked as needing explicit approval."):
                        raise TaskFailure("The user did not approve this step.")
                self._run_step(task, step)
                models.save(task)

            self._transition(task, Status.VALIDATING, "verifying artifacts")
            final = validation.validate_all(task.get("artifacts") or [],
                                            task["workspace"])
            task["validation"] = final
            self._log(task, None, f"Validation: {final['detail']}", "")
            if not final["ok"]:
                self._transition(task, Status.REPAIRING, "validation failed")
                raise TaskFailure(
                    "Artifact validation failed: " + final["detail"])

            done = sum(1 for s in task["plan"]["steps"]
                       if s.get("status") == "done")
            task["result"] = {
                "summary": f"{done} step(s) complete; "
                           f"{len(task.get('artifacts') or [])} artifact(s) "
                           "verified.",
                "artifacts": [a.get("path") for a in task.get("artifacts") or []],
                "validation": final["detail"],
                "warnings": task.get("warnings") or [],
            }
            models.add_event(task, "task_completed", task["result"]["summary"])
            models.audit(security.audit_line(
                "task.completed", task_id, task["result"]["summary"]))
            self._transition(task, Status.COMPLETED)
            self._emit(task, {"type": "completed", "task_id": task_id,
                              "result": copy.deepcopy(task['result'])})
        except Cancelled:
            if str(task.get("status")) not in (Status.CANCELLED.value,
                                               Status.COMPLETED.value):
                try:
                    models.set_status(task, Status.CANCELLED, "cancelled")
                except models.StateError:
                    task["status"] = Status.CANCELLED.value
                task["error"] = "Cancelled by user."
                models.add_event(task, "cancelled", "task cancelled")
                models.audit(security.audit_line("task.cancelled", task_id, "user"))
                models.save(task)
        except TaskFailure as exc:
            task["error"] = security.redact_secrets(str(exc))[:1000]
            self._fail(task, str(exc))
        except Exception as exc:
            task["error"] = security.redact_secrets(
                f"{type(exc).__name__}: {exc}")[:1000]
            self._fail(task, task["error"])
        finally:
            models.save(task)
            with self._lock:
                self._threads.pop(task_id, None)
                self._cancels.pop(task_id, None)

    def _no_model(self, _prompt, _system):
        raise RuntimeError("model planner disabled")

    def _fail(self, task: dict, message: str) -> None:
        try:
            if str(task.get("status")) not in (Status.FAILED.value,
                                               Status.CANCELLED.value):
                models.set_status(task, Status.FAILED, "error")
        except models.StateError:
            task["status"] = Status.FAILED.value
        models.add_event(task, "task_failed", message)
        models.audit(security.audit_line("task.failed", task["id"], message))
        self._emit(task, {"type": "failed", "task_id": task["id"],
                          "error": task.get("error") or message})

    def _run_step(self, task: dict, step: dict) -> None:
        if self._is_cancelled(task["id"]):
            raise Cancelled()
        step["status"] = "running"
        step["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        step["attempts"] = int(step.get("attempts") or 0)
        self._log(task, step, f"Starting: {step.get('title')}", "step_started")
        models.save(task)

        repair_notes = ""
        for attempt in range(MAX_REPAIRS + 1):
            step["attempts"] += 1
            ctx = self._build_context(task, step)
            if repair_notes:
                ctx.params["repair"] = repair_notes
            result, timed_out = self._call_worker(step, ctx)
            if self._is_cancelled(task["id"]):
                raise Cancelled()
            if timed_out:
                raise TaskFailure(
                    f"'{step.get('title')}' exceeded its "
                    f"{int(ctx._timeout)}s limit and was stopped.")

            if not result.get("ok"):
                raise TaskFailure(
                    result.get("error") or
                    f"Worker '{step.get('worker')}' reported failure.")

            descriptors = list(result.get("artifacts") or [])
            if not descriptors:
                repair_notes = ("The worker reported success but produced no "
                                "artifact to verify.")
            else:
                registered, outside = self._register(task, descriptors)
                if outside:
                    raise TaskFailure(
                        "An artifact was written outside the task workspace: "
                        + ", ".join(outside))
                # Steps keep their own artifacts: a later step reads them — this
                # is how the research report reaches the build brief.
                step.setdefault("artifacts", [])
                known = {a.get("path") for a in step["artifacts"]}
                step["artifacts"].extend(r for r in registered
                                         if r.get("path") not in known)
                check = validation.validate_all(registered, task["workspace"])
                if check["ok"]:
                    task["evidence"].extend(result.get("evidence") or [])
                    task.setdefault("warnings", []).extend(
                        w for w in (result.get("warnings") or [])
                        if w not in task.get("warnings", []))
                    step["status"] = "done"
                    step["ended_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    step["detail"] = result.get("summary", "")
                    for item in registered:
                        self._log(task, step,
                                  f"Verified artifact: {Path(item['path']).name} "
                                  f"({item['validation_detail']})", "")
                    self._log(task, step,
                              f"Done: {result.get('summary', '')}", "step_done")
                    models.audit(security.audit_line(
                        "step.done", f"{task['id']} {step.get('worker')}",
                        result.get("summary", "")))
                    models.save(task)
                    return
                repair_notes = check["detail"]
                # Invalid artifacts must not linger in the registry, or the
                # final validation would fail on a repaired step's leftovers.
                bad_paths = {r["path"] for r in registered}
                task["artifacts"] = [a for a in task.get("artifacts") or []
                                     if a.get("path") not in bad_paths]
                step["artifacts"] = [a for a in step.get("artifacts") or []
                                     if a.get("path") not in bad_paths]
                self._log(task, step,
                          f"Validation failed: {repair_notes}",
                          "validation_failed")
                models.add_event(task, "validation_failed", repair_notes,
                                 step=step.get("id", ""))
                if attempt < MAX_REPAIRS:
                    self._transition(task, Status.VALIDATING, "artifact validation")
                    self._transition(task, Status.REPAIRING, "repair attempt")
                    self._transition(task, Status.RUNNING, "repair running")
                    continue
                task.setdefault("artifacts", [])
                raise TaskFailure(
                    "The produced artifact could not be verified: " + repair_notes)

            if attempt < MAX_REPAIRS:
                self._transition(task, Status.VALIDATING, "no artifact produced")
                self._transition(task, Status.REPAIRING, "retry requested")
                self._transition(task, Status.RUNNING, "retry running")
                continue
            raise TaskFailure(repair_notes)

    def _call_worker(self, step: dict, ctx: Context) -> tuple[dict, bool]:
        box: dict = {}

        def work():
            try:
                fn = self._executors.get(step.get("worker"))
                box["result"] = (fn(ctx) if fn else
                                 worker_pkg.execute(step["worker"], ctx))
            except Exception as exc:
                box["result"] = {
                    "ok": False, "summary": "Worker raised.",
                    "artifacts": [], "evidence": [], "warnings": [],
                    "error": f"{type(exc).__name__}: {exc}", "notes": [],
                }

        thread = threading.Thread(target=work, name="ua-worker", daemon=True)
        thread.start()
        thread.join(float(ctx._timeout))
        if thread.is_alive():
            # Cooperative cancellation only: Python cannot kill the thread, so
            # signal it and stop waiting. The worker checks this flag itself.
            ctx._attempt_cancel.set()
            return ({"ok": False, "summary": "Timed out.",
                     "artifacts": [], "evidence": [], "warnings": [],
                     "error": f"step timed out after {int(ctx._timeout)}s",
                     "notes": []}, True)
        return box.get("result") or {
            "ok": False, "summary": "Worker returned nothing.",
            "artifacts": [], "evidence": [], "warnings": [],
            "error": "The worker returned no result.", "notes": [],
        }, False

    def _register(self, task: dict, descriptors: list[dict]) -> tuple[list[dict], list[str]]:
        registered: list[dict] = []
        outside: list[str] = []
        existing = {a.get("path") for a in task.get("artifacts") or []}
        for descriptor in descriptors:
            raw = descriptor.get("path") if isinstance(descriptor, dict) else descriptor
            if not raw:
                continue
            try:
                path = security.resolve_within(task["workspace"], raw, must_exist=True)
            except security.SecurityError as exc:
                outside.append(str(raw))
                self._log(task, None, f"Refused artifact path: {exc}", "")
                continue
            if not path.is_file():
                outside.append(str(raw))
                continue
            if str(path) in existing:
                continue
            try:
                digest = security.sha256_file(path)
                size = path.stat().st_size
            except Exception:
                digest, size = "", 0
            record = {
                "id": uuid.uuid4().hex[:10],
                "task_id": task["id"],
                "name": path.name,
                "path": str(path),
                "kind": (descriptor.get("kind") if isinstance(descriptor, dict)
                         else path.suffix.lstrip(".")) or path.suffix.lstrip("."),
                "size": size,
                "sha256": digest,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "detail": (descriptor.get("detail", "") if isinstance(descriptor, dict)
                           else ""),
                "validated": False,
                "validation_detail": "",
            }
            check = validation.validate_artifact(path, task["workspace"])
            record["validated"] = bool(check["ok"])
            record["validation_detail"] = check["detail"]
            registered.append(record)
            existing.add(str(path))
            task.setdefault("artifacts", []).append(record)
            self._emit(task, {"type": "artifact", "task_id": task["id"],
                              "artifact": dict(record)})
        return registered, outside

    def _await_approval(self, task: dict, step: dict, title: str,
                        detail: str) -> bool:
        if self._is_cancelled(task["id"]):
            return False
        approval = {
            "id": uuid.uuid4().hex[:10],
            "task_id": task["id"],
            "step": step.get("id", ""),
            "title": security.redact_secrets(title)[:200],
            "detail": security.redact_secrets(detail)[:1000],
            "status": "pending",
            "requested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        task["approval"] = approval
        models.add_event(task, "approval_required", approval["title"])
        models.audit(security.audit_line("task.approval_requested",
                                         f"{task['id']} {approval['title']}"))
        # The wake-up event is registered BEFORE the request is announced: a
        # decision that arrives from the UI while the request is still being
        # emitted used to find no event to set and the task then waited out the
        # whole approval timeout even though it had already been answered.
        event = threading.Event()
        self._approvals[approval["id"]] = event
        try:
            self._transition(task, Status.WAITING_FOR_APPROVAL, "approval needed")
        except models.StateError:
            task["status"] = Status.WAITING_FOR_APPROVAL.value
            models.save(task)
        self._emit(task, {"type": "approval_required", "task_id": task["id"],
                          "approval": dict(approval)})
        if str((task.get("approval") or {}).get("status")) in ("approved",
                                                                "rejected"):
            event.set()
        deadline = time.time() + APPROVAL_TIMEOUT
        try:
            while time.time() < deadline:
                if event.wait(0.5):
                    break
                if self._is_cancelled(task["id"]):
                    return False
            else:
                approval["status"] = "timed out"
                models.add_event(task, "approval_timeout", approval["title"])
                models.audit(security.audit_line(
                    "task.approval_timeout", f"{task['id']} {approval['title']}"))
                models.save(task)
                return False
        finally:
            self._approvals.pop(approval["id"], None)

        decision = bool((task.get("approval") or {}).get("approved"))
        step["approved"] = decision
        if decision:
            self._transition(task, Status.RUNNING, "approval granted")
        else:
            self._transition(task, Status.RUNNING, "approval answered")
            raise TaskFailure(
                "The user rejected this step: "
                + str((task.get("approval") or {}).get("reason") or "no reason given."))
        return True


__all__ = ["ProjectAgentService", "TaskFailure", "Cancelled", "STEP_TIMEOUT"]
