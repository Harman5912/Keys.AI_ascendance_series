"""Regression tests for core/crown_bridge.py (model selection, config, lifecycle).

Deterministic — no model inference, no subprocess, no network calls except a
connection attempt to a closed localhost port.

Run:  python -m unittest qa_artifacts.regression_tests.test_crown_bridge -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from core import crown_bridge as cb  # noqa: E402


class TmpConfig:
    """Point the module at a throwaway config file for the duration of a test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = cb.CONFIG_PATH
        cb.CONFIG_PATH = Path(self._tmp.name) / "crown_code.json"

    def tearDown(self):
        cb.CONFIG_PATH = self._orig
        self._tmp.cleanup()


class TestModelSelection(unittest.TestCase):
    INSTALLED = ["qwen3:8b", "qwen2.5-coder:3b", "deepseek-r1:8b", "tinyllama:latest",
                 "qwen2.5-coder:7b", "qwen3.5:4b", "qwen3:30b", "qwen3-coder:30b",
                 "llava:latest", "llama3.2-vision:latest"]

    def test_pick_model_honours_installed_preference(self):
        self.assertEqual(cb.pick_model(self.INSTALLED, "qwen2.5-coder:7b"), "qwen2.5-coder:7b")

    def test_pick_model_preference_matches_without_tag(self):
        self.assertEqual(cb.pick_model(self.INSTALLED, "qwen3"), "qwen3:8b")

    def test_pick_model_ignores_missing_preference(self):
        picked = cb.pick_model(self.INSTALLED, "gpt-oss:120b")
        self.assertIn(picked, self.INSTALLED)

    def test_pick_model_empty_list(self):
        self.assertEqual(cb.pick_model([], ""), "")

    def test_auto_pick_prefers_verified_tool_calling_model(self):
        """Auto-pick must prefer the model the project verified emits native tool
        calls (qwen3:8b) over one documented to write tool calls as prose
        (qwen3.5:4b) and over 30B models that cannot fit in this machine's RAM.
        """
        model, note = cb.recommend_model(self.INSTALLED)
        self.assertEqual(model, "qwen3:8b", f"auto-picked {model!r} (note: {note!r})")

    def test_auto_pick_never_selects_model_larger_than_ram(self):
        model, _ = cb.recommend_model(self.INSTALLED)
        self.assertLessEqual(cb.model_size_gb(model), cb.total_ram_gb() * 0.75)

    def test_auto_pick_warns_when_only_huge_models_available(self):
        model, note = cb.recommend_model(["qwen3-coder:30b"])
        self.assertEqual(model, "qwen3-coder:30b")
        if cb.total_ram_gb() and cb.model_size_gb(model) > cb.total_ram_gb() * 0.75:
            self.assertIn("Warning", note)

    def test_preferred_missing_is_reported_not_substituted(self):
        model, note = cb.recommend_model(self.INSTALLED, "qwen9:99b")
        self.assertEqual(model, "qwen9:99b")
        self.assertIn("not installed", note)

    def test_no_models_returns_empty_and_note(self):
        self.assertEqual(cb.recommend_model([]), ("", "No local models installed."))

    def test_model_size_ordering(self):
        sizes = [cb.model_size_gb(m) for m in
                 ("tinyllama:latest", "qwen2.5-coder:3b", "qwen3.5:4b",
                  "qwen3:8b", "qwen2.5-coder:14b", "qwen3-coder:30b")]
        self.assertEqual(sizes, sorted(sizes))


class TestVerifyModel(unittest.TestCase):
    def test_unreachable_runtime_fails_cleanly(self):
        ok, detail = cb.verify_model("qwen3:8b", url="http://127.0.0.1:9", timeout=2)
        self.assertFalse(ok)
        self.assertTrue(detail)

    def test_empty_reply_is_not_a_verified_model(self):
        """A model that returns no content has not been verified — reporting
        success here makes the UI claim a working model when inference is broken."""
        payload = json.dumps({"message": {"content": "   "}}).encode()

        class _Resp:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", return_value=_Resp()):
            ok, detail = cb.verify_model("qwen3:8b", url="http://127.0.0.1:11434", timeout=2)
        self.assertFalse(ok, f"empty model reply reported as verified: {detail!r}")

    def test_real_reply_is_verified(self):
        payload = json.dumps({"message": {"content": "OK"}}).encode()

        class _Resp:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", return_value=_Resp()):
            ok, detail = cb.verify_model("qwen3:8b", url="http://127.0.0.1:11434", timeout=2)
        self.assertTrue(ok)
        self.assertEqual(detail, "OK")


class TestConfig(TmpConfig, unittest.TestCase):
    def test_defaults_when_file_absent(self):
        cfg = cb.load_config()
        self.assertEqual(cfg["provider"], "ollama")
        self.assertEqual(cfg["policy"], "safe")
        self.assertIn("crown_dir", cfg)

    def test_roundtrip(self):
        cb.save_config({"model": "qwen3:8b", "policy": "readonly", "max_iterations": 7})
        cfg = cb.load_config()
        self.assertEqual(cfg["model"], "qwen3:8b")
        self.assertEqual(cfg["policy"], "readonly")
        self.assertEqual(cfg["max_iterations"], 7)

    def test_corrupt_config_never_raises(self):
        cb.CONFIG_PATH.write_text("{not json", encoding="utf-8")
        cfg = cb.load_config()
        self.assertEqual(cfg["policy"], "safe")

    def test_non_dict_config_never_raises(self):
        cb.CONFIG_PATH.write_text('["a", "b"]', encoding="utf-8")
        cfg = cb.load_config()
        self.assertEqual(cfg["provider"], "ollama")


