"""Unit tests for the Keys.ai Agent Control Mode.

Run: python test_agent_control.py

Covers: the control state machine, the control-history log (with privacy
scrubbing), the humour engine (settings gating), the high-impact
confirmation gate, settings validation/persistence, and the agent_control /
agent_settings tool argument validation. All Qt/automation-free.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_control import states, action_log, humour, confirmation, settings  # noqa: E402
from agent_control import tools  # noqa: E402


def _reset_all():
    settings.reset_settings()
    action_log.reset_history()
    humour.reset_humour()
    confirmation.reset_gate()
    states.reset_machine()
    try:
        from agent_control import app_control, emergency
        app_control.reset_control_engine()
        emergency.reset_emergency()
    except Exception:
        pass


class _FakeSettings:
    def __init__(self, level="MEDIUM", dark=False, professional=False):
        self._d = {"humour_level": level, "dark_humour": dark,
                   "professional_mode": professional,
                   "confirm_high_impact": True}

    def get(self, key, default=None):
        return self._d.get(key, default)


class TestStateMachine(unittest.TestCase):

    def setUp(self):
        self.m = states.ControlStateMachine()

    def test_happy_path_flow(self):
        flow = [states.UNDERSTANDING, states.INSPECTING, states.PLANNING,
                states.CONTROL_ACTIVE, states.EXECUTING, states.VERIFYING,
                states.CONTINUE, states.COMPLETED, states.CONTROL_RELEASED,
                states.IDLE]
        for s in flow:
            self.assertTrue(self.m.transition(s), "should allow -> %s" % s)
        self.assertEqual(self.m.state, states.IDLE)

    def test_recover_path(self):
        for s in (states.INSPECTING, states.PLANNING, states.CONTROL_ACTIVE,
                  states.EXECUTING, states.RECOVER, states.INSPECTING):
            self.assertTrue(self.m.transition(s))
        self.assertEqual(self.m.state, states.INSPECTING)

    def test_invalid_transitions_rejected(self):
        self.assertFalse(self.m.transition(states.VERIFYING))
        self.assertEqual(self.m.state, states.IDLE)

    def test_pause_resume(self):
        self.m.transition(states.EXECUTING)
        self.assertTrue(self.m.transition(states.PAUSED))
        self.assertTrue(self.m.transition(states.EXECUTING))

    def test_emergency_stop_priority(self):
        self.m.transition(states.EXECUTING)
        self.assertTrue(self.m.force(states.STOPPED))
        self.assertEqual(self.m.state, states.STOPPED)

    def test_user_takeover(self):
        self.m.transition(states.EXECUTING)
        self.assertTrue(self.m.transition(states.USER_TAKEOVER))
        self.assertTrue(self.m.transition(states.PAUSED))

    def test_ui_status_mapping(self):
        self.assertEqual(states.ui_status(states.EXECUTING)[0], "EXECUTING")
        self.assertEqual(states.ui_status(states.FAILED)[0], "ACTION FAILED")
        self.assertEqual(states.ui_status(states.IDLE)[0], "CONTROL RELEASED")

    def test_unknown_state_rejected(self):
        self.assertFalse(self.m.transition("BANANA"))


class TestActionLog(unittest.TestCase):

    def setUp(self):
        self.h = action_log.ControlHistory()

    def test_add_and_update(self):
        e = self.h.add("VS Code", "open_file", "opened server.js", action_log.RUNNING)
        self.assertEqual(e["status"], action_log.RUNNING)
        self.h.update_status(e, action_log.SUCCESS)
        self.assertEqual(self.h.recent(1)[0]["status"], action_log.SUCCESS)

    def test_status_icons_present(self):
        for st in (action_log.SUCCESS, action_log.RUNNING, action_log.WAITING,
                   action_log.FAILED, action_log.PAUSED, action_log.STOPPED):
            self.assertIn(st, action_log.STATUS_ICON)

    def test_privacy_scrub(self):
        out = action_log.scrub("api_key=AIzaSy1234567890abcdefghijklmnopqrstuvwxyz sent")
        self.assertNotIn("AIzaSy", out)
        self.assertIn("***", out)
        out2 = action_log.scrub("token: ghp_abcdefghijklmnopqrstuvwxyz1234567890")
        self.assertNotIn("ghp_", out2)
        out3 = action_log.scrub("password=hunter2")
        self.assertNotIn("hunter2", out3)

    def test_clear_and_cap(self):
        for i in range(20):
            self.h.add("App", "action%d" % i)
        self.assertEqual(self.h.count(), 20)
        self.h.clear()
        self.assertEqual(self.h.count(), 0)

    def test_render(self):
        self.h.add("VS Code", "opened", "server.js", action_log.SUCCESS)
        out = self.h.render(5)
        self.assertIn("VS Code", out)
        self.assertIn("opened", out)


class TestHumour(unittest.TestCase):

    def setUp(self):
        self.h = humour.HumourEngine()

    def test_professional_mode_disables(self):
        self.h._settings = _FakeSettings(professional=True)
        self.assertFalse(self.h.enabled())
        self.assertIsNone(self.h.comment("open", force=True))

    def test_off_disables(self):
        self.h._settings = _FakeSettings(level="OFF")
        self.assertFalse(self.h.enabled())
        self.assertIsNone(self.h.sample("open"))

    def test_sample_returns_comment(self):
        self.h._settings = _FakeSettings(level="MEDIUM")
        c = self.h.sample("open", "VS Code")
        self.assertTrue(c and len(c) > 3)

    def test_unknown_event_falls_back_to_generic(self):
        self.h._settings = _FakeSettings(level="HIGH")
        c = self.h.sample("mystery_event")
        self.assertTrue(c and len(c) > 3)

    def test_comment_never_crashes(self):
        self.h._settings = _FakeSettings(level="HIGH")
        for ev in ("open", "error", "build_failure", "slow_computer",
                   "slow_network", "success", "verify", "fix", "long",
                   "click", "typing", "generic"):
            self.h.comment(ev, force=False)  # must not raise


class TestConfirmation(unittest.TestCase):

    def test_classify_high_impact(self):
        for a in ("send", "send_message", "send_email", "delete",
                  "delete_file", "submit", "purchase", "post", "publish",
                  "uninstall", "format", "email"):
            self.assertEqual(confirmation.classify(a), "high", a)

    def test_classify_harmless(self):
        for a in ("open", "scroll", "search", "read", "inspect", "find",
                  "focus", "navigate", "switch_tab", "copy", "paste",
                  "select", "move_mouse", "type", "wait", "verify"):
            self.assertEqual(confirmation.classify(a), "low", a)

    def test_classify_description_markers(self):
        self.assertEqual(confirmation.classify("click", "click the send button"), "high")
        self.assertEqual(confirmation.classify("click", "click the search box"), "low")
        self.assertEqual(confirmation.classify("type", "type a message and send it"), "high")

    def test_gate_without_bridge_is_honest(self):
        g = confirmation.ConfirmationGate(settings=_FakeSettings())
        self.assertEqual(g.request("send"), confirmation.ConfirmationGate.RESULT_CANCEL)

    def test_gate_disabled_by_settings(self):
        s = _FakeSettings()
        g = confirmation.ConfirmationGate(settings=s)
        self.assertTrue(g.needs_confirmation("send"))
        s._d["confirm_high_impact"] = False
        self.assertFalse(g.needs_confirmation("send"))


class TestSettings(unittest.TestCase):

    def test_validation(self):
        with tempfile.TemporaryDirectory() as td:
            s = settings.AgentControlSettings(path=Path(td) / "s.json")
            self.assertTrue(s.set("humour_level", "high"))
            self.assertEqual(s.get("humour_level"), "HIGH")
            self.assertFalse(s.set("humour_level", "banana"))
            self.assertFalse(s.set("not_a_key", 1))
            self.assertTrue(s.set("retry_limit", 5))
            self.assertFalse(s.set("retry_limit", -3))
            self.assertTrue(s.set("dark_humour", True))

    def test_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "s.json"
            s1 = settings.AgentControlSettings(path=p)
            s1.set("humour_level", "LOW")
            s1.set("dark_humour", True)
            s2 = settings.AgentControlSettings(path=p)
            self.assertEqual(s2.get("humour_level"), "LOW")
            self.assertTrue(s2.get("dark_humour"))

    def test_summary(self):
        with tempfile.TemporaryDirectory() as td:
            s = settings.AgentControlSettings(path=Path(td) / "s.json")
            out = settings.settings_summary(s)
            self.assertIn("Humour", out)
            self.assertIn("Retry limit", out)


class TestTools(unittest.TestCase):

    def setUp(self):
        _reset_all()

    def test_agent_control_unknown_action(self):
        out = tools.agent_control({"action": "bogus_action"})
        self.assertIn("Unknown agent_control action", out)

    def test_agent_control_no_action(self):
        out = tools.agent_control({})
        self.assertIn("No action specified", out)

    def test_agent_control_press_requires_key(self):
        out = tools.agent_control({"action": "press"})
        self.assertIn("Provide a key name", out)

    def test_agent_control_type_requires_text(self):
        out = tools.agent_control({"action": "type"})
        self.assertIn("Provide text to type", out)

    def test_agent_control_scroll_validates_direction(self):
        out = tools.agent_control({"action": "scroll", "direction": "sideways"})
        self.assertIn("Scroll direction", out)

    def test_agent_control_move_requires_coords(self):
        out = tools.agent_control({"action": "move"})
        self.assertIn("x and y coordinates", out)

    def test_agent_control_open_app_requires_name(self):
        out = tools.agent_control({"action": "open_app"})
        self.assertIn("application name", out)

    def test_agent_control_history(self):
        out = tools.agent_control({"action": "history", "limit": 5})
        self.assertTrue(out)

    def test_agent_control_humour_action(self):
        out = tools.agent_control({"action": "humour", "event": "open", "app": "VS Code"})
        self.assertTrue(out and len(out) > 3)

    def test_agent_settings_get(self):
        out = tools.agent_settings({"action": "get"})
        self.assertIn("Humour", out)

    def test_agent_settings_set(self):
        out = tools.agent_settings({"action": "set", "humour_level": "HIGH",
                                    "professional_mode": True})
        self.assertIn("updated", out)
        self.assertIn("HIGH", out)

    def test_agent_settings_set_invalid(self):
        out = tools.agent_settings({"action": "set", "humour_level": "BANANA"})
        self.assertIn("Rejected", out)

    def test_agent_settings_reset(self):
        tools.agent_settings({"action": "set", "humour_level": "OFF"})
        out = tools.agent_settings({"action": "reset"})
        self.assertIn("defaults", out)
        self.assertIn("MEDIUM", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
