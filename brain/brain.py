"""
KEYS.AI SMART BRAIN V2 — the central intelligence layer (spec §3).

Exposes the simple interface the rest of the app uses:

    from brain.brain import KeysBrain
    brain = KeysBrain(ui=ui, speak=speak)          # ui/speak optional
    response = brain.process(user_input)            # -> BrainResponse

Internally (spec §3 flow):
    INPUT → CONTEXT → INTENT → MEMORY RETRIEVAL → REASONING → PLAN
    → TOOL SELECTION → EXECUTION → OBSERVATION → EVALUATION
    → MEMORY UPDATE → RESPONSE

The brain is fully modular and can be disabled via config/brain.json
(`enabled: false`) or by passing enabled=False / the --no-brain CLI flag.
If anything inside fails, process() returns used_brain=False so the caller
falls back to the normal conversational path (spec §33) — a brain failure
can never crash the application.
"""

from __future__ import annotations

import re
import threading
import traceback

from brain.config import load_config
from brain.context import ContextManager
from brain.evaluator import Evaluator
from brain.executor import Executor
from brain.intelligence import IntelligenceCore
from brain.intent import (CONVERSATION, MEMORY, PAUSE, QUESTION, RESUME,
                          STOP, UNKNOWN, IntentClassifier)
from brain.log import (EVT_FALLBACK, EVT_INTENT, EVT_MEMORY_SAVED,
                       EVT_PAUSED, EVT_PLAN, EVT_RESUMED, EVT_STOPPED,
                       EVT_TASK_COMPLETE, EVT_TASK_FAILED, EVT_USER_REQUEST,
                       EVT_WAIT_USER, BrainLogger)
from brain.memory import MemoryLayer
from brain.planner import Planner
from brain.providers import get_provider
from brain.reasoning import ReasoningEngine
from brain.router import Router
from brain.safety import SafetyLayer
from brain.state import (BrainStatus, StepStatus, TaskState, new_plan,
                         new_step)
from brain.tools import ToolRegistry

CONFIRM_YES = ("yes", "yeah", "yep", "ok", "okay", "sure", "confirm",
               "do it", "go ahead", "proceed", "send it", "evet", "onayla",
               "tamam", "olur", "devam")
CONFIRM_NO = ("no", "nope", "cancel", "don't", "dont", "stop", "hayır",
              "hayir", "iptal", "vazgeç", "vazgec")


# A question about a running build must be answerable while that build runs.
_PROGRESS_QUESTION = re.compile(
    r"\b(progress|how(?:'s| is| are) (?:it|things|the (?:build|site|page|app))|"
    r"how far(?: along)?|what(?:'s| is) it doing|status|percentage|percent|"
    r"\d{1,2}\s*%|done yet|finished yet|still (?:building|working|going|running)|"
    r"eta|time left|which step)\b",
    re.I,
)


class BrainResponse:
    """Result of brain.process(). `used_brain=False` means: use the normal
    conversational path instead (fallback mode)."""

    def __init__(self, text: str = "", status: str = "",
                 used_brain: bool = True, task_id: str | None = None,
                 intent: str = "", plan_summary: str = "",
                 memory_updates: dict | None = None):
        self.text          = text
        self.status        = status or (BrainStatus.COMPLETED.value
                                        if text else BrainStatus.FAILED.value)
        self.used_brain    = used_brain
        self.task_id       = task_id
        self.intent        = intent
        self.plan_summary  = plan_summary
        self.memory_updates = memory_updates or {}

    def __repr__(self) -> str:
        return f"BrainResponse(status={self.status}, used_brain={self.used_brain})"