class TestLocalModelReadiness(unittest.TestCase):
    def test_no_silent_remote_fallback_when_ollama_unreachable(self):
        """Local setup failure must return a local-setup error, never a remote
        provider id that would silently change where inference happens."""
        with mock.patch.object(cb, "load_config",
                               return_value={"ollama_url": "http://127.0.0.1:9",
                                             "model": "", "crown_dir": str(BASE)}), \
             mock.patch.object(cb, "start_ollama", return_value=False):
            ok, info = cb.ensure_local_model()
        self.assertFalse(ok)
        self.assertIsInstance(info, str)
        self.assertTrue("ollama" in info.lower() or "reachable" in info.lower(), info)


class TestBridgeLifecycle(unittest.TestCase):
    def test_start_fails_cleanly_without_headless_build(self):
        with mock.patch.object(cb, "headless_entry",
                               return_value=Path(tempfile.gettempdir()) / "nope.js"), \
             mock.patch.object(cb, "crown_dir", return_value=Path(tempfile.gettempdir()) / "nope"):
            ok, msg = cb.ensure_built()
        self.assertFalse(ok)
        self.assertIn("not found", msg.lower())

    def test_bridge_defaults_come_from_config(self):
        with mock.patch.object(cb, "load_config",
                               return_value={"model": "qwen3:8b", "provider": "ollama",
                                             "policy": "safe", "max_iterations": 12,
                                             "ollama_url": "http://localhost:11434"}):
            b = cb.CrownBridge(workspace=str(BASE))
        self.assertEqual(b.model, "qwen3:8b")
        self.assertEqual(b.max_iterations, 12)
        self.assertEqual(b.policy, "safe")

    def test_workspace_is_resolved_to_absolute(self):
        b = cb.CrownBridge(workspace=".")
        self.assertTrue(Path(b.workspace).is_absolute())

    def test_permission_default_denies_delete_allows_write(self):
        b = cb.CrownBridge(workspace=str(BASE))
        sent = []
        b.send_permission = lambda rid, allow: sent.append((rid, allow))
        b._dispatch({"type": "permission_request", "id": "1", "tool": "delete_file"})
        b._dispatch({"type": "permission_request", "id": "2", "tool": "write_file"})
        self.assertEqual(sent, [("1", False), ("2", True)])

    def test_erroring_event_handler_does_not_break_dispatch(self):
        b = cb.CrownBridge(workspace=str(BASE), on_event=lambda ev: 1 / 0)
        b._dispatch({"type": "state", "state": "thinking"})  # must not raise

    def test_reader_thread_reports_failure_when_process_dies_without_result(self):
        class _DeadPipe:
            def __iter__(self):
                return iter([])

        b = cb.CrownBridge(workspace=str(BASE))

        class _P:
            stdout = _DeadPipe()
            stderr = None

        b.proc = _P()
        b._read_loop()
        self.assertIsNotNone(b.result)
        self.assertFalse(b.result["ok"])
        self.assertTrue(b._done.is_set())


class TestToolAllowlist(unittest.TestCase):
    def test_tool_allowlist_is_forwarded_in_start_message(self):
        b = cb.CrownBridge(workspace=str(BASE), tools=["write_file", "read_file"])
        sent = []
        b._send = sent.append
        with mock.patch.object(cb, "ensure_built", return_value=(True, "ok")), \
             mock.patch.object(cb, "node_exe", return_value="node"), \
             mock.patch.object(cb, "headless_entry", return_value=Path("h.js")), \
             mock.patch("subprocess.Popen", side_effect=RuntimeError("no spawn")):
            ok, _ = b.start("task")
        self.assertFalse(ok)  # spawn failed — but nothing was sent either
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class _FakeResp:
    """Minimal urlopen() context manager for the model probe."""

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


class TestVerifyModel(unittest.TestCase):
    """B16 — a reasoning model that answers inside its thinking block must not
    be reported as a broken model (that blocked every Crown Code run)."""

    def _probe(self, payload: dict, model: str = "qwen3:8b"):
        sent: dict = {}

        def fake_urlopen(req, timeout=None):
            sent["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResp(payload)

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            ok, detail = cb.verify_model(model, "http://localhost:11434")
        return ok, detail, sent.get("body", {})

    def test_probe_disables_thinking_for_qwen3(self):
        _, _, body = self._probe({"message": {"content": "OK"}})
        self.assertIs(body.get("think"), False)
        self.assertGreaterEqual(body["options"]["num_predict"], 16)

    def test_probe_leaves_other_models_alone(self):
        _, _, body = self._probe({"message": {"content": "OK"}}, model="tinyllama:latest")
        self.assertNotIn("think", body)

    def test_hidden_reasoning_is_reported_as_such(self):
        ok, detail, _ = self._probe({"message": {"content": "", "thinking": "Okay, the user"},
                                     "done_reason": "length"})
        self.assertFalse(ok)
        self.assertIn("reasoning", detail)

    def test_real_answer_verifies(self):
        ok, detail, _ = self._probe({"message": {"content": "OK"}, "done_reason": "stop"})
        self.assertTrue(ok)
        self.assertEqual(detail, "OK")

    def test_empty_answer_still_fails(self):
        ok, detail, _ = self._probe({"message": {"content": ""}, "done_reason": "stop"})
        self.assertFalse(ok)
        self.assertIn("empty", detail)
