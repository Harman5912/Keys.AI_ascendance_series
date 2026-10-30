"""
Tests for the KEYS.AI SMART BRAIN V2 (brain/ package).

All tests run OFFLINE — a FakeProvider and FakeRegistry stand in for the
network and the real tools, so this suite never calls Gemini or touches the
user's desktop. Covers: intent, context/references, memory, safety, planner,
executor, and the full brain loop (incl. confirmation + fallback).

Run:  python -m unittest test_brain -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from brain.brain import KeysBrain
from brain.config import BrainConfig
from brain.context import ContextManager
from brain.evaluator import Evaluator
from brain.executor import Executor
from brain.intent import (APP_CONTROL, CODING, COMPUTER_ACTION, CONVERSATION,
                          MEMORY, MULTI_STEP_TASK, PAUSE, QUESTION, REMINDER,
                          RESUME, STOP, SYSTEM_TASK, WEB_RESEARCH,
                          IntentClassifier)
from brain.memory import MemoryLayer
from brain.planner import Planner
from brain.router import Router
from brain.safety import Decision, SafetyLayer, SafetyLevel
from brain.state import BrainStatus, StepStatus, TaskState, new_plan, new_step
from brain.tools import ToolRegistry


# ── fakes ────────────────────────────────────────────────────────────────────
class FakeProvider:
    name = "fake"

    def __init__(self, generate_text="fake answer", structured=None,
                 fail=False, vision_text="I see a screen."):
        self.calls = []
        self._gen = generate_text
        self._structured = structured
        self._fail = fail
        self._vision = vision_text

    def generate(self, prompt, system=None, temperature=0.2, max_tokens=None):
        self.calls.append(("generate", prompt[:60]))
        if self._fail:
            raise RuntimeError("fake provider boom")
        return self._gen

    def structured_output(self, prompt, system=None, temperature=0.0):
        self.calls.append(("structured", prompt[:60]))
        if self._fail:
            raise RuntimeError("fake provider boom")
        return self._structured

    def describe_image(self, image_bytes, mime_type, question):
        return self._vision

    def available(self):
        return True


class FakeRegistry:
    def __init__(self, results=None, fail_first=None):
        self.calls = []
        self._results = results or {}
        self._fail_first = fail_first or {}

    def names(self):
        return ["open_app", "web_search", "send_message", "system_status",
                "save_memory", "weather_report", "code_helper"]

    def has(self, name):
        return name in self.names()

    def descriptions(self, max_tools=40):
        return ("- open_app: opens an application\n"
                "- send_message: sends a message\n"
                "- web_search: searches the web\n"
                "- system_status: cpu/ram\n"
                "- weather_report: weather\n"
                "- code_helper: write/edit/run code")

    def execute(self, name, args, ui=None, speak=None):
        self.calls.append((name, dict(args)))
        n = self._fail_first.get(name, 0)
        if n > 0:
            self._fail_first[name] = n - 1
            return {"ok": True, "tool": name,
                    "result": "failed: temporary problem", "error": None}
        if name in self._results:
            r = self._results[name]
            if isinstance(r, Exception):
                raise r
            return r
        return {"ok": True, "tool": name, "result": f"{name} done: {args}",
                "error": None}


def make_config(**overrides):
    base = {
        "enabled": True,
        "provider": "fake",
        "model": "fake-model",
        "max_iterations": 10,
        "max_retries": 2,
        "autonomous_mode": True,
        "confirm_moderate": True,
        "confirm_dangerous": True,
        "polish_response": False,
        "memory": {"enabled": True, "long_term": True, "llm_extract": False},
        "intent": {"llm_refine": False},
        "context": {"max_history": 12},
        "logging": {"level": "info"},
        "permissions": {
            "DANGEROUS": ["file_controller"],
            "MODERATE": ["send_message"],
            "SAFE": ["open_app", "web_search", "system_status",
                     "weather_report", "code_helper"],
        },
        "blocked_tools": [],
    }

    def _merge(a, b):
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                _merge(a[k], v)
            else:
                a[k] = v

    _merge(base, overrides)
    return BrainConfig(base)


class _SpyUI:
    def __init__(self):
        self.logs = []
        self.spoken = []
        self.states = []

    def write_log(self, text):
        self.logs.append(text)

    def set_state(self, state):
        self.states.append(state)

    def show_content(self, title, text):
        pass

    def stop_camera_stream(self):
        pass


def make_brain(cfg=None, provider=None, registry=None, memory_path=None):
    cfg = cfg or make_config()
    ui = _SpyUI()
    if memory_path is None:
        memory_path = Path(tempfile.mkdtemp()) / "long_term.json"
    mem = MemoryLayer(memory_path=memory_path)
    brain = KeysBrain(
        ui=ui, speak=ui.spoken.append, config=cfg,
        provider=provider or FakeProvider(structured=None),
        tool_registry=registry or FakeRegistry(),
        memory_layer=mem)
    return brain, ui


# ── intent ───────────────────────────────────────────────────────────────────
class TestIntent(unittest.TestCase):
    def setUp(self):
        self.clf = IntentClassifier()

    def test_open_app(self):
        r = self.clf.classify("open chrome")
        self.assertEqual(r.primary, APP_CONTROL)
        self.assertIn(COMPUTER_ACTION, r.tags)

    def test_web_research(self):
        r = self.clf.classify("search the web for the latest AI news")
        self.assertEqual(r.primary, WEB_RESEARCH)

    def test_reminder(self):
        r = self.clf.classify("remind me to call mom at 5pm")
        self.assertEqual(r.primary, REMINDER)

    def test_memory(self):
        r = self.clf.classify("remember that I prefer Python")
        self.assertEqual(r.primary, MEMORY)

    def test_stop(self):
        r = self.clf.classify("stop")
        self.assertEqual(r.primary, STOP)

    def test_pause_resume(self):
        self.assertEqual(self.clf.classify("pause").primary, PAUSE)
        self.assertEqual(self.clf.classify("continue").primary, RESUME)

    def test_question(self):
        r = self.clf.classify("what is the capital of France?")
        self.assertEqual(r.primary, QUESTION)

    def test_conversation(self):
        r = self.clf.classify("hello, how are you?")
        self.assertIn(CONVERSATION, r.tags)

    def test_system_task(self):
        r = self.clf.classify("how is my cpu and ram usage?")
        self.assertEqual(r.primary, SYSTEM_TASK)

    def test_multi_step_tags(self):
        r = self.clf.classify(
            "open chrome and search for python docs and summarize")
        self.assertIn(MULTI_STEP_TASK, r.tags)

    def test_coding(self):
        r = self.clf.classify("fix the error in my python project")
        self.assertIn(CODING, r.tags)


# ── context / references ─────────────────────────────────────────────────────
class TestContext(unittest.TestCase):
    def test_pronoun_resolution_app(self):
        ctx = ContextManager()
        ctx.note_reference("app", "ReviewBot")
        self.assertEqual(ctx.resolve_references("run it"), "run ReviewBot")

    def test_pronoun_resolution_file_priority(self):
        ctx = ContextManager()
        ctx.note_reference("app", "VS Code")
        ctx.note_reference("file", "C:/projects/main.py")
        self.assertEqual(ctx.resolve_references("fix this"),
                         "fix C:/projects/main.py")

    def test_that_app(self):
        ctx = ContextManager()
        ctx.note_reference("app", "WhatsApp")
        self.assertEqual(ctx.resolve_references("open that app"),
                         "open WhatsApp")

    def test_history_snapshot(self):
        ctx = ContextManager(max_history=4)
        ctx.add_user("open chrome")
        ctx.add_assistant("Chrome is open.")
        snap = ctx.snapshot()
        self.assertIn("Chrome is open.", snap)

    def test_tool_memory(self):
        ctx = ContextManager()
        ctx.remember_tool_value("workspace", "C:/Projects/KeysAI")
        self.assertIn("workspace=C:/Projects/KeysAI", ctx.snapshot())


# ── memory ──────────────────────────────────────────────────────────────────
class TestMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "mem.json"
        self.mem = MemoryLayer(memory_path=self.tmp)

    def test_remember_recall(self):
        self.mem.remember("language", "Python", "preferences")
        found = self.mem.search("python", top_k=5)
        self.assertTrue(any(e["key"] == "language" for e in found))
        self.assertIn("Python", self.mem.recall("python"))

    def test_forget(self):
        self.mem.remember("language", "Python", "preferences")
        self.mem.forget("language", "preferences")
        self.assertEqual(self.mem.search("python", top_k=5), [])

    def test_decision_preference(self):
        out = self.mem.decide_and_store("I prefer Python")
        self.assertTrue(out["handled"])
        self.assertTrue(out["saved"])
        self.assertIn("Python", self.mem.recall("prefer"))

    def test_decision_name(self):
        out = self.mem.decide_and_store("my name is Harman")
        self.assertTrue(out["handled"])
        self.assertIn("identity/name", out["saved"])

    def test_decision_favorite(self):
        out = self.mem.decide_and_store(
            "my favorite coding language is Python")
        self.assertTrue(out["handled"])
        self.assertTrue(any("favorite" in s for s in out["saved"]))

    def test_decision_forget(self):
        self.mem.remember("language", "Python", "preferences")
        out = self.mem.decide_and_store("forget language")
        self.assertTrue(out["forgotten"])

    def test_decision_plain_conversation_saves_nothing(self):
        out = self.mem.decide_and_store("how are you today?")
        self.assertFalse(out["handled"])


# ── safety ───────────────────────────────────────────────────────────────────
class TestSafety(unittest.TestCase):
    def test_levels(self):
        cfg = make_config()
        s = SafetyLayer(cfg)
        self.assertEqual(s.permission_for("open_app", {}), SafetyLevel.SAFE)
        self.assertEqual(s.permission_for("send_message", {}),
                         SafetyLevel.MODERATE)
        self.assertEqual(s.permission_for("file_controller",
                                          {"action": "delete",
                                           "path": "C:/x"}),
                         SafetyLevel.DANGEROUS)

    def test_action_escalation(self):
        cfg = make_config()
        s = SafetyLayer(cfg)
        self.assertEqual(
            s.permission_for("open_app",
                             {"action": "shutdown", "value": "pc"}),
            SafetyLevel.DANGEROUS)

    def test_decisions(self):
        cfg = make_config()
        s = SafetyLayer(cfg)
        self.assertEqual(s.decision("open_app", {}, cfg), Decision.ALLOW)
        self.assertEqual(s.decision("send_message", {}, cfg), Decision.ASK)
        self.assertEqual(s.decision("file_controller",
                                    {"action": "delete"}, cfg),
                         Decision.ASK)

    def test_blocked_tool(self):
        cfg = make_config(blocked_tools=["system_status"])
        s = SafetyLayer(cfg)
        self.assertEqual(s.decision("system_status", {}, cfg),
                         Decision.BLOCK)

    def test_confirm_moderate_off_allows(self):
        cfg = make_config(confirm_moderate=False)
        s = SafetyLayer(cfg)
        self.assertEqual(s.decision("send_message", {}, cfg),
                         Decision.ALLOW)


# ── evaluator ───────────────────────────────────────────────────────────────
class TestEvaluator(unittest.TestCase):
    def setUp(self):
        self.ev = Evaluator(max_retries=2)

    def test_success(self):
        e = self.ev.evaluate({"ok": True, "result": "Done."})
        self.assertTrue(e.is_success())

    def test_failure_marker(self):
        e = self.ev.evaluate({"ok": True,
                              "result": "Error: connection refused"})
        self.assertEqual(e.status, "soft_fail")
        self.assertTrue(e.is_retryable())

    def test_crash(self):
        e = self.ev.evaluate({"ok": False, "error": "boom"})
        self.assertEqual(e.status, "hard_fail")

    def test_retry_bounds(self):
        e = self.ev.evaluate({"ok": True, "result": "failed again"})
        self.assertTrue(self.ev.should_retry(e, 1))
        self.assertFalse(self.ev.should_retry(e, 2))


# ── router ──────────────────────────────────────────────────────────────────
class TestRouter(unittest.TestCase):
    def setUp(self):
        self.reg = FakeRegistry()
        self.ctx = ContextManager()
        self.router = Router(self.reg, self.ctx)
        self.clf = IntentClassifier()

    def _route(self, text):
        intent = self.clf.classify(text)
        resolved = self.ctx.resolve_references(text)
        return self.router.route(text, intent, resolved)

    def test_open_app(self):
        d = self._route("open chrome")
        self.assertEqual(d.kind, "single_tool")
        self.assertEqual(d.tool, "open_app")
        self.assertEqual(d.arguments["app_name"], "Chrome")

    def test_search(self):
        d = self._route("search the web for python tutorials")
        self.assertEqual(d.kind, "single_tool")
        self.assertEqual(d.tool, "web_search")
        self.assertIn("python tutorials", d.arguments["query"])

    def test_weather(self):
        d = self._route("what is the weather in Istanbul")
        self.assertEqual(d.tool, "weather_report")

    def test_system_status(self):
        d = self._route("check my cpu usage")
        self.assertEqual(d.tool, "system_status")

    def test_multi_step_goes_to_plan(self):
        d = self._route("open chrome and search for X and summarize it")
        self.assertEqual(d.kind, "plan")

    # ── user-facing wording (no internal jargon in confirmations) ───────
    def test_coding_route_description_is_the_user_text_not_route_reason(self):
        """The step description feeds the confirmation question, so it must
        be the user's own request — not the route reason
        ('coding intent → live_code' leaked verbatim to the user)."""
        d = self._route("build me a portfolio website using Python and HTML")
        self.assertEqual((d.kind, d.tool), ("single_tool", "crown_code"))
        desc = (d.arguments or {}).get("description") or ""
        self.assertNotIn("→", desc)
        self.assertIn("portfolio", desc.lower())

    def test_confirmation_question_never_leaks_route_jargon(self):
        from brain.brain import KeysBrain
        q = KeysBrain._confirm_question(None, {
            "tool": "crown_code",
            "description": "coding intent → crown_code"})
        self.assertNotIn("→", q)
        self.assertIn("use crown_code", q)

    def test_confirmation_question_keeps_plain_descriptions(self):
        from brain.brain import KeysBrain
        q = KeysBrain._confirm_question(None, {
            "tool": "crown_code",
            "description": "build the portfolio website"})
        self.assertIn("build the portfolio website", q)
        self.assertIn("Say yes to proceed", q)

    def test_confirmation_question_tidies_user_sentence_descriptions(self):
        """The user's own sentence arrives capitalised and full-stopped;
        mid-sentence that read as 'before I Create a website..'."""
        from brain.brain import KeysBrain
        q = KeysBrain._confirm_question(None, {
            "tool": "crown_code",
            "description": "Create a Python Flask website."})
        self.assertIn("before I create a Python Flask website.", q)
        self.assertNotIn("..", q)

    # ── admin elevation (legitimate UAC path only) ─────────────────────
    def test_make_me_admin_routes_to_elevation(self):
        d = self._route("make me admin")
        self.assertEqual(d.kind, "single_tool")
        self.assertEqual(d.tool, "computer_use")
        self.assertEqual(d.arguments["action"], "elevate")

    def test_run_as_administrator_routes_to_elevation(self):
        d = self._route("run this as administrator")
        self.assertEqual((d.tool, d.arguments.get("action")),
                         ("computer_use", "elevate"))

    def test_admin_question_reads_status_instead_of_raising_uac(self):
        d = self._route("do I have administrator rights?")
        self.assertEqual((d.tool, d.arguments.get("action")),
                         ("computer_use", "elevation"))

    def test_admin_product_builds_are_not_hijacked_by_elevation(self):
        """'build me an admin dashboard' must stay a coding request."""
        d = self._route("build me an admin dashboard with charts")
        self.assertFalse(d.tool == "computer_use" and
                         d.arguments.get("action") == "elevate",
                         f"coding request hijacked: {d!r}")

    def test_question_about_past_work_is_answered_not_executed(self):
        """'Did you actually run it?' must be answered in chat, not turned
        into a confirmation prompt to start a new build (honesty defect)."""
        for t in ("Did you actually run my application, or did you only "
                  "write the code?",
                  "have you tested this project?"):
            d = self._route(t)
            self.assertEqual(d.kind, "chat", f"{t!r} routed to {d!r}")
            self.assertNotEqual(d.tool, "crown_code", t)

    def test_every_single_tool_route_names_a_registered_tool(self):
        """A route that names an unregistered tool is a dead end: the executor
        returns 'Unknown tool' while logging a successful step."""
        from brain.tools import ToolRegistry
        reg = ToolRegistry()
        cases = [
            "build me a portfolio website using Python and HTML",
            "write a python script that parses a csv file",
            "check my cpu usage",
            "what's the weather in Istanbul",
            "search the web for python 3.13 release notes",
            "make me admin",
        ]
        for text in cases:
            d = self._route(text)
            if d.kind != "single_tool":
                continue
            self.assertTrue(reg.has(d.tool),
                            f"{text!r} routed to unregistered tool {d.tool!r}")

    def test_pronoun_no_reference_clarifies(self):
        d = self._route("run it")
        self.assertEqual(d.kind, "chat")
        self.assertTrue(d.message)

    def test_pronoun_with_reference(self):
        self.ctx.note_reference("app", "ReviewBot")
        intent = self.clf.classify("run it")
        resolved = self.ctx.resolve_references("run it")
        # pronoun resolves against the previous reference…
        self.assertIn("ReviewBot", resolved)
        # …and the router builds a plan for the resolved command
        d = self.router.route("run it", intent, resolved)
        self.assertEqual(d.kind, "plan")


# ── planner ─────────────────────────────────────────────────────────────────
class TestPlanner(unittest.TestCase):
    def test_template_fallback_single_step(self):
        cfg = make_config()
        reg = FakeRegistry()
        intent = IntentClassifier().classify("open chrome")
        planner = Planner(None, reg, cfg)
        plan = planner.create_plan("open chrome", intent, "open chrome", "")
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan["steps"]), 1)
        self.assertEqual(plan["steps"][0]["tool"], "open_app")

    def test_llm_plan(self):
        cfg = make_config()
        reg = FakeRegistry()
        provider = FakeProvider(structured={
            "summary": "open and search",
            "chat": False,
            "steps": [
                {"description": "open chrome", "tool": "open_app",
                 "arguments": {"app_name": "Chrome"}},
                {"description": "search python", "tool": "web_search",
                 "arguments": {"query": "python docs", "mode": "search"}},
            ],
        })
        intent = IntentClassifier().classify(
            "open chrome and search for python docs")
        planner = Planner(provider, reg, cfg)
        plan = planner.create_plan("open chrome and search for python docs",
                                   intent, "open chrome and search for "
                                   "python docs", "")
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan["steps"]), 2)

    def test_llm_plan_rejects_unknown_tool(self):
        cfg = make_config()
        reg = FakeRegistry()
        provider = FakeProvider(structured={
            "summary": "bad", "chat": False,
            "steps": [{"description": "hack", "tool": "NOT_A_TOOL",
                       "arguments": {}}],
        })
        intent = IntentClassifier().classify("do something")
        planner = Planner(provider, reg, cfg)
        plan = planner.create_plan("do something", intent, "do something", "")
        self.assertIsNone(plan)  # all steps dropped → None → chat


# ── executor ────────────────────────────────────────────────────────────────
class TestExecutor(unittest.TestCase):
    def test_success_step(self):
        cfg = make_config()
        reg = FakeRegistry()
        exec_ = Executor(reg, SafetyLayer(cfg), Evaluator(), cfg)
        step = new_step("open chrome", "open_app", {"app_name": "Chrome"})
        out = exec_.execute_step(step)
        self.assertEqual(out["status"], StepStatus.SUCCESS.value)
        self.assertEqual(reg.calls[0][0], "open_app")

    def test_confirmation_gate(self):
        cfg = make_config()
        reg = FakeRegistry()
        exec_ = Executor(reg, SafetyLayer(cfg), Evaluator(), cfg)
        step = new_step("send message", "send_message",
                        {"receiver": "John", "message_text": "hi"})
        out = exec_.execute_step(step)
        self.assertEqual(out["status"], StepStatus.WAITING_FOR_USER.value)
        self.assertEqual(reg.calls, [])  # nothing executed

    def test_blocked_tool(self):
        cfg = make_config(blocked_tools=["web_search"])
        reg = FakeRegistry()
        exec_ = Executor(reg, SafetyLayer(cfg), Evaluator(), cfg)
        step = new_step("search", "web_search", {"query": "x"})
        out = exec_.execute_step(step)
        self.assertEqual(out["status"], StepStatus.FAILED.value)

    def test_retry_then_success(self):
        cfg = make_config(max_retries=2)
        reg = FakeRegistry(fail_first={"open_app": 2})
        exec_ = Executor(reg, SafetyLayer(cfg), Evaluator(max_retries=2), cfg)
        step = new_step("open chrome", "open_app", {"app_name": "Chrome"})
        out = exec_.execute_step(step)
        self.assertEqual(out["status"], StepStatus.SUCCESS.value)
        self.assertEqual(len(reg.calls), 3)   # 2 fails + 1 success

    def test_stop_flag(self):
        cfg = make_config()
        reg = FakeRegistry()
        exec_ = Executor(reg, SafetyLayer(cfg), Evaluator(), cfg)
        exec_.stop()
        step = new_step("open chrome", "open_app", {"app_name": "Chrome"})
        out = exec_.execute_step(step)
        self.assertEqual(out["status"], StepStatus.SKIPPED.value)

    def test_dangerous_no_retry(self):
        # dangerous action + confirm off → executes, but never retries
        cfg = make_config(confirm_dangerous=False, max_retries=2)
        reg = FakeRegistry(fail_first={"file_controller": 5})
        exec_ = Executor(reg, SafetyLayer(cfg), Evaluator(max_retries=2), cfg)
        step = new_step("delete file", "file_controller",
                        {"action": "delete", "path": "C:/x"})
        out = exec_.execute_step(step)
        self.assertEqual(out["status"], StepStatus.FAILED.value)
        self.assertEqual(len(reg.calls), 1)   # executed exactly once


# ── full brain loop ─────────────────────────────────────────────────────────
class _TempSessionState(unittest.TestCase):
    """Keep session persistence out of the user's real config directory.

    KeysBrain.process() writes brain.context.SESSION_STATE_PATH, so without this
    a test run leaves its fixture references ("ReviewBot", "Dhananjay") in
    config/session_state.json and the next app start restores them.
    """

    def setUp(self):
        import brain.context as bctx
        self._tmp = tempfile.TemporaryDirectory()
        self._state = mock.patch.object(
            bctx, "SESSION_STATE_PATH",
            Path(self._tmp.name) / "session_state.json")
        self._state.start()

    def tearDown(self):
        try:
            self._state.stop()
        finally:
            self._tmp.cleanup()


class TestBrain(_TempSessionState):
    def test_single_tool_execution(self):
        brain, ui = make_brain()
        resp = brain.process("open chrome")
        self.assertTrue(resp.used_brain)
        self.assertEqual(resp.intent, APP_CONTROL)
        self.assertIn("open_app done", resp.text)

    def test_chat_when_no_tools(self):
        brain, ui = make_brain(provider=FakeProvider(
            generate_text="Ankara is the capital of Turkey."))
        resp = brain.process("what is the capital of Turkey?")
        self.assertTrue(resp.used_brain)
        self.assertIn("Ankara", resp.text)

    def test_confirmation_flow(self):
        brain, ui = make_brain()
        resp = brain.process("send a message to John: hello")
        self.assertEqual(resp.status, BrainStatus.WAITING_FOR_USER.value)
        resp2 = brain.process("yes")
        self.assertTrue(resp2.used_brain)
        self.assertIn("send_message done", resp2.text)
        self.assertTrue(any(c[0] == "send_message"
                            for c in brain.tools.calls))

    def test_confirmation_decline(self):
        brain, ui = make_brain()
        brain.process("send a message to John: hello")
        resp = brain.process("no")
        self.assertEqual(resp.status, BrainStatus.COMPLETED.value)
        self.assertFalse(any(c[0] == "send_message"
                             for c in brain.tools.calls))

    def test_stop(self):
        brain, ui = make_brain()
        resp = brain.process("stop")
        self.assertEqual(resp.status, BrainStatus.STOPPED.value)

    def test_stop_during_confirmation(self):
        brain, ui = make_brain()
        brain.process("send a message to John: hello")
        self.assertEqual(brain.status()["pending_confirmation"], True)
        # "stop" must HARD-stop, not decline-and-continue the plan
        resp = brain.process("stop")
        self.assertEqual(resp.status, BrainStatus.STOPPED.value)
        self.assertEqual(brain.status()["pending_confirmation"], False)

    def test_confirm_no_is_word_boundary(self):
        brain, ui = make_brain()
        brain.process("send a message to John: hello")
        # "not now" must NOT be treated as a "no": the decline path would
        # answer "Cancelled as you asked" and continue the plan.
        resp = brain.process("not now")
        self.assertNotIn("Cancelled", resp.text)
        self.assertFalse(any(c[0] == "send_message"
                             for c in brain.tools.calls))

    def test_unanswered_reply_while_pending_is_not_a_deadlock(self):
        """A non-yes/no reply must not trap the user in WAITING forever.

        Repro of the defect: after one confirmation prompt, "I'm still
        waiting" answered every following message — corrections, new tasks,
        questions — and only the undocumented word "stop" escaped.
        """
        brain, ui = make_brain()
        brain.process("send a message to John: hello")
        self.assertTrue(brain.status()["pending_confirmation"])

        resp = brain.process("use sqlite for the database instead")

        # the new message was handled as a request, not stonewalled
        self.assertFalse(brain.status()["pending_confirmation"],
                         "user is still stuck at the confirmation prompt")
        self.assertNotIn("still waiting", resp.text.lower())
        # safety unchanged: the risky step never ran without a yes
        self.assertFalse(any(c[0] == "send_message"
                             for c in brain.tools.calls))
        # the dropped step is recorded, not silently forgotten
        task = brain._last_task
        step = task.step(0) if task else None
        self.assertIsNotNone(step)
        self.assertEqual(step["status"], StepStatus.SKIPPED.value)
        self.assertIn("Superseded", step.get("error", ""))

    def test_yes_still_confirms_after_an_unanswered_reply(self):
        """Dropping the pending step must not break the normal yes path on a
        later, freshly requested action."""
        brain, ui = make_brain()
        brain.process("send a message to John: hello")
        brain.process("open chrome")              # unrelated reply → dropped
        resp = brain.process("send a message to John: are you there?")
        self.assertEqual(resp.status, BrainStatus.WAITING_FOR_USER.value)
        resp2 = brain.process("yes")
        self.assertIn("send_message done", resp2.text)
        self.assertTrue(any(c[0] == "send_message"
                            for c in brain.tools.calls))

    def test_new_command_after_stop_runs(self):
        brain, ui = make_brain()
        brain.process("stop")
        # a fresh command must not be swallowed by the previous stop
        resp = brain.process("open chrome")
        self.assertTrue(resp.used_brain)
        self.assertIn("open_app done", resp.text)

    def test_forget_everything(self):
        brain, ui = make_brain()
        brain.memory.remember("language", "Python", "preferences")
        brain.memory.remember("project", "ReviewBot", "projects")
        out = brain.memory.decide_and_store("forget everything")
        self.assertTrue(out["forgotten"])
        self.assertEqual(brain.memory.search("python"), [])
        self.assertEqual(brain.memory.search("reviewbot"), [])

    def test_remember_flow(self):
        brain, ui = make_brain()
        resp = brain.process("remember that I prefer Python")
        self.assertTrue(resp.used_brain)
        self.assertIn("Python", brain.memory.recall("prefer python"))

    def test_memory_recall_question(self):
        brain, ui = make_brain()
        brain.memory.remember("language", "Python", "preferences")
        resp = brain.process("what do you remember about me?")
        self.assertIn("Python", resp.text)

    def test_llm_plan_execution(self):
        provider = FakeProvider(structured={
            "summary": "two steps",
            "chat": False,
            "steps": [
                {"description": "open chrome", "tool": "open_app",
                 "arguments": {"app_name": "Chrome"}},
                {"description": "check cpu", "tool": "system_status",
                 "arguments": {}},
            ],
        })
        brain, ui = make_brain(provider=provider)
        resp = brain.process(
            "open chrome and check my cpu usage and tell me")
        self.assertTrue(resp.used_brain)
        tools_called = [c[0] for c in brain.tools.calls]
        self.assertIn("open_app", tools_called)
        self.assertIn("system_status", tools_called)

    def test_fallback_when_provider_crashes(self):
        brain, ui = make_brain(provider=FakeProvider(fail=True))
        resp = brain.process("hello there")
        self.assertFalse(resp.used_brain)   # caller falls back to chat

    def test_disabled_brain(self):
        brain, ui = make_brain(cfg=make_config(enabled=False))
        resp = brain.process("open chrome")
        self.assertFalse(resp.used_brain)

    def test_reference_continuity(self):
        brain, ui = make_brain()
        brain.process("open ReviewBot")
        intent = brain.intent.classify("open it")
        resolved = brain.context.resolve_references("open it")
        self.assertIn("ReviewBot", resolved)

    def test_task_state_serialization(self):
        plan = new_plan("test", "COMMAND")
        plan["steps"].append(new_step("open chrome", "open_app",
                                      {"app_name": "Chrome"}))
        task = TaskState("test", "COMMAND", plan)
        task.mark_current(StepStatus.SUCCESS.value, "done", None)
        data = task.to_dict()
        restored = TaskState.from_dict(data)
        self.assertEqual(restored.steps()[0]["status"],
                         StepStatus.SUCCESS.value)


# ── tools specials ──────────────────────────────────────────────────────────
class TestToolsSpecials(unittest.TestCase):
    def test_save_memory_via_registry(self):
        tmp = Path(tempfile.mkdtemp()) / "mem.json"
        mem = MemoryLayer(memory_path=tmp)
        reg = ToolRegistry(memory_layer=mem, provider=None)
        res = reg.execute("save_memory",
                          {"category": "preferences", "key": "lang",
                           "value": "Python"})
        self.assertTrue(res["ok"])
        self.assertIn("Python", mem.recall("lang"))


if __name__ == "__main__":
    unittest.main()
