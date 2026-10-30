"""OpenAI-compatible provider: local reasoning suppression + empty responses.

Regression: local Qwen3 models spent minutes in a hidden reasoning block before
answering structured requests, and an empty completion was handed back to
callers as "" (silently producing empty documents / canned templates).

Run: python -m unittest qa_artifacts.regression_tests.test_openai_compat -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from brain.providers.base import ProviderError  # noqa: E402
from brain.providers.openai_compat import OpenAICompatProvider  # noqa: E402


class FakeResp:
    def __init__(self, content: str = "hello", status_code: int = 200, native: bool = False):
        self._content = content
        self.status_code = status_code
        self._native = native

    def raise_for_status(self):
        pass

    def json(self):
        if self._native:
            return {"message": {"content": self._content}}
        return {"choices": [{"message": {"content": self._content}}]}


class _Recorder:
    """Collect requests while a provider call runs inside the patch."""

    def __init__(self, content="hello", native_status=200, native=True):
        self.calls: list[tuple[str, dict]] = []
        self.content = content
        self.native_status = native_status
        self.native = native

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json))
        return FakeResp(self.content, self.native_status, native=self.native)

    def run(self, provider, prompts):
        with mock.patch("requests.post", side_effect=self):
            return [provider.generate(p) for p in prompts]


class TestNativeOllamaPath(unittest.TestCase):
    def test_local_uses_native_chat_without_thinking(self):
        rec = _Recorder("[]")
        p = OpenAICompatProvider(base_url="http://localhost:11434", model="qwen3:8b")
        rec.run(p, ["Write something"])
        url, payload = rec.calls[0]
        self.assertTrue(url.endswith("/api/chat"), url)
        self.assertFalse(payload["think"], "reasoning must be disabled locally")
        self.assertIn("options", payload)

    def test_native_path_used_for_every_call(self):
        rec = _Recorder("a")
        p = OpenAICompatProvider(base_url="http://localhost:11434", model="qwen3:8b")
        rec.run(p, ["one", "two"])
        self.assertEqual([c[0].rsplit("/api", 1)[-1] for c in rec.calls], ["/chat", "/chat"])
        self.assertTrue(p._native)

    def test_v1_suffix_still_resolves_native_url(self):
        p = OpenAICompatProvider(base_url="http://localhost:11434/v1", model="qwen3:8b")
        self.assertEqual(p._native_url(), "http://localhost:11434/api/chat")

    def test_runtime_without_native_endpoint_falls_back(self):
        """LM Studio / vLLM return 404 for /api/chat -> OpenAI endpoint."""
        calls = []

        def fake_post(url, json=None, headers=None, timeout=None):
            calls.append((url, json))
            if url.endswith("/api/chat"):
                return FakeResp("", status_code=404)
            return FakeResp("fallback answer", native=False)

        p = OpenAICompatProvider(base_url="http://localhost:11434", model="lmstudio-model")
        with mock.patch("requests.post", side_effect=fake_post):
            self.assertEqual(p.generate("hi"), "fallback answer")
        self.assertFalse(p._native)
        self.assertTrue(calls[1][0].endswith("/v1/chat/completions"))

    def test_hosted_endpoint_never_probes_native(self):
        calls = []

        def fake_post(url, json=None, headers=None, timeout=None):
            calls.append(url)
            return FakeResp("ok", native=False)

        p = OpenAICompatProvider(base_url="https://api.openai.com", model="gpt-4o",
                                 api_key="sk-test")
        with mock.patch("requests.post", side_effect=fake_post):
            p.generate("hi")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].endswith("/v1/chat/completions"))


class TestQwenSoftSwitch(unittest.TestCase):
    """Fallback path still silences Qwen3 when the native API is unavailable."""

    def _messages(self, model: str, base_url="http://localhost:11434", prompt="Write something"):
        p = OpenAICompatProvider(base_url=base_url, model=model)
        sent = []

        def fake_post(url, json=None, headers=None, timeout=None):
            if url.endswith("/api/chat"):
                return FakeResp("", status_code=404)
            sent.append(json)
            return FakeResp("ok", native=False)

        with mock.patch("requests.post", side_effect=fake_post):
            p.generate(prompt)
        return sent[0]["messages"][-1]["content"]

    def test_qwen3_local_gets_no_think(self):
        self.assertIn("/no_think", self._messages("qwen3:8b"))

    def test_no_think_added_once(self):
        self.assertEqual(self._messages("qwen3:8b", prompt="already /no_think").count("/no_think"), 1)

    def test_other_models_untouched(self):
        for model in ("llama3.1:8b", "qwen2.5-coder:7b"):
            with self.subTest(model=model):
                self.assertNotIn("/no_think", self._messages(model))

    def test_hosted_endpoint_untouched(self):
        p = OpenAICompatProvider(base_url="https://api.openai.com", model="qwen3:8b",
                                 api_key="sk-test")
        sent = []

        def fake_post(url, json=None, headers=None, timeout=None):
            sent.append(json)
            return FakeResp("ok", native=False)

        with mock.patch("requests.post", side_effect=fake_post):
            p.generate("hi")
        self.assertNotIn("/no_think", sent[0]["messages"][-1]["content"])


class TestEmptyCompletion(unittest.TestCase):
    def test_empty_is_retried_once_then_raises(self):
        calls = []

        def fake_post(url, json=None, headers=None, timeout=None):
            calls.append(url)
            return FakeResp("", native=True)

        p = OpenAICompatProvider(base_url="http://localhost:11434", model="qwen3:8b")
        with mock.patch("requests.post", side_effect=fake_post):
            with self.assertRaises(ProviderError) as ctx:
                p.generate("Write something")
        self.assertEqual(len(calls), 2, "empty completion should be retried once")
        self.assertIn("empty completion", str(ctx.exception))

    def test_empty_hosted_does_not_retry(self):
        calls = []

        def fake_post(url, json=None, headers=None, timeout=None):
            calls.append(url)
            return FakeResp("", native=False)

        p = OpenAICompatProvider(base_url="https://api.openai.com", model="gpt-4o",
                                 api_key="sk-test")
        with mock.patch("requests.post", side_effect=fake_post):
            with self.assertRaises(ProviderError):
                p.generate("hi")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
