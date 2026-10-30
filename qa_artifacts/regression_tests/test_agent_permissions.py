"""Regression tests for the coding-agent permission policy, the config store,
the tool-result contract, the dashboard guard and the router's coding route.

Every test here corresponds to a defect found in the October 2026 audit and
fixed in this pass:

    * S-03  actions/crown_code.py approved every permission request (True)
    * S-11  agent_control.scrub raised IndexError on a bare key-like token
    * R-03  brain/router.py routed coding to the non-existent `live_code`
    * unknown tools reported ok=True with "Unknown tool: …" as the payload
    * R-02  three uncoordinated writers of config/api_keys.json
    * R-01  two coroutines consumed the dashboard command queue
    * dashboard mutating routes had no authorisation

Run: python -m unittest qa_artifacts.regression_tests.test_agent_permissions -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from core import agent_permissions as ap  # noqa: E402

WS = str(Path(tempfile.gettempdir()) / "keysai_perm_ws")


# ── policy classification ─────────────────────────────────────────────────
class TestPermissionPolicy(unittest.TestCase):
    def test_workspace_write_is_allowed_unattended(self):
        d = ap.evaluate({"tool": "write_file", "input": {"path": "app/main.py"}},
                        workspace=WS, policy="safe")
        self.assertTrue(d.allow, d.reason)
        self.assertEqual(d.risk, ap.MODERATE)

    def test_read_inside_workspace_is_low_risk(self):
        d = ap.evaluate({"tool": "read_file", "input": {"path": "README.md"}},
                        workspace=WS, policy="safe")
        self.assertTrue(d.allow)
        self.assertEqual(d.risk, ap.LOW)

    def test_delete_requires_approval_and_fails_closed_without_one(self):
        d = ap.evaluate({"tool": "delete_file", "input": {"path": "main.py"}},
                        workspace=WS, policy="safe")
        self.assertFalse(d.allow)
        self.assertTrue(d.requires_approval)
        self.assertEqual(d.risk, ap.HIGH)

    def test_delete_is_denied_even_with_policy_all(self):
        d = ap.evaluate({"tool": "delete_file", "input": {"path": "main.py"}},
                        workspace=WS, policy="all")
        self.assertFalse(d.allow, "policy=all must not pre-authorise deletion")

    def test_approver_can_grant_and_deny(self):
        ev = {"tool": "delete_file", "input": {"path": "old.py"}}
        granted = ap.evaluate(ev, workspace=WS, policy="safe",
                              approve=lambda d: "allow_once")
        denied = ap.evaluate(ev, workspace=WS, policy="safe",
                             approve=lambda d: "deny")
        self.assertTrue(granted.allow)
        self.assertFalse(denied.allow)

    def test_approver_that_raises_denies(self):
        def boom(_):
            raise RuntimeError("no UI thread")

        d = ap.evaluate({"tool": "delete_file", "input": {"path": "x"}},
                        workspace=WS, policy="safe", approve=boom)
        self.assertFalse(d.allow)
        self.assertIn("denied", d.reason)

    def test_allow_task_remembers_the_tool(self):
        seen = set()
        ev = {"tool": "terminal", "input": {"command": "pip install requests"}}
        first = ap.evaluate(ev, workspace=WS, policy="safe",
                            approve=lambda d: "allow_task", session_allows=seen)
        second = ap.evaluate(ev, workspace=WS, policy="safe", approve=None,
                             session_allows=seen)
        self.assertTrue(first.allow)
        self.assertTrue(second.allow, "allow_task should not ask twice")

    def test_install_and_network_need_approval(self):
        for cmd in ("pip install requests", "npm install left-pad",
                    "curl https://example.com"):
            d = ap.evaluate({"tool": "terminal", "input": {"command": cmd}},
                            workspace=WS, policy="safe")
            self.assertFalse(d.allow, cmd)
            self.assertEqual(d.risk, ap.HIGH, cmd)

    def test_ordinary_build_command_is_allowed(self):
        for cmd in ("python -m pytest -q", "python app.py", "node build.js"):
            d = ap.evaluate({"tool": "terminal", "input": {"command": cmd}},
                            workspace=WS, policy="safe")
            self.assertTrue(d.allow, f"{cmd}: {d.reason}")

    def test_destructive_command_is_never_allowed(self):
        d = ap.evaluate({"tool": "terminal",
                         "input": {"command": "rm -rf / --no-preserve-root"}},
                        workspace=WS, policy="all")
        self.assertFalse(d.allow)
        self.assertEqual(d.risk, ap.CRITICAL)

    def test_credential_access_is_denied_at_every_policy(self):
        for pol in ("readonly", "safe", "all"):
            d = ap.evaluate({"tool": "read_file", "input": {"path": ".env"}},
                            workspace=WS, policy=pol)
            self.assertFalse(d.allow, pol)
            self.assertEqual(d.risk, ap.CRITICAL, pol)

    def test_path_escape_is_detected(self):
        d = ap.evaluate({"tool": "write_file",
                         "input": {"path": "../../etc/passwd"}},
                        workspace=WS, policy="safe")
        self.assertFalse(d.allow)
        self.assertEqual(d.risk, ap.CRITICAL)

    def test_readonly_policy_blocks_writes(self):
        d = ap.evaluate({"tool": "write_file", "input": {"path": "a.py"}},
                        workspace=WS, policy="readonly")
        self.assertFalse(d.allow)

    def test_unknown_tool_needs_approval(self):
        d = ap.evaluate({"tool": "frobnicate"}, workspace=WS, policy="safe")
        self.assertFalse(d.allow)
        self.assertTrue(d.requires_approval)

    def test_inside_handles_symlink_style_segments(self):
        self.assertTrue(ap.inside(f"{WS}/a/../b.py", WS))
        self.assertFalse(ap.inside(f"{WS}/../outside.py", WS))


# ── bridge integration ────────────────────────────────────────────────────
class TestBridgePermissionWiring(unittest.TestCase):
    def setUp(self):
        from core.crown_bridge import CrownBridge
        self.bridge = CrownBridge(workspace=WS, policy="safe")
        self.sent = []
        self.bridge.send_permission = lambda rid, allow: self.sent.append((rid, allow))

    def test_default_policy_allows_write_denies_delete(self):
        self.bridge._dispatch({"type": "permission_request", "id": "1",
                               "tool": "write_file", "input": {"path": "a.py"}})
        self.bridge._dispatch({"type": "permission_request", "id": "2",
                               "tool": "delete_file", "input": {"path": "a.py"}})
        self.assertEqual(self.sent, [("1", True), ("2", False)])

    def test_raising_handler_denies(self):
        def boom(_):
            raise ValueError("ui gone")

        self.bridge.permission_handler = boom
        self.bridge._dispatch({"type": "permission_request", "id": "9",
                               "tool": "write_file", "input": {"path": "a.py"}})
        self.assertEqual(self.sent, [("9", False)])

    def test_none_returning_handler_denies(self):
        self.bridge.permission_handler = lambda ev: None
        self.bridge._dispatch({"type": "permission_request", "id": "3",
                               "tool": "write_file", "input": {"path": "a.py"}})
        self.assertEqual(self.sent, [("3", False)])

    def test_decision_object_is_honoured_and_recorded(self):
        self.bridge.permission_handler = lambda ev: ap.Decision(
            allow=True, risk=ap.MODERATE, reason="test", tool="write_file")
        self.bridge._dispatch({"type": "permission_request", "id": "4",
                               "tool": "write_file", "input": {"path": "a.py"}})
        self.assertEqual(self.sent, [("4", True)])
        self.assertEqual(self.bridge.last_permission.reason, "test")

    def test_crown_code_uses_the_supervisor_not_a_constant(self):
        """The old bridge was built with permission_handler=lambda ev: True."""
        import inspect
        import actions.crown_code as cc
        src = inspect.getsource(cc._run_bridge)
        self.assertNotIn("permission_handler=lambda ev: True", src)
        self.assertIn("_permission_handler", src)


# ── config store ──────────────────────────────────────────────────────────
class TestConfigStore(unittest.TestCase):
    def setUp(self):
        from core import config_store, secret_store
        self.store = config_store
        self.secrets = secret_store
        self._orig = config_store.CONFIG_PATH
        self._orig_secrets = secret_store.SECRETS_PATH
        self._orig_migrated = config_store._migrated
        self.tmpdir = tempfile.mkdtemp()
        config_store.CONFIG_PATH = Path(self.tmpdir) / "api_keys.json"
        secret_store.SECRETS_PATH = Path(self.tmpdir) / "secrets.enc"
        secret_store.reset_cache()
        config_store._migrated = True          # no migration against the temp file

    def tearDown(self):
        self.store.CONFIG_PATH = self._orig
        self.secrets.SECRETS_PATH = self._orig_secrets
        self.secrets.reset_cache()
        self.store._migrated = self._orig_migrated

    def test_merge_preserves_unrelated_keys(self):
        self.store.update({"llm_provider": "gemini"})
        self.store.update({"voice_name": "Charon"})
        data = self.store.load()
        self.assertEqual(data["llm_provider"], "gemini")
        self.assertEqual(data["voice_name"], "Charon")

    def test_no_temp_file_is_left_behind(self):
        self.store.update({"a": 1})
        leftovers = [p.name for p in Path(self.tmpdir).iterdir() if ".tmp" in p.name]
        self.assertEqual(leftovers, [])

    def test_concurrent_writers_do_not_lose_keys(self):
        """Two threads saving different keys concurrently must both survive."""
        barrier = threading.Barrier(2)
        errors = []

        def writer(key):
            try:
                barrier.wait(timeout=5)
                for i in range(15):
                    self.store.update({f"{key}_{i}": i})
            except Exception as exc:            # pragma: no cover
                errors.append(exc)

        t1 = threading.Thread(target=writer, args=("left",))
        t2 = threading.Thread(target=writer, args=("right",))
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertEqual(errors, [])
        data = self.store.load()
        for i in range(15):
            self.assertIn(f"left_{i}", data)
            self.assertIn(f"right_{i}", data)

    def test_corrupt_file_is_quarantined_not_crashed(self):
        Path(self.tmpdir).mkdir(parents=True, exist_ok=True)
        self.store.CONFIG_PATH.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.store.load(), {})
        self.store.update({"ok": True})
        self.assertTrue(self.store.load()["ok"])

    def test_api_config_goes_through_the_store(self):
        from core import api_config
        api_config.CONFIG_PATH = self.store.CONFIG_PATH
        api_config.save_config({"llm_provider": "ollama"})
        api_config.save_config({"voice_name": "Puck"})
        data = json.loads(self.store.CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(data["llm_provider"], "ollama")
        self.assertEqual(data["voice_name"], "Puck")

    # ── credentials at rest ──────────────────────────────────────────────
    def test_credentials_are_not_written_to_the_json(self):
        if not self.secrets.available():
            self.skipTest("DPAPI unavailable on this platform")
        fake = "AIza" + "F" * 35
        self.store.update({"gemini_api_key": fake, "voice_name": "Kore"})
        raw = self.store.CONFIG_PATH.read_text(encoding="utf-8")
        self.assertNotIn(fake, raw, "credential was written in plaintext")
        self.assertIn("Kore", raw)
        # …and reading still returns the real value to every caller
        self.assertEqual(self.store.load()["gemini_api_key"], fake)

    def test_clearing_a_credential_removes_it_from_both_stores(self):
        if not self.secrets.available():
            self.skipTest("DPAPI unavailable on this platform")
        self.store.update({"openai_api_key": "sk-" + "a" * 30})
        self.store.update(remove=["openai_api_key"])
        self.assertNotIn("openai_api_key", self.store.load())
        self.assertNotIn("openai_api_key", self.secrets.names())

    def test_legacy_plaintext_is_migrated(self):
        if not self.secrets.available():
            self.skipTest("DPAPI unavailable on this platform")
        fake = "AIza" + "L" * 35
        self.store.CONFIG_PATH.write_text(json.dumps({
            "llm_provider": "gemini", "gemini_api_key": fake,
        }), encoding="utf-8")
        self.store._migrated = False          # allow the one-time migration
        data = self.store.load()
        self.assertEqual(data["gemini_api_key"], fake)
        raw = self.store.CONFIG_PATH.read_text(encoding="utf-8")
        self.assertNotIn(fake, raw)
        self.assertIn("llm_provider", raw)

    def test_secret_name_classification(self):
        if not self.secrets.available():
            self.skipTest("DPAPI unavailable on this platform")
        for name in ("gemini_api_key", "firebase_refresh_token",
                     "google_oauth_client_secret", "nvidia_api_key_backups"):
            self.assertTrue(self.secrets.is_secret_name(name), name)
        for name in ("llm_provider", "voice_name", "theme", "max_tokens"):
            self.assertFalse(self.secrets.is_secret_name(name), name)


# ── tool result contract ──────────────────────────────────────────────────
class TestToolContract(unittest.TestCase):
    def test_unknown_tool_is_a_failure_not_a_success(self):
        from brain.tools import ToolRegistry
        reg = ToolRegistry()
        out = reg.execute("live_code", {"action": "start"})
        self.assertFalse(out["ok"], "unknown tool reported success")
        self.assertIn("Unknown tool", out["error"])

    def test_router_coding_route_reaches_a_registered_tool(self):
        from brain.context import ContextManager
        from brain.intent import IntentClassifier
        from brain.router import Router
        from brain.tools import ToolRegistry
        clf = IntentClassifier()
        registry = ToolRegistry()
        router = Router(registry, ContextManager())
        text = "build me a portfolio website using Python and HTML"
        d = router.route(text, clf.classify(text), text)
        self.assertEqual(d.kind, "single_tool")
        self.assertTrue(registry.has(d.tool),
                        f"routed to unregistered tool {d.tool!r}")
        self.assertEqual(d.tool, "crown_code")

    def test_evaluator_marks_unknown_tool_failed(self):
        from brain.evaluator import Evaluator
        ev = Evaluator()
        out = Evaluator().evaluate({"ok": False, "error": "Unknown tool: x",
                                    "result": "", "tool": "x"})
        self.assertFalse(out.is_success())


# ── dashboard guard ───────────────────────────────────────────────────────
class TestDashboardGuard(unittest.TestCase):
    def setUp(self):
        try:
            from dashboard.server import DashboardServer, _DEPS_OK
        except Exception as exc:               # pragma: no cover
            self.skipTest(f"dashboard unavailable: {exc}")
        if not _DEPS_OK:
            self.skipTest("fastapi/uvicorn not installed")
        os.environ.pop("KEYSAI_DASHBOARD_TOKEN", None)
        self.server = DashboardServer()

    def test_server_generates_a_random_token(self):
        self.assertTrue(self.server.auth_token)
        self.assertGreaterEqual(len(self.server.auth_token), 16)

    def test_wrong_or_missing_token_is_rejected(self):
        self.assertFalse(self.server._authorized(""))
        self.assertFalse(self.server._authorized("nope"))
        self.assertTrue(self.server._authorized(self.server.auth_token))

    def test_mutating_routes_require_a_token(self):
        from fastapi.testclient import TestClient
        client = TestClient(self.server.app)
        self.assertEqual(client.post("/api/command", json={"text": "hi"}).status_code, 401)
        self.assertEqual(client.post("/api/settings", json={"provider": "gemini"}).status_code, 401)
        self.assertEqual(client.post("/api/settings/reset-key", json={}).status_code, 401)
        self.assertEqual(client.post("/api/google/sign-in").status_code, 401)
        self.assertEqual(client.post("/api/google/switch", json={"account": "x"}).status_code, 401)

    def test_authorised_command_is_accepted(self):
        from fastapi.testclient import TestClient
        client = TestClient(self.server.app)
        r = client.post("/api/command", json={"text": "hello"},
                        headers={"X-KeysAI-Token": self.server.auth_token})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_command_queue_has_one_owner(self):
        self.assertEqual(self.server._command_owner, "dashboard")
        self.server.claim_command_queue("assistant")
        self.assertEqual(self.server._command_owner, "assistant")

    def test_main_claims_the_queue_before_serving(self):
        import inspect
        import main
        src = inspect.getsource(main.KeysAILive.run)
        self.assertIn("claim_command_queue", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