class KeysBrain:
    def __init__(self, ui=None, speak=None, config=None, provider=None,
                 tool_registry=None, memory_layer=None, logger=None,
                 context=None, enabled: bool | None = None):
        self.config   = config or load_config()
        self._enabled_override = enabled
        self.ui       = ui
        self.speak    = speak

        self.logger   = logger or BrainLogger(
            level=(self.config.get("logging") or {}).get("level", "info"))
        self.provider = provider if provider is not None else get_provider(
            self.config, logger=self.logger)
        self.memory   = memory_layer or MemoryLayer(
            enabled=bool((self.config.get("memory") or {}).get("enabled", True)),
            long_term=bool((self.config.get("memory") or {}).get("long_term", True)),
            llm_extract=bool((self.config.get("memory") or {}).get("llm_extract", False)),
            provider=self.provider)
        self.context  = context or ContextManager(
            max_history=int((self.config.get("context") or {}).get("max_history", 12)))
        self.tools    = tool_registry or ToolRegistry(memory_layer=self.memory,
                                                      provider=self.provider)
        self.safety   = SafetyLayer(self.config)
        self.evaluator = Evaluator(max_retries=int(self.config.get("max_retries", 2)))
        self.executor = Executor(self.tools, self.safety, self.evaluator,
                                 self.config, logger=self.logger)
        self.intent   = IntentClassifier(
            provider=self.provider,
            llm_refine=bool((self.config.get("intent") or {}).get("llm_refine", False)))
        self.router   = Router(self.tools, self.context)
        self.planner  = Planner(self.provider, self.tools, self.config)
        self.reasoning = ReasoningEngine(self.provider, self.config)

        # ── Intelligence layer (spelling / entities / semantics / situation /
        # personality + humour). Fully guarded — any failure falls back to
        # the original pipeline, so it can never break the brain. ──
        self.intelligence = IntelligenceCore(self.config,
                                              context=self.context,
                                              logger=self.logger)
        if (self.config.get("session") or {}).get("persist", True):
            try:
                self.context.restore_state()
            except Exception:
                pass

        self._status         = BrainStatus.IDLE
        self._stop_requested = False
        self._paused         = False
        # RLock: control helpers (stop/pause/resume) are called both from the
        # quick path in process() AND from inside _process_locked (which runs
        # under the same lock) — re-entrant acquisition is required or resume
        # deadlocks on a plain Lock.
        self._lock           = threading.RLock()
        self._pending        = None    # {"task": TaskState, "step_index": int}
        self._last_task      = None    # TaskState | None

    # ── status / control (spec §29) ──────────────────────────────────────
    @property
    def enabled(self) -> bool:
        if self._enabled_override is not None:
            return self._enabled_override
        return bool(self.config.get("enabled", True))

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "state": self._status.value,
            "paused": self._paused,
            "pending_confirmation": self._pending is not None,
            "active_task": self._last_task.to_dict() if self._last_task else None,
        }

    def stop(self) -> str:
        with self._lock:
            self._stop_requested = True
            self._pending = None
            self._status = BrainStatus.STOPPED
        self.executor.stop()
        self.logger.event(EVT_STOPPED, "stopped by user")
        return "Stopped."

    def pause(self) -> str:
        with self._lock:
            self._paused = True
            self._status = BrainStatus.PAUSED
        self.logger.event(EVT_PAUSED, "paused")
        return "Paused."

    def resume(self) -> str:
        with self._lock:
            self._paused = False
            self._stop_requested = False
            self._status = BrainStatus.IDLE
        self.executor.reset()
        self.logger.event(EVT_RESUMED, "resumed")
        return "Resumed."

    # ── main entry point (spec §3) ───────────────────────────────────────
    def process(self, user_input: str, ui=None, speak=None) -> BrainResponse:
        ui    = ui    or self.ui
        speak = speak or self.speak
        if not self.enabled:
            return BrainResponse(used_brain=False)

        text = (user_input or "").strip()
        if not text:
            return BrainResponse(text="", status=BrainStatus.IDLE.value,
                                 used_brain=False)
        self.logger.event(EVT_USER_REQUEST, text[:200])

        # Control intents are handled OUTSIDE the main lock so "stop" can
        # interrupt a plan running in another thread (spec §29). The intent
        # classifier is stateless, so this is thread-safe.
        quick = self.intent.classify(text)
        if quick.primary == STOP:
            return BrainResponse(self.stop(), BrainStatus.STOPPED.value,
                                 intent=STOP)
        if quick.primary == PAUSE:
            return BrainResponse(self.pause(), BrainStatus.PAUSED.value,
                                 intent=PAUSE)

        # Progress questions are answered from the build-job registry, OUTSIDE
        # the task lock. Otherwise "how's it going?" would queue behind the
        # very build it is asking about and the assistant would feel deaf.
        progress = self._build_progress(text)
        if progress is not None:
            return BrainResponse(progress, BrainStatus.COMPLETED.value,
                                 intent=quick.primary)

        # Typo-tolerant control commands: "stp" / "paus" / "contine" must
        # still stop / pause / resume. Correct first, then re-check the
        # control intents on the corrected form. Only runs when the quick
        # intent is NOT already a concrete action — a typo'd control word
        # never classifies as one, so this never wastes a correction pass.
        if (self.intelligence.is_enabled() and
                quick.primary in ("UNKNOWN", "CONVERSATION", "QUESTION")):
            try:
                corrected = self.intelligence.control_correct(text)
            except Exception:
                corrected = text
            if corrected != text:
                quick2 = self.intent.classify(corrected)
                if quick2.primary == STOP:
                    return BrainResponse(self.stop(),
                                         BrainStatus.STOPPED.value,
                                         intent=STOP)
                if quick2.primary == PAUSE:
                    return BrainResponse(self.pause(),
                                         BrainStatus.PAUSED.value,
                                         intent=PAUSE)
                if quick2.primary == RESUME:
                    quick = quick2
                    text = corrected

        # Everything else is serialised so concurrent text commands cannot
        # corrupt shared state (executor / context / _pending / _last_task).
        with self._lock:
            resp = self._process_locked(text, ui, speak, quick)
            # ── Post-process: personality-aware conversational humour ─────
            # Appended only when genuinely appropriate (never on errors,
            # code, confirmations or sensitive topics). Runs under the lock
            # so the humour engine and session state are race-free.
            self.intelligence.postprocess(resp, self.context,
                                          intent=resp.intent or quick.primary)
            if (self.config.get("session") or {}).get("persist", True):
                try:
                    self.context.save_state()
                except Exception:
                    pass
        return resp

    def _build_progress(self, text: str) -> str | None:
        """Human answer for "how's the build going?" while jobs run.

        Returns None when the message is not a progress question, or when no
        build is recent enough to talk about.
        """
        if not _PROGRESS_QUESTION.search(text or ""):
            return None
        if re.search(r"\b(system|cpu|ram|memory|gpu|disk|battery)\b", text or "", re.I):
            return None
        try:
            from core import crown_jobs
            job = crown_jobs.get()
        except Exception:
            return None
        if job is None:
            return None
        if not job.active:
            import time
            if job.ended and (time.time() - job.ended) > 600:
                return None
        return job.describe(log_lines=4)

    def _process_locked(self, text, ui, speak, intent) -> BrainResponse:
        try:
            # paused → only "resume/continue" unpauses
            if self._paused:
                if self._is_confirm(text, CONFIRM_YES) or _matches(
                        text, r"\b(resume|continue|devam|kaldığın yerden)\b"):
                    self.resume()
                else:
                    return BrainResponse(
                        text="I'm paused. Say 'continue' to resume.",
                        status=BrainStatus.PAUSED.value)

            # a fresh request after a stop — clear the flag so this new
            # command is not swallowed by the previous stop (spec §29).
            if self._stop_requested:
                self._stop_requested = False
                self.executor.reset()

            # pending confirmation from a previous turn (spec §16)
            if self._pending is not None:
                handled = self._handle_pending(text, ui, speak)
                if handled is not None:
                    return handled
                # None means the message was not a confirmation answer: the
                # pending step was dropped above and this message is now a
                # normal request, handled by the rest of this method.

            self.logger.event(EVT_INTENT,
                              f"{intent.primary} tags={intent.tags} "
                              f"conf={intent.confidence}")

            # resume / continue the previous task
            if intent.primary == RESUME:
                if self._last_task and self._last_task.remaining():
                    return self._continue_task(ui, speak, resume=True)
                self.resume()
                return BrainResponse("Resumed.", BrainStatus.IDLE.value,
                                     intent=RESUME)

            # ── Intelligence pre-process (spelling / entities / semantics) ─
            # Runs BEFORE intent/context so misspellings and names resolve
            # first (spec: RAW → NORMALIZE → CORRECT → ENTITIES → MEANING
            # → INTENT). Any failure falls back to the original text.
            prepared = self.intelligence.preprocess(text)
            if prepared.ask:
                self.logger.event("INTEL",
                                  f"clarification: {prepared.ask[:120]}")
                return BrainResponse(
                    prepared.ask, BrainStatus.WAITING_FOR_USER.value,
                    intent=prepared.intent_hint or intent.primary)
            work = prepared.resolved or text
            if work != text:
                intent = self.intent.classify(work)

            # context + reference resolution (spec §6, §23). The WORKING text
            # (corrected / entity-resolved) is what history and memory store,
            # so typos don't accumulate in long-term memory.
            self.context.add_user(work)
            resolved = self.context.resolve_references(work)

            # memory decision (spec §7) — only genuinely useful facts
            memory_updates = self.memory.decide_and_store(work)
            if memory_updates.get("handled"):
                self.logger.event(
                    EVT_MEMORY_SAVED,
                    f"saved={memory_updates.get('saved')} "
                    f"forgotten={memory_updates.get('forgotten')}")

            # pure memory requests
            if intent.primary == MEMORY:
                return self._handle_memory(work, ui, speak)

            # route (spec §22): chat / single tool / plan. The WORKING text
            # (corrected/entity-resolved) is passed so canonical casing like
            # 'VS Code' survives the router's case-preservation logic.
            self._status = BrainStatus.UNDERSTANDING
            route = self.router.route(work, intent, resolved)
            self.logger.event("ROUTED", f"{route.kind} → {route.tool} "
                                        f"{route.arguments}")

            if route.kind == "chat":
                if route.message:
                    return BrainResponse(route.message,
                                         BrainStatus.WAITING_FOR_USER.value,
                                         intent=intent.primary)
                return self._chat(work, intent, ui, speak)

            # ── plan (single tool or multi-step) ─────────────────────────
            self._status = BrainStatus.PLANNING
            if route.kind == "single_tool":
                plan = new_plan(work, intent.primary, "Single step")
                # The step description is USER-FACING: it is interpolated
                # into the confirmation question (spec §16). Prefer the
                # user's own words; never the internal route reason
                # ("coding intent → live_code" is log jargon, and leaking it
                # made the assistant claim it was confirming "coding intent
                # → live_code" instead of the user's actual request).
                desc = ((route.arguments or {}).get("description")
                        or route.tool)
                plan["steps"].append(new_step(desc, route.tool,
                                              route.arguments))
            else:
                snapshot = self.context.snapshot(
                    self.memory.format_for_prompt())
                plan = self.planner.create_plan(work, intent, resolved,
                                                snapshot)
                if plan is None:
                    # planner decided this is really just conversation
                    return self._chat(work, intent, ui, speak)
            self.logger.event(EVT_PLAN, plan.get("summary", "")
                              + f" ({len(plan['steps'])} steps)")

            return self._run_plan(work, intent, plan, ui, speak)

        except Exception as e:
            traceback.print_exc()
            self.logger.event(EVT_FALLBACK, f"brain error: {e}")
            return BrainResponse(
                text="", status=BrainStatus.FAILED.value, used_brain=False)

    # ── plan execution (spec §17) ────────────────────────────────────────
    def _run_plan(self, user_input, intent, plan, ui, speak) -> BrainResponse:
        task = TaskState(user_input, intent.primary, plan)
        self._last_task = task
        self._status = BrainStatus.EXECUTING
        self.executor.reset()

        return self._execute_from(task, 0, ui, speak)

    def _execute_from(self, task: TaskState, start_index: int, ui, speak,
                      approved_step_index: int | None = None) -> BrainResponse:
        steps = task.steps()
        for idx in range(start_index, len(steps)):
            if self._stop_requested:
                self._status = BrainStatus.STOPPED
                return BrainResponse(self._stopped_message(task),
                                     BrainStatus.STOPPED.value,
                                     task_id=task.task_id,
                                     intent=task.intent,
                                     plan_summary=task.plan.get("summary", ""))

            task.current_index = idx
            step = steps[idx]
            self.logger.event("STEP", f"{idx + 1}/{len(steps)} "
                                      f"{step.get('tool')} — "
                                      f"{step.get('description')}")
            # Only the step the user just approved skips its gate; every
            # other step is still permission-checked independently.
            step = self.executor.execute_step(
                step, ui, speak,
                approved=(idx == approved_step_index))

            # confirmation gate → pause and ask the user (spec §16). The
            # caller always speaks resp.text, so no inline speak() here —
            # otherwise the question would be spoken twice.
            if step.get("status") == StepStatus.WAITING_FOR_USER.value:
                self._pending = {"task": task, "step_index": idx}
                self._status = BrainStatus.WAITING_FOR_USER
                self.logger.event(EVT_WAIT_USER,
                                  f"waiting on: {step.get('description')}")
                question = self._confirm_question(step)
                return BrainResponse(question,
                                     BrainStatus.WAITING_FOR_USER.value,
                                     task_id=task.task_id,
                                     intent=task.intent,
                                     plan_summary=task.plan.get("summary", ""))

            task.mark_current(step.get("status"), step.get("result"),
                              step.get("error"))
            if step.get("status") == StepStatus.FAILED.value:
                task.status = BrainStatus.FAILED.value
            self._note_references(step)

        self._pending = None
        return self._finalize(task, ui, speak)

    def _finalize(self, task: TaskState, ui, speak) -> BrainResponse:
        steps = task.steps()
        done = [s for s in steps if s.get("status") == StepStatus.SUCCESS.value]
        failed = [s for s in steps
                  if s.get("status") in (StepStatus.FAILED.value,
                                         StepStatus.SKIPPED.value)]
        waiting = [s for s in steps
                   if s.get("status") == StepStatus.WAITING_FOR_USER.value]

        if len(steps) == 1 and done and not failed:
            task.status = BrainStatus.COMPLETED.value
            result = str(done[0].get("result") or "Done.").strip()
            self.logger.event(EVT_TASK_COMPLETE, task.user_request[:120])
            self.context.add_assistant(result)
            return BrainResponse(result, BrainStatus.COMPLETED.value,
                                 task_id=task.task_id, intent=task.intent,
                                 plan_summary=task.plan.get("summary", ""))
        if len(steps) == 1 and failed:
            step = failed[0]
            msg = (f"I couldn't {step.get('description', '')}: "
                   f"{step.get('error', 'something went wrong')}. "
                   "Would you like me to try again or a different way?")
            task.status = BrainStatus.FAILED.value
            self.logger.event(EVT_TASK_FAILED, task.user_request[:120])
            return BrainResponse(msg, BrainStatus.FAILED.value,
                                 task_id=task.task_id, intent=task.intent)

        lines = []
        for s in done:
            lines.append(f"✓ {s.get('description')}")
        for s in failed:
            lines.append(f"⚠️ {s.get('description')} — "
                         f"{s.get('error', 'failed')}")
        for s in waiting:
            lines.append(f"⏸ {s.get('description')} — needs your confirmation")

        if not failed:
            task.status = BrainStatus.COMPLETED.value
            text = "Done. " + " ".join(
                s.get('description') for s in done)
            self.logger.event(EVT_TASK_COMPLETE, task.user_request[:120])
        else:
            task.status = BrainStatus.FAILED.value
            text = (f"Most steps completed but {len(failed)} didn't. "
                    + " ".join(lines))
            self.logger.event(EVT_TASK_FAILED, task.user_request[:120])

        # optional natural phrasing (off by default — saves a call)
        if self.config.get("polish_response") and self.provider is not None:
            try:
                text = self.reasoning.polish(text, task.user_request)
            except Exception:
                pass

        self.context.add_assistant(text)
        return BrainResponse(text, task.status, task_id=task.task_id,
                             intent=task.intent,
                             plan_summary=task.plan.get("summary", ""))

    # ── pending confirmation handling (spec §16) ─────────────────────────
    def _handle_pending(self, text: str, ui, speak) -> BrainResponse:
        pending = self._pending
        if self._is_confirm(text, CONFIRM_YES):
            self._pending = None
            return self._execute_from(pending["task"],
                                      pending["step_index"], ui, speak,
                                      approved_step_index=
                                      pending["step_index"])
        if self._is_confirm(text, CONFIRM_NO):
            task = pending["task"]
            step = task.step(pending["step_index"])
            if step:
                step["status"] = StepStatus.SKIPPED.value
                step["error"] = "Declined by user."
                task.mark_current(StepStatus.SKIPPED.value, None,
                                  "Declined by user.")
            self._pending = None
            rest = task.steps()[pending["step_index"] + 1:]
            if rest:
                return self._execute_from(task, pending["step_index"] + 1,
                                          ui, speak)
            return BrainResponse(
                "Cancelled as you asked. Anything else?",
                BrainStatus.COMPLETED.value, task_id=task.task_id)
        # The reply was neither yes nor no. Holding the conversation hostage
        # here is a deadlock: from this state the pending step can never be
        # reached, and every new message — a correction, a different task, a
        # question — was answered with "I'm still waiting", forever. A user had
        # to know the undocumented word "stop" to escape.
        #
        # So the pending step is dropped, unexecuted, and the message is
        # processed normally. Safety is unchanged: nothing runs without an
        # explicit yes. The dropped step is recorded on the task so the reason
        # is not lost.
        task = pending["task"]
        step = task.step(pending["step_index"])
        if step is not None:
            step["status"] = StepStatus.SKIPPED.value
            step["error"] = "Superseded by a new request; not executed."
        self._pending = None
        self.logger.event(
            "CONFIRM_SUPERSEDED",
            f"dropped pending step {pending['step_index']} and handled the new "
            f"request instead")
        return None      # sentinel: continue as a normal request

    def _confirm_question(self, step: dict) -> str:
        tool = step.get("tool", "")
        desc = step.get("description") or f"use {tool}"
        # Defence in depth: a step description may still carry internal
        # routing jargon (arrow-separated route labels). The confirmation
        # sentence is shown verbatim to the user, so fall back to a plain
        # tool phrase rather than leaking it.
        if "→" in desc:
            desc = f"use {tool}"
        # The description is usually the user's own sentence: it starts
        # capitalised and ends with a period, which mid-sentence reads as
        # "before I Create a website..". Tidy both ends.
        desc = desc.strip().rstrip(".!").strip()
        if desc[:1].isupper():
            desc = desc[:1].lower() + desc[1:]
        return (f"I need your confirmation before I {desc}. "
                "Say yes to proceed, or no to skip it.")

    def _is_confirm(self, text: str, words) -> bool:
        """Word-boundary matching — "no" must NOT match inside "note" or
        "not now" (substring matching was a false-positive source)."""
        t = (text or "").strip().lower()
        if not t:
            return False
        for w in words:
            w = w.strip()
            if not w:
                continue
            if " " in w:
                if w in t:
                    return True
            elif re.search(rf"\b{re.escape(w)}\b", t):
                return True
        return False

    # ── chat fallback (spec §33) ─────────────────────────────────────────
    def _chat(self, text, intent, ui, speak) -> BrainResponse:
        self._status = BrainStatus.UNDERSTANDING
        snapshot = self.context.snapshot(self.memory.format_for_prompt())
        answer = self.reasoning.answer(text, snapshot)
        if not answer:
            # provider unavailable → normal conversational path (fallback)
            self._status = BrainStatus.FAILED
            return BrainResponse(used_brain=False)
        self.context.add_assistant(answer)
        self._status = BrainStatus.COMPLETED
        return BrainResponse(answer, BrainStatus.COMPLETED.value,
                             intent=intent.primary)

    # ── memory requests ──────────────────────────────────────────────────
    def _handle_memory(self, text, ui, speak) -> BrainResponse:
        low = " " + text.lower() + " "
        if re.search(r"\b(forget|remove from memory|unlearn)\b", low):
            hits = self.memory.search(text, top_k=5)
            if hits:
                for e in hits:
                    self.memory.forget(e["key"], e["category"])
                keys = ", ".join(f"{e['key']}" for e in hits[:3])
                return BrainResponse(f"Forgotten: {keys}.",
                                     BrainStatus.COMPLETED.value,
                                     intent=MEMORY)
            return BrainResponse("There's nothing stored under that topic.",
                                 BrainStatus.COMPLETED.value, intent=MEMORY)

        if re.search(r"\b(what do you (know|remember)|show my memory|"
                     r"what's in my memory|what have you stored)\b", low):
            formatted = self.memory.format_for_prompt()
            if formatted:
                clean = formatted.replace(
                    "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, "
                    "never recite like a list]", "")
                return BrainResponse(
                    "Here's what I remember about you:\n" + clean.strip(),
                    BrainStatus.COMPLETED.value, intent=MEMORY)
            return BrainResponse(
                "I don't have any long-term memories saved yet.",
                BrainStatus.COMPLETED.value, intent=MEMORY)

        return BrainResponse(
            "I've noted that. Is there anything else?",
            BrainStatus.COMPLETED.value, intent=MEMORY)

    def _continue_task(self, ui, speak, resume: bool) -> BrainResponse:
        task = self._last_task
        idx = task.current_index
        # find first not-yet-completed step
        while idx < len(task.steps()) and task.steps()[idx].get("status") in (
                StepStatus.SUCCESS.value,):
            idx += 1
        if resume:
            self.resume()
        self._status = BrainStatus.EXECUTING
        return self._execute_from(task, idx, ui, speak)

    # ── helpers ──────────────────────────────────────────────────────────
    def _note_references(self, step: dict) -> None:
        """Track app/file/project references for follow-up commands (§23)."""
        tool = step.get("tool", "")
        args = step.get("arguments", {})
        result = str(step.get("result") or "")
        if tool in ("open_app",) and args.get("app_name"):
            self.context.note_reference("app", str(args["app_name"]))
        elif tool in ("editor_control", "code_helper", "file_processor",
                      "file_controller") and args.get("file_path"):
            self.context.note_reference("file", str(args["file_path"]))
        elif tool == "computer_use" and str(args.get("action", "")).lower() \
                == "set_context":
            key = args.get("key", "")
            val = args.get("value", "")
            if key and val:
                if key == "app":
                    self.context.note_reference("app", val)
                elif key == "focused":
                    self.context.note_reference("window", val)
                else:
                    self.context.remember_tool_value(key, val)
        # remember set_context results embedded in the tool reply
        m = re.search(r"set_context.*?key=['\"]?(\w+)['\"]?.*?value=['\"]?"
                      r"([^'\"]+)['\"]?", result)
        if m:
            self.context.remember_tool_value(m.group(1), m.group(2).strip())

    def _stopped_message(self, task: TaskState) -> str:
        done = sum(1 for s in task.steps()
                   if s.get("status") == StepStatus.SUCCESS.value)
        return (f"Stopped. {done} of {len(task.steps())} steps completed. "
                "Say 'continue' to pick up where I left off.")


def _matches(text: str, pattern: str) -> bool:
    return re.search(pattern, text or "", re.IGNORECASE) is not None
