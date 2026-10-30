"""Security regression tests.

Covers: API-key masking, log scrubbing, the local dashboard bind address, the
removed calling feature answering honestly, and the secret-leak scanner finding
nothing in the mission's own logs.

Run: python -m unittest qa_artifacts.regression_tests.test_security -v
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

import core.api_config as api_config  # noqa: E402


class TestKeyMasking(unittest.TestCase):
    def test_status_never_returns_full_key(self):
        status = api_config.provider_status()
        self.assertIn("key_masked", status)
        real = api_config.get_api_key(status["provider"])
        if real:
            self.assertNotIn(real, json.dumps(status))
            self.assertNotEqual(status["key_masked"], real)
            self.assertLess(len(status["key_masked"]), len(real))

    def test_mask_hides_middle(self):
        key = "abcdefghijklmnopqrstuvwxyz0123456789"
        masked = (key[:6] + "..." + key[-4:]) if len(key) > 12 else ("set" if key else "")
        self.assertNotIn(key[10:20], masked)


class TestLogScrubbing(unittest.TestCase):
    def test_action_log_scrubs_api_key(self):
        from agent_control import action_log
        fake = "AIza" + "B" * 35
        out = action_log.scrub(f"api_key={fake} sent")
        self.assertNotIn(fake, out, "API key survived log scrubbing")

    def test_action_log_scrubs_bearer_token(self):
        from agent_control import action_log
        fake = "Bearer " + "c" * 40
        out = action_log.scrub(f"header: {fake}")
        self.assertNotIn(fake, out)

    # ── the crash S-11 ───────────────────────────────────────────────────
    def test_bare_key_shapes_do_not_raise(self):
        """scrub() used to IndexError on any pattern without a second group,
        so a log line containing a bare key killed the action recording it."""
        from agent_control import action_log
        cases = [
            "AIza" + "B" * 35,
            "sk-" + "a" * 32,
            "ghp_" + "z" * 30,
            "xoxb-" + "1" * 20,
            "eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12,
        ]
        for fake in cases:
            out = action_log.scrub(f"token seen: {fake}")
            self.assertIsInstance(out, str)
            self.assertNotIn(fake, out, f"{fake[:6]}… survived scrubbing")

    def test_labelled_secret_keeps_its_label(self):
        from agent_control import action_log
        out = action_log.scrub("api_key=supersecretvalue123")
        self.assertIn("api_key", out)
        self.assertNotIn("supersecretvalue123", out)

    def test_authorization_header_is_masked(self):
        from agent_control import action_log
        out = action_log.scrub("Authorization: Bearer abcdefghijklmnopqrstuvwxyz")
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", out)

    def test_malformed_input_never_raises(self):
        from agent_control import action_log
        for value in ("", None, 0, b"bytes", "ünïcode ✓ " * 3, "x" * 5000,
                      "token=", "AIza", "sk-"):
            out = action_log.scrub(value)
            self.assertIsInstance(out, str)

    def test_length_is_capped(self):
        from agent_control import action_log
        self.assertLessEqual(len(action_log.scrub("a " * 4000)), 220)


class TestDashboardExposure(unittest.TestCase):
    def test_mutating_routes_require_a_token(self):
        try:
            from dashboard.server import DashboardServer, _DEPS_OK
        except Exception as exc:                 # pragma: no cover
            self.skipTest(f"dashboard unavailable: {exc}")
        if not _DEPS_OK:
            self.skipTest("fastapi/uvicorn not installed")
        server = DashboardServer()
        self.assertTrue(server.auth_token)
        self.assertFalse(server._authorized(""))
        self.assertFalse(server._authorized("wrong"))
        self.assertTrue(server._authorized(server.auth_token))

    def test_default_bind_is_loopback(self):
        os.environ.pop("KEYSAI_DASHBOARD_HOST", None)
        import dashboard.server as srv
        importlib.reload(srv)
        self.assertEqual(srv.HOST, "127.0.0.1",
                         "dashboard must not listen on all interfaces by default")

    def test_bind_can_be_overridden_deliberately(self):
        os.environ["KEYSAI_DASHBOARD_HOST"] = "0.0.0.0"
        try:
            import dashboard.server as srv
            importlib.reload(srv)
            self.assertEqual(srv.HOST, "0.0.0.0")
        finally:
            os.environ.pop("KEYSAI_DASHBOARD_HOST", None)
            import dashboard.server as srv
            importlib.reload(srv)


class TestRemovedCalling(unittest.TestCase):
    def test_make_call_refuses_honestly(self):
        from actions.make_call import make_call
        out = make_call({})
        self.assertIn("cannot make calls", out.lower())
        self.assertIn("removed", out.lower())

    def test_whatsapp_control_rejects_call_actions(self):
        from actions.whatsapp_control import whatsapp_control
        for action in ("call", "make_call", "call_status", "last_call"):
            out = whatsapp_control({"action": action, "receiver": "x"})
            self.assertIn("removed", out.lower(), f"{action} did not report the removal")


class TestNoSecretsInQaLogs(unittest.TestCase):
    def test_mission_logs_contain_no_credential_values(self):
        cfg_path = BASE / "config" / "api_keys.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        secrets = [str(cfg.get(k, "")) for k in
                   ("gemini_api_key", "google_oauth_client_secret", "firebase_api_key")]
        secrets = [s for s in secrets if len(s) >= 12]
        hits = []
        for p in (BASE / "qa_artifacts").rglob("*"):
            if not p.is_file() or p.suffix.lower() not in {".log", ".txt", ".json", ".csv", ".md"}:
                continue
            if p.name == "test_security.py":
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            for s in secrets:
                if s in text:
                    hits.append(str(p.relative_to(BASE)))
        self.assertEqual(hits, [], f"credential value found in: {hits}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
