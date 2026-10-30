"""Regression tests: live feature demo + WhatsApp contact fallback.

The demo must be callable, registered, bounded, and must not send anything.
The messaging fallback must ask WhatsApp's own search when Google contacts
cannot resolve a name — and must prefer a Google match when there is one.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from actions import feature_demo  # noqa: E402
from actions import send_message as sm  # noqa: E402


class _Player:
    def __init__(self):
        self.events = []
        self.logs = []

    def write_log(self, text):
        self.logs.append(str(text))

    def creation_event(self, *a):
        self.events.append(a)

    def creation_progress(self, *a):
        pass

    def creation_phase(self, *a):
        pass

    def creation_complete(self, *a):
        pass

    def show_content(self, *a):
        pass


class DemoRegistrationTest(unittest.TestCase):
    def test_declared_and_registered(self):
        from core.tool_declarations import TOOL_DECLARATIONS
        from core.tool_registry import TOOL_HANDLERS

        self.assertIn("feature_demo", TOOL_HANDLERS)
        decl = next((d for d in TOOL_DECLARATIONS if d.get("name") == "feature_demo"), None)
        self.assertIsNotNone(decl)
        self.assertIn("demo", decl["description"].lower())

    def test_list_and_idle_status(self):
        self.assertIn("system", feature_demo.feature_demo({"action": "list"}))
        feature_demo._STATE["running"] = False
        self.assertIn("No demo is running", feature_demo.feature_demo({"action": "status"}))

    def test_quick_steps_run_and_report(self):
        player = _Player()
        out = feature_demo.feature_demo(
            {"action": "run", "steps": "system,memory"}, player=player)
        self.assertIn("Demo started", out)
        deadline = time.time() + 30
        while feature_demo._STATE["running"] and time.time() < deadline:
            time.sleep(0.2)
        self.assertFalse(feature_demo._STATE["running"])
        results = feature_demo._STATE["results"]
        self.assertEqual([r["step"] for r in results], ["system", "memory"])
        self.assertTrue(all(r["ok"] for r in results), results)
        report = Path(feature_demo._STATE["report"])
        self.assertTrue(report.exists())
        self.assertIn("demo_report", report.name)


class ResolveReceiverTest(unittest.TestCase):
    def test_google_contact_preferred(self):
        contact = {"name": "Ravi Kumar", "phone": "+919999999999",
                   "source": "google"}
        with mock.patch("core.firebase_client.is_signed_in", return_value=True), \
             mock.patch("core.firebase_client.find_contact", return_value=contact), \
             mock.patch.object(sm, "_whatsapp_contact_search") as wa:
            target, note = sm._resolve_receiver("Ravi", "WhatsApp")
        self.assertEqual(target, "+919999999999")
        self.assertIn("Ravi Kumar", note)
        wa.assert_not_called()

    def test_whatsapp_search_used_when_google_has_nothing(self):
        with mock.patch("core.firebase_client.is_signed_in", return_value=True), \
             mock.patch("core.firebase_client.find_contact", return_value=None), \
             mock.patch.object(sm, "_whatsapp_contact_search",
                               return_value=("Ravi Kumar",
                                             " (matched in WhatsApp's own search)")):
            target, note = sm._resolve_receiver("Ravi", "WhatsApp")
        self.assertEqual(target, "Ravi Kumar")
        self.assertIn("WhatsApp", note)

    def test_whatsapp_search_used_when_google_lookup_raises(self):
        with mock.patch("core.firebase_client.is_signed_in", return_value=True), \
             mock.patch("core.firebase_client.find_contact",
                        side_effect=RuntimeError("Firebase token refresh failed")), \
             mock.patch.object(sm, "_whatsapp_contact_search",
                               return_value=("Elena Voss", " (matched in WhatsApp)")):
            target, note = sm._resolve_receiver("Elena", "WhatsApp")
        self.assertEqual(target, "Elena Voss")
        self.assertIn("WhatsApp", note)

    def test_no_match_is_reported_honestly(self):
        with mock.patch("core.firebase_client.is_signed_in", return_value=True), \
             mock.patch("core.firebase_client.find_contact", return_value=None), \
             mock.patch.object(sm, "_whatsapp_contact_search",
                               return_value=("", " (no chat or contact by that name)")):
            target, note = sm._resolve_receiver("Nobody", "WhatsApp")
        self.assertEqual(target, "Nobody")
        self.assertIn("no chat or contact", note)


class ProjectTestGuardTest(unittest.TestCase):
    def test_passing_tests_are_accepted(self):
        import tempfile
        from actions.crown_code import _verify_project_tests

        with tempfile.TemporaryDirectory() as d:
            Path(d, "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n",
                                             encoding="utf-8")
            ok, note = _verify_project_tests(Path(d))
        self.assertTrue(ok, note)
        self.assertIn("pass", note)

    def test_failing_tests_are_reported(self):
        import tempfile
        from actions.crown_code import _verify_project_tests

        with tempfile.TemporaryDirectory() as d:
            Path(d, "test_bad.py").write_text(
                "def test_bad():\n    assert '--x--' == 'x'\n", encoding="utf-8")
            ok, note = _verify_project_tests(Path(d))
        self.assertFalse(ok)
        self.assertIn("pytest exit", note)

    def test_no_tests_needs_no_check(self):
        import tempfile
        from actions.crown_code import _verify_project_tests

        with tempfile.TemporaryDirectory() as d:
            Path(d, "app.py").write_text("print('hi')\n", encoding="utf-8")
            self.assertEqual(_verify_project_tests(Path(d)), (True, ""))


class AgentRepairTest(unittest.TestCase):
    class _Job:
        def __init__(self):
            self.progress = 0.5
            self.cancelled = False
            self.phase = "working"
            self.logs = []

        def update(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    def test_repairs_failing_tests_with_real_output(self):
        from actions import crown_code as cc

        calls = []

        def fake(job, task, *a, **k):
            calls.append(task)
            if len(calls) == 1:
                return {"ok": False, "tests_ok": False,
                        "test_note": "pytest exit 1: assert '--test---' == 'test'"}
            return {"ok": True, "tests_ok": True, "summary": "fixed"}

        with mock.patch.object(cc, "_run_bridge", side_effect=fake):
            out = cc._agent_build(self._Job(), "build stringkit", Path("C:/tmp/x"),
                                  "qwen3:8b", "ollama", "safe", 60, None,
                                  verify_tests=True)
        self.assertTrue(out["ok"])
        self.assertEqual(len(calls), 2)
        self.assertIn("REPAIR PASS", calls[1])
        self.assertIn("assert '--test---' == 'test'", calls[1])
        self.assertIn("Do not delete, skip or weaken a test", calls[1])

    def test_no_repair_when_tests_pass(self):
        from actions import crown_code as cc

        calls = []

        def fake(job, task, *a, **k):
            calls.append(task)
            return {"ok": True, "tests_ok": True, "summary": "done"}

        with mock.patch.object(cc, "_run_bridge", side_effect=fake):
            out = cc._agent_build(self._Job(), "build x", Path("C:/tmp/x"),
                                  "qwen3:8b", "ollama", "safe", 60, None,
                                  verify_tests=True)
        self.assertTrue(out["ok"])
        self.assertEqual(len(calls), 1)

    def test_gives_up_after_two_repairs_and_reports_failure(self):
        from actions import crown_code as cc

        calls = []

        def fake(job, task, *a, **k):
            calls.append(task)
            return {"ok": False, "tests_ok": False, "test_note": "1 failed"}

        with mock.patch.object(cc, "_run_bridge", side_effect=fake):
            out = cc._agent_build(self._Job(), "build x", Path("C:/tmp/x"),
                                  "qwen3:8b", "ollama", "safe", 60, None,
                                  verify_tests=True, repair_attempts=2)
        self.assertFalse(out["ok"])
        self.assertEqual(len(calls), 3)      # original + 2 repair passes

    def test_no_repair_for_non_test_failures(self):
        from actions import crown_code as cc

        calls = []

        def fake(job, task, *a, **k):
            calls.append(task)
            return {"ok": False, "tests_ok": True, "summary": "no files written"}

        with mock.patch.object(cc, "_run_bridge", side_effect=fake):
            cc._agent_build(self._Job(), "build x", Path("C:/tmp/x"),
                            "qwen3:8b", "ollama", "safe", 60, None,
                            verify_tests=True)
        self.assertEqual(len(calls), 1)


class WhatsAppRowParsingTest(unittest.TestCase):
    def test_extracts_name_from_real_uia_rows(self):
        cases = {
            "Mini Malaysia 09:53 Crown_Code_Product_Showcase.pptx": "Mini Malaysia",
            "Dhananjay Allen 06:41": "Dhananjay Allen",
            "IEEE IDEATHON 2026 04:19 ~Udit Gupta : Cast your vote": "IEEE IDEATHON 2026",
            "Ravi Kumar Thursday see you at six": "Ravi Kumar",
            "View status Dhananjay Allen 06:41 Your data list": "Dhananjay Allen",
            "Pinned chat Mini Malaysia 09:53 hi": "Mini Malaysia",
            "Elena Voss": "Elena Voss",
            "Mum yesterday ok": "Mum",
        }
        for row, expected in cases.items():
            self.assertEqual(sm._wa_name_from_row(row), expected, row)


class WhatsAppDirectSearchTest(unittest.TestCase):
    class _Ctrl:
        def __init__(self, elements):
            self.elements = elements
            self.focused = ""

        def list_windows(self):
            return mock.Mock(data={"windows": [{"title": "WhatsApp"}]})

        def focus_window(self, title):
            self.focused = title
            return mock.Mock(ok=True)

        def list_elements(self, window):
            return mock.Mock(data={"elements": self.elements})

    def test_picks_the_contact_and_skips_whatsapp_chrome(self):
        ctrl = self._Ctrl([
            {"name": "Chats", "control_type": "Button"},
            {"name": "Search", "control_type": "Edit"},
            {"name": "Ravi Kumar", "control_type": "DataItem"},
            {"name": "Ravi Kumar\nYesterday: see you at 6", "control_type": "DataItem"},
            {"name": "Ravindra", "control_type": "DataItem"},
        ])
        with mock.patch.object(sm, "_PYAUTOGUI", True), \
             mock.patch.object(sm, "_search_in_app") as typed, \
             mock.patch("automation.get_controller", return_value=ctrl):
            label, note = sm._whatsapp_contact_search("Ravi Kumar")
        self.assertEqual(label, "Ravi Kumar")
        self.assertIn("WhatsApp", note)
        typed.assert_called_once_with("Ravi Kumar")
        self.assertEqual(ctrl.focused, "WhatsApp")

    def test_no_match_is_reported_not_invented(self):
        ctrl = self._Ctrl([{"name": "Chats", "control_type": "Button"},
                           {"name": "Status", "control_type": "Button"},
                           {"name": "Calls", "control_type": "Button"}])
        with mock.patch.object(sm, "_PYAUTOGUI", True), \
             mock.patch.object(sm, "_search_in_app"), \
             mock.patch("automation.get_controller", return_value=ctrl):
            label, note = sm._whatsapp_contact_search("Nobody Here")
        self.assertEqual(label, "")
        self.assertIn("no chat or contact", note)

    def test_search_box_text_is_not_a_contact(self):
        # The search field's name becomes the typed query; it must never be
        # treated as a matching chat.
        ctrl = self._Ctrl([{"name": "Mini", "control_type": "Edit"},
                           {"name": "Mini Malaysia 09:53 hello",
                            "control_type": "DataItem"}])
        with mock.patch.object(sm, "_PYAUTOGUI", True), \
             mock.patch.object(sm, "_search_in_app"), \
             mock.patch("automation.get_controller", return_value=ctrl):
            label, _ = sm._whatsapp_contact_search("Mini")
        self.assertEqual(label, "Mini Malaysia")

    def test_single_word_match_works(self):
        ctrl = self._Ctrl([{"name": "Elena Voss", "control_type": "ListItem"},
                           {"name": "Chats", "control_type": "Button"}])
        with mock.patch.object(sm, "_PYAUTOGUI", True), \
             mock.patch.object(sm, "_search_in_app"), \
             mock.patch("automation.get_controller", return_value=ctrl):
            label, _ = sm._whatsapp_contact_search("Elena")
        self.assertEqual(label, "Elena Voss")


class WhatsAppControlFallbackTest(unittest.TestCase):
    def test_send_resolves_through_fallback(self):
        from actions import whatsapp_control as wc

        with mock.patch.object(wc, "_robust_send_whatsapp",
                               return_value="sent (verified)") as robust:
            with mock.patch.object(wc, "get_adapter", create=True):
                out = wc.whatsapp_control({"action": "send", "receiver": "Ravi",
                                           "message_text": "hi"})
        self.assertIn("sent", out)
        robust.assert_called_once_with("Ravi", "hi", session_memory=None, player=None)


if __name__ == "__main__":
    unittest.main()
