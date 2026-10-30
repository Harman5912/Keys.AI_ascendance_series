"""Messaging tests — validation, routing and failure honesty.

Every desktop handler is mocked: NOTHING is typed into WhatsApp/Telegram and no
message leaves this machine. What is verified is the behaviour the tool controls:
input validation, platform routing, contact gating, failure reporting and the
"confirmed vs unconfirmed" distinction.

Run: python -m unittest qa_artifacts.regression_tests.test_messaging -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

import actions.send_message as sm  # noqa: E402


class FakePlayer:
    def __init__(self):
        self.logs = []

    def write_log(self, msg):
        self.logs.append(str(msg))


class TestValidation(unittest.TestCase):
    def test_empty_receiver_rejected(self):
        out = sm.send_message({"receiver": "  ", "message_text": "hi", "platform": "whatsapp"})
        self.assertIn("recipient", out.lower())

    def test_empty_message_rejected(self):
        out = sm.send_message({"receiver": "Test Contact", "message_text": "", "platform": "whatsapp"})
        self.assertIn("message content", out.lower())

    def test_whitespace_message_rejected(self):
        out = sm.send_message({"receiver": "Test Contact", "message_text": "   \n ", "platform": "whatsapp"})
        self.assertIn("message content", out.lower())

    @mock.patch.object(sm, "_PYAUTOGUI", False)
    def test_missing_desktop_dependency_reported(self):
        out = sm.send_message({"receiver": "A", "message_text": "b", "platform": "whatsapp"})
        self.assertIn("PyAutoGUI", out)


class TestRouting(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(sm, "_PYAUTOGUI", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("_verified_contact_note", "_resolve_receiver"):
            p = mock.patch.object(sm, name, return_value=("", ""))
            p.start()
            self.addCleanup(p.stop)
        # Contact lookup is off in these tests: the spoken name is the target.
        p = mock.patch.object(sm, "_resolve_receiver", side_effect=lambda r, _p: (r, ""))
        p.start()
        self.addCleanup(p.stop)

    def _send(self, platform, text="hello", receiver="Test Contact"):
        calls = []

        def handler(r, m):
            calls.append((r, m))
            return "Message confirmed sent to Test Contact (verified on screen)."

        with mock.patch.object(sm, "_resolve_platform", return_value=handler):
            out = sm.send_message({"receiver": receiver, "message_text": text, "platform": platform})
        return out, calls

    def test_unknown_platform_routes_to_desktop_app_named_after_it(self):
        with mock.patch.object(sm, "_desktop_send", return_value="Message confirmed sent.") as desk:
            out = sm.send_message({"receiver": "A", "message_text": "b", "platform": "slack"})
        self.assertTrue(desk.called)
        self.assertEqual(desk.call_args[0][0], "Slack")
        self.assertIn("confirmed", out.lower())

    def test_unicode_and_emoji_pass_through_intact(self):
        text = "नमस्ते — café ☕ ✅ 🎉"
        _, calls = self._send("whatsapp", text)
        self.assertEqual(calls[0][1], text)

    def test_long_message_is_not_truncated_to_preview_length(self):
        text = "x" * 5000
        _, calls = self._send("whatsapp", text)
        self.assertEqual(len(calls[0][1]), 5000)

    def test_recipient_is_trimmed(self):
        _, calls = self._send("whatsapp", "hi", receiver="  Asha  ")
        self.assertEqual(calls[0][0], "Asha")

    def test_platform_aliases_resolve_to_whatsapp(self):
        self.assertIs(sm._resolve_platform("wp"), sm._send_whatsapp)
        self.assertIs(sm._resolve_platform("WhatsApp"), sm._send_whatsapp)
        self.assertIs(sm._resolve_platform("telegram"), sm._send_telegram)


class TestFailureHonesty(unittest.TestCase):
    def setUp(self):
        for name, val in (("_PYAUTOGUI", True),):
            p = mock.patch.object(sm, name, val)
            p.start()
            self.addCleanup(p.stop)
        for name in ("_verified_contact_note", "_resolve_receiver"):
            p = mock.patch.object(sm, name, return_value=("", ""))
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(sm, "_resolve_receiver", side_effect=lambda r, _p: (r, ""))
        p.start()
        self.addCleanup(p.stop)

    def test_handler_exception_is_reported_as_failure(self):
        def boom(r, m):
            raise RuntimeError("WhatsApp window not found")

        with mock.patch.object(sm, "_resolve_platform", return_value=boom):
            out = sm.send_message({"receiver": "A", "message_text": "b", "platform": "whatsapp"})
        self.assertIn("Could not send", out)
        self.assertNotIn("confirmed sent", out.lower())

    def test_unconfirmed_screen_result_is_not_reported_as_sent(self):
        def unconfirmed(r, m):
            return "Message sent to A via WhatsApp, but could NOT be confirmed on screen."

        with mock.patch.object(sm, "_resolve_platform", return_value=unconfirmed):
            out = sm.send_message({"receiver": "A", "message_text": "b", "platform": "whatsapp"})
        self.assertIn("could NOT be confirmed", out)

    def test_verified_contact_gate_blocks_before_any_handler(self):
        called = []
        with mock.patch.object(sm, "_verified_contact_note",
                               return_value=("'X' is not confirmed via Google.", "")), \
             mock.patch.object(sm, "_resolve_platform", side_effect=lambda p: called.append(p)):
            out = sm.send_message({"receiver": "X", "message_text": "b",
                                   "platform": "whatsapp", "require_verified": True})
        self.assertEqual(called, [])
        self.assertIn("not confirmed", out.lower())


class TestNoRealEffects(unittest.TestCase):
    def test_pyautogui_is_not_invoked_by_validation_paths(self):
        with mock.patch.object(sm, "_paste_text", side_effect=AssertionError("typed into desktop")) as paste:
            sm.send_message({"receiver": "", "message_text": "x", "platform": "whatsapp"})
            sm.send_message({"receiver": "A", "message_text": "", "platform": "whatsapp"})
        self.assertFalse(paste.called)


if __name__ == "__main__":
    unittest.main(verbosity=2)
