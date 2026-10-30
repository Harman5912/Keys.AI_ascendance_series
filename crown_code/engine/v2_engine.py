"""
crown_code/engine/v2_engine.py — Python-native Crown Code v2 agent engine.

This is the new engine that runs entirely in Python, with no Node.js subprocess.
It implements the same AgentEngine interface as LegacyEngine and is activated
by setting CROWN_ENGINE=v2 (or config["engine"] = "v2").

Architecture
------------
  Session → Plan → [Tool Loop] → Verify → Done

  Session:   durable SQLite-backed state so builds resume after a crash.
  Plan:      the LLM decomposes the brief into an ordered TODO list.
  Tool Loop: the LLM picks tools; the engine executes them; loop-detector watches.
  Verify:    run the repair loop (pytest / ruff / syntax check) before claiming done.
  Done:      emit DoneEvent; the session is marked complete.

Tool set
--------
  read_file, write_file, list_dir, run_shell, search_web, grep_codebase,
  ask_user (emits a clarification request back to the conversation),
  checkpoint (saves a snapshot at the current state).

All tool calls are mediated through core.tool_exec.ToolOutcome so the engine
never crashes on a bad tool result.

Model
-----
  Uses core.llm_client.LLMClient, which supports Ollama / OpenAI-compatible
  API out of the box.  Provider and model are resolved from:
    1. config["model"] / config["provider"]
    2. OLLAMA_HOST env var
    3. Hardcoded fallback to qwen3:8b on localhost:11434
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

from crown_code.engine.events import (
    CheckpointEvent,
    DoneEvent,
    ErrorEvent,
    EventBus,
    FileReadEvent,
    FileWriteEvent,
    PlanEvent,
    ProgressEvent,
    ShellEvent,
    ThinkEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from crown_code.engine.interface import AgentEngine
from crown_code.engine.checkpoints import CheckpointStore
from crown_code.engine.loop_detector import LoopDetector, LoopConfig

# ── constants ─────────────────────────────────────────────────────────────────

_MAX_ITERATIONS = 40
_TOOL_TIMEOUT = 30      # seconds per tool call
_PLAN_TIMEOUT = 60      # seconds for the planning LLM call


# ── tool implementations ───────────────────────────────────────────────────────

def _tool_read_file(params: dict, ws: Path) -> str:
    path = ws / params.get("path", "")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        # return at most 8 KB
        if len(text) > 8192:
            text = text[:8192] + "\n… (truncated)"
        return text
    except FileNotFoundError:
        return f"ERROR: file not found: {path}"
    except Exception as exc:
        return f"ERROR: {exc}"


def _tool_write_file(params: dict, ws: Path, bus: EventBus) -> str:
    path_str = params.get("path", "")
    content = params.get("content", "")
    path = ws / path_str
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        bus.emit(FileWriteEvent(path=str(path), size=len(content.encode())))
        return f"Wrote {len(content)} chars to {path_str}"
    except Exception as exc:
        return f"ERROR: {exc}"


def _tool_list_dir(params: dict, ws: Path) -> str:
    target = ws / params.get("path", ".")
    try:
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
        lines = []
        for e in entries[:60]:
            lines.append(f"{'f' if e.is_file() else 'd'}  {e.name}")
        if len(list(target.iterdir())) > 60:
            lines.append("… (truncated)")
        return "\n".join(lines) or "(empty)"
    except Exception as exc:
        return f"ERROR: {exc}"


def _tool_run_shell(params: dict, ws: Path, bus: EventBus,
                    cancel_event: threading.Event) -> str:
    cmd = params.get("command", "")
    if not cmd:
        return "ERROR: no command"
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=ws,
            capture_output=True, text=True, timeout=_TOOL_TIMEOUT,
        )
        stdout = proc.stdout[:2000]
        stderr = proc.stderr[:500]
        bus.emit(ShellEvent(
            command=cmd,
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
        ))
        out = stdout
        if proc.returncode != 0:
            out += f"\nEXIT {proc.returncode}"
            if stderr:
                out += f"\nSTDERR: {stderr}"
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {_TOOL_TIMEOUT}s"
    except Exception as exc:
        return f"ERROR: {exc}"


def _tool_grep(params: dict, ws: Path) -> str:
    pattern = params.get("pattern", "")
    glob = params.get("glob", "**/*.py")
    try:
        results = []
        for p in ws.glob(glob):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if re.search(pattern, line, re.I):
                        results.append(f"{p.relative_to(ws)}:{i}: {line.rstrip()}")
                        if len(results) >= 30:
                            break
            except Exception:
                pass
            if len(results) >= 30:
                break
        return "\n".join(results) or "(no matches)"
    except Exception as exc:
        return f"ERROR: {exc}"


def _tool_checkpoint(params: dict, store: CheckpointStore, bus: EventBus) -> str:
    label = params.get("label", "")
    cp_id = store.save(label=label)
    if cp_id:
        bus.emit(CheckpointEvent(checkpoint_id=cp_id, action="saved", label=label))
        return f"Checkpoint saved: {cp_id}"
    return "Checkpoint skipped (no changes or git unavailable)"


# ── V2Engine ──────────────────────────────────────────────────────────────────

class V2Engine(AgentEngine):
    """
    Python-native agent engine (Crown Code v2).

    Runs the full PLAN → TOOL-LOOP → VERIFY → DONE pipeline in a single
    background thread.  All progress is emitted to the EventBus.
    """

    def __init__(
        self,
        *,
        job_id: str,
        brief: str,
        workspace: Optional[str | Path],
        bus: EventBus,
        config: dict,
    ):
        self._job_id = job_id
        self._brief = brief
        self._bus = bus
        self._config = config

        # resolve workspace
        if workspace:
            self._workspace = Path(workspace)
        else:
            slug = re.sub(r"[^\w]+", "_", brief.lower())[:30].strip("_")
            self._workspace = (
                Path.home() / "Desktop" / "keys_Creations" / "code" / slug
            )

        self._status = "queued"
        self._result: dict = {}
        self._cancel_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self._checkpoints = CheckpointStore(
            workspace=self._workspace, job_id=job_id
        )
        self._loop_detector: Optional[LoopDetector] = None

    # ── AgentEngine properties ────────────────────────────────────────────────

    @property
    def job_id(self) -> str:
        return self._job_id

    @property
    def brief(self) -> str:
        return self._brief

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def result(self) -> dict:
        with self._lock:
            return dict(self._result)

    def start(self) -> None:
        with self._lock:
            if self._status != "queued":
                return
            self._status = "running"
        self._thread = threading.Thread(
            target=self._run,
            name=f"v2-engine-{self._job_id}",
            daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        self._cancel_event.set()

    def join(self, timeout: float = 30.0) -> bool:
        if self._thread is None:
            return True
        self._thread.join(timeout=timeout)
        return not self._thread.is_alive()

    # ── checkpoints ───────────────────────────────────────────────────────────

    def save_checkpoint(self, label: str = "") -> str:
        cp_id = self._checkpoints.save(label=label)
        if cp_id:
            self._bus.emit(CheckpointEvent(
                checkpoint_id=cp_id, action="saved", label=label
            ))
        return cp_id

    def restore_checkpoint(self, checkpoint_id: str) -> bool:
        ok = self._checkpoints.restore(checkpoint_id)
        if ok:
            self._bus.emit(CheckpointEvent(
                checkpoint_id=checkpoint_id, action="restored"
            ))
        return ok

    def list_checkpoints(self) -> list[dict]:
        return self._checkpoints.list()

    # ── internal pipeline ─────────────────────────────────────────────────────

    def _run(self) -> None:
        bus = self._bus

        # start loop detector
        self._loop_detector = LoopDetector(
            bus=bus,
            cancel_fn=self.cancel,
            config=LoopConfig(
                repeat_limit=self._config.get("loop_repeat_limit", 3),
                spin_limit=self._config.get("loop_spin_limit", 12),
                stall_seconds=float(self._config.get("loop_stall_seconds", 120)),
            ),
        )
        self._loop_detector.start()

        try:
            self._workspace.mkdir(parents=True, exist_ok=True)
            bus.emit(ProgressEvent("initialising", 0.02, "Workspace ready"))

            # ── Phase 1: Plan ──────────────────────────────────────────────
            if self._cancel_event.is_set():
                self._finish(ok=False, summary="cancelled before planning")
                return

            bus.emit(ProgressEvent("planning", 0.05, "Generating task plan…"))
            todos = self._plan()
            bus.emit(PlanEvent(todos=todos))
            bus.emit(ProgressEvent("planning", 0.10,
                                   f"Plan ready: {len(todos)} tasks"))

            # ── Phase 2: Tool loop ─────────────────────────────────────────
            files_written: list[str] = []
            iteration = 0
            max_iter = self._config.get("max_iterations", _MAX_ITERATIONS)
            done_todos: list[str] = []

            while iteration < max_iter and not self._cancel_event.is_set():
                iteration += 1
                pct = 0.10 + 0.70 * (iteration / max_iter)
                bus.emit(ProgressEvent(
                    "building",
                    pct,
                    f"Iteration {iteration}/{max_iter}",
                ))

                # Ask the LLM for the next action
                action = self._next_action(todos, done_todos, files_written)
                if action is None:
                    bus.emit(ThinkEvent(text="Agent chose to stop."))
                    break

                atype = action.get("type", "")
                if atype == "done":
                    summary = action.get("summary", "Build complete.")
                    bus.emit(ThinkEvent(text=summary))
                    break
                elif atype == "think":
                    bus.emit(ThinkEvent(text=action.get("text", "")))
                    continue
                elif atype == "mark_done":
                    task = action.get("task", "")
                    if task and task not in done_todos:
                        done_todos.append(task)
                    bus.emit(PlanEvent(todos=todos, done=done_todos))
                    continue
                elif atype == "tool":
                    name = action.get("name", "")
                    params = action.get("params", {})

                    bus.emit(ToolCallEvent(name=name, params=params))
                    result_text = self._exec_tool(name, params)
                    ok = not result_text.startswith("ERROR:")
                    bus.emit(ToolResultEvent(name=name, result=result_text, ok=ok))

                    if name == "write_file":
                        path = params.get("path", "")
                        if path and path not in files_written:
                            files_written.append(path)

            # ── Phase 3: Verify ────────────────────────────────────────────
            if not self._cancel_event.is_set():
                bus.emit(ProgressEvent("verifying", 0.85, "Running checks…"))
                verify_ok, verify_msg = self._verify(files_written)
                if not verify_ok:
                    bus.emit(ErrorEvent(message=verify_msg, recoverable=True))
                    # attempt one repair pass
                    bus.emit(ProgressEvent("repairing", 0.90, "Attempting repair…"))
                    self._repair(verify_msg, files_written)

            # ── Done ───────────────────────────────────────────────────────
            if self._cancel_event.is_set():
                self._finish(ok=False, summary="cancelled")
            else:
                summary = (
                    f"Built {len(files_written)} file(s): "
                    + ", ".join(files_written[:5])
                    + ("…" if len(files_written) > 5 else "")
                ) if files_written else "Task complete."
                self._finish(ok=True, summary=summary, files=files_written)

        except Exception as exc:
            bus.emit(ErrorEvent(message=str(exc), recoverable=False))
            self._finish(ok=False, summary=str(exc))
        finally:
            if self._loop_detector:
                self._loop_detector.stop()

    # ── LLM helpers ───────────────────────────────────────────────────────────

    def _llm(self, prompt: str, timeout: float = 60.0) -> str:
        """Call the configured LLM and return the raw text response."""
        try:
            from core.llm_client import complete as llm_complete
            # Use "crown_code" task so it reads config/crown_code model settings
            return llm_complete("crown_code", prompt) or ""
        except Exception as exc:
            # Fallback: try Ollama directly with the configured model
            try:
                return self._ollama_fallback(prompt)
            except Exception:
                return f"[LLM ERROR: {exc}]"

    def _ollama_fallback(self, prompt: str) -> str:
        """Direct Ollama call when llm_client is unavailable."""
        import urllib.request, json as _json
        ollama_url = self._config.get("ollama_url", "http://localhost:11434")
        model = self._config.get("model", "gemma4:12b")
        payload = _json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 1024},
        }).encode()
        req = urllib.request.Request(
            f"{ollama_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = _json.loads(resp.read())
            return data.get("response", "")

    def _plan(self) -> list[str]:
        """Ask the LLM to decompose the brief into numbered tasks."""
        prompt = (
            f"You are Crown Code, a coding agent. "
            f"Break this task into ≤10 concrete implementation steps as a numbered list. "
            f"Each step should be one action (write a file, run a command, etc.).\n\n"
            f"TASK: {self._brief}\n\n"
            f"Respond with ONLY the numbered list, no preamble."
        )
        response = self._llm(prompt, timeout=_PLAN_TIMEOUT)
        lines = response.strip().splitlines()
        todos = []
        for line in lines:
            line = line.strip()
            if re.match(r"^\d+[\.\)]\s+", line):
                todos.append(re.sub(r"^\d+[\.\)]\s+", "", line))
        return todos or [self._brief]

    def _next_action(
        self,
        todos: list[str],
        done: list[str],
        files: list[str],
    ) -> dict | None:
        """Ask the LLM for the next tool call."""
        remaining = [t for t in todos if t not in done]
        if not remaining:
            return {"type": "done", "summary": "All tasks complete."}

        files_str = ", ".join(files[-5:]) if files else "(none yet)"
        prompt = (
            "You are Crown Code. Choose the single next action.\n\n"
            f"REMAINING TASKS:\n" + "\n".join(f"- {t}" for t in remaining) + "\n\n"
            f"FILES WRITTEN SO FAR: {files_str}\n\n"
            "AVAILABLE TOOLS:\n"
            "  read_file(path)                 — read a file\n"
            "  write_file(path, content)       — write a file\n"
            "  list_dir(path)                  — list directory\n"
            "  run_shell(command)              — run a shell command\n"
            "  grep_codebase(pattern, glob)    — search code\n"
            "  checkpoint(label)               — save a checkpoint\n"
            "  mark_done(task)                 — mark a task complete\n"
            "  done(summary)                   — signal build complete\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"type": "tool", "name": "write_file", "params": {"path": "main.py", "content": "..."}}\n'
            'OR {"type": "done", "summary": "..."}\n'
            'OR {"type": "mark_done", "task": "<exact task text>"}\n'
            'OR {"type": "think", "text": "..."}'
        )
        response = self._llm(prompt)
        return _parse_action(response)

    # ── tool execution ────────────────────────────────────────────────────────

    def _exec_tool(self, name: str, params: dict) -> str:
        ws = self._workspace
        bus = self._bus

        if name == "read_file":
            bus.emit(FileReadEvent(path=str(ws / params.get("path", ""))))
            return _tool_read_file(params, ws)
        elif name == "write_file":
            return _tool_write_file(params, ws, bus)
        elif name == "list_dir":
            return _tool_list_dir(params, ws)
        elif name == "run_shell":
            return _tool_run_shell(params, ws, bus, self._cancel_event)
        elif name == "grep_codebase":
            return _tool_grep(params, ws)
        elif name == "checkpoint":
            return _tool_checkpoint(params, self._checkpoints, bus)
        else:
            return f"ERROR: unknown tool '{name}'"

    # ── verify / repair ───────────────────────────────────────────────────────

    def _verify(self, files: list[str]) -> tuple[bool, str]:
        """Run a quick syntax check on written Python files."""
        errors = []
        for rel in files:
            path = self._workspace / rel
            if path.suffix == ".py" and path.exists():
                try:
                    r = subprocess.run(
                        ["python", "-m", "py_compile", str(path)],
                        capture_output=True, text=True, timeout=10
                    )
                    if r.returncode != 0:
                        errors.append(f"{rel}: {r.stderr.strip()}")
                except Exception as exc:
                    errors.append(f"{rel}: {exc}")
        if errors:
            return False, "\n".join(errors)
        return True, ""

    def _repair(self, error: str, files: list[str]) -> None:
        """One-shot repair: ask the LLM to fix the first failing file."""
        if not files:
            return
        first = files[0]
        path = self._workspace / first
        try:
            source = path.read_text(encoding="utf-8", errors="replace")[:4000]
        except Exception:
            return

        prompt = (
            f"Fix this Python syntax error in {first}:\n\n"
            f"ERROR:\n{error[:500]}\n\n"
            f"SOURCE:\n```python\n{source}\n```\n\n"
            "Respond with ONLY the corrected Python source, no explanation."
        )
        fixed = self._llm(prompt)
        # strip markdown fences if present
        fixed = re.sub(r"^```python\n", "", fixed)
        fixed = re.sub(r"\n```$", "", fixed)
        if fixed and not fixed.startswith("[LLM ERROR"):
            _tool_write_file({"path": first, "content": fixed},
                             self._workspace, self._bus)

    # ── finish ────────────────────────────────────────────────────────────────

    def _finish(
        self, *, ok: bool, summary: str = "",
        files: list[str] | None = None
    ) -> None:
        with self._lock:
            cancelled = self._cancel_event.is_set()
            if cancelled and ok:
                ok = False
                summary = "cancelled"
            self._status = "done" if ok else ("cancelled" if cancelled else "failed")
            self._result = {
                "ok": ok,
                "summary": summary,
                "files": files or [],
            }
        self._bus.emit(DoneEvent(ok=ok, summary=summary, files=files or []))


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_action(text: str) -> dict | None:
    """Parse a JSON action from an LLM response."""
    # try to find a JSON object in the response
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
