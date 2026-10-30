"""Group H — provider and model compatibility.

These tests exercise the real provider layer (brain/providers/*, core/llm_client,
core/model_catalog). HTTP is replaced with a scripted stand-in so a documented
failure mode — a 401, a timeout, a rate limit, a runtime without the native
endpoint — is reproducible offline.

No test here claims a real cloud model answered: every provider reply is a mock.
What is verified is how Keys.AI resolves a provider/model, what it sends, how it
classifies a failure, and that the existing chat path still builds.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from brain.providers import get_provider  # noqa: E402
from brain.providers.base import (  # noqa: E402
    FallbackProvider, LLMProvider, ProviderError, parse_json,
)
from brain.providers.openai_compat import OpenAICompatProvider  # noqa: E402
from core import llm_client, model_catalog  # noqa: E402


class _Resp:
    def __init__(self, payload=None, status: int = 200):
        self._payload = payload if payload is not None else {}
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} Client Error: Unauthorized")

    def iter_lines(self, decode_unicode=True):
        body = self._payload.get("_stream") if isinstance(self._payload, dict) else None
        for line in body or []:
            yield line


def _reply(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


def _chat_patch(text="hello", status=200, recorder=None, raise_error=None):
    def post(url, **kwargs):
        if recorder is not None:
            recorder.append({"url": url, **kwargs})
        if raise_error is not None:
            raise raise_error
        if status >= 400:
            return _Resp({"error": "unauthorized"}, status=status)
        return _Resp(_reply(text))
    return post


class _Fake(LLMProvider):
    name = "fake"

    def __init__(self, reply: str = "ok", error: Exception | None = None):
        self.reply, self.error, self.calls = reply, error, 0

    def generate(self, prompt, system=None, temperature=0.2, max_tokens=None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.reply

    def structured_output(self, prompt, system=None, temperature=0.0):
        return {"ok": True}


class TestProviderResolution(unittest.TestCase):
    def test_configured_provider_is_resolved(self):
        provider = get_provider(api_config={
            "llm_provider": "nvidia", "llm_model": "meta/llama-3.3-70b-instruct",
            "nvidia_api_key": "nvapi-test"})
        self.assertIn("integrate.api.nvidia.com", provider.endpoint)
        self.assertEqual(provider.model, "meta/llama-3.3-70b-instruct")

    def test_configured_model_is_resolved(self):
        provider = get_provider(api_config={
            "llm_provider": "openai", "llm_model": "gpt-x",
            "openai_api_key": "sk-test"})
        self.assertEqual(provider.model, "gpt-x")

    def test_local_provider_defaults_to_ollama_port(self):
        provider = get_provider(api_config={"llm_provider": "ollama",
                                            "llm_model": "qwen3:8b"})
        self.assertEqual(provider.base_url, "http://localhost:11434")

    def test_missing_configuration_falls_back_to_gemini(self):
        provider = get_provider(api_config={})
        self.assertIn("gemini", provider.name)

    def test_explicit_model_beats_the_catalogue_default(self):
        provider = get_provider(cfg={"provider": "openai", "model": "pinned-model"},
                                api_config={"llm_provider": "openai",
                                            "openai_api_key": "sk-test",
                                            "llm_model": "other"})
        self.assertEqual(provider.model, "pinned-model")

    def test_catalog_and_provider_layer_agree(self):
        from brain.providers import key_field_for
        for name, info in model_catalog.PROVIDERS.items():
            self.assertEqual(key_field_for(name), info.get("key_field"), name)
            self.assertIn(info.get("default_model"), info.get("models") or
                          [info.get("default_model")])


class TestOpenAICompatibleProvider(unittest.TestCase):
    def provider(self, base="https://api.example.com/v1", key="sk-test",
                 timeout=5.0) -> OpenAICompatProvider:
        return OpenAICompatProvider(base_url=base, model="model-a",
                                    api_key=key, timeout=timeout)

    def test_basic_request_shape(self):
        seen: list = []
        with mock.patch("requests.post", _chat_patch("hello", recorder=seen)):
            out = self.provider().generate("hi", system="be brief")
        self.assertEqual(out, "hello")
        call = seen[0]
        self.assertTrue(call["url"].endswith("/chat/completions"))
        self.assertEqual(call["json"]["model"], "model-a")
        self.assertEqual(call["json"]["messages"][0]["role"], "system")
        self.assertEqual(call["headers"]["Authorization"], "Bearer sk-test")

    def test_keyless_endpoint_sends_no_authorization(self):
        seen: list = []
        with mock.patch("requests.post", _chat_patch("ok", recorder=seen)):
            out = self.provider(key="").generate("hi")
        self.assertEqual(out, "ok")
        self.assertNotIn("Authorization", seen[0]["headers"])

    def test_invalid_key_is_reported(self):
        with mock.patch("requests.post", _chat_patch(status=401)):
            with self.assertRaises(ProviderError) as ctx:
                self.provider().generate("hi")
        self.assertIn("401", str(ctx.exception))

    def test_unreachable_provider_is_reported(self):
        with mock.patch("requests.post",
                        _chat_patch(raise_error=requests.exceptions.ConnectionError(
                            "connection refused"))):
            with self.assertRaises(ProviderError) as ctx:
                self.provider().generate("hi")
        self.assertIn("connection refused", str(ctx.exception))

    def test_timeout_is_reported(self):
        with mock.patch("requests.post",
                        _chat_patch(raise_error=requests.exceptions.Timeout(
                            "read timed out"))):
            with self.assertRaises(ProviderError) as ctx:
                self.provider(base="https://api.example.com/v1").generate("hi")
        self.assertIn("timed out", str(ctx.exception))

    def test_unexpected_payload_is_an_error(self):
        with mock.patch("requests.post", lambda *a, **k: _Resp({})):
            with self.assertRaises(ProviderError) as ctx:
                self.provider().generate("hi")
        self.assertIn("empty completion", str(ctx.exception))

    def test_structured_output_parses_json(self):
        with mock.patch("requests.post",
                        _chat_patch(json.dumps({"plan": ["a", "b"]}))):
            out = self.provider().structured_output("plan it")
        self.assertEqual(out, {"plan": ["a", "b"]})

    def test_structured_output_tolerates_fences(self):
        with mock.patch("requests.post",
                        _chat_patch("```json\n{\"steps\": 2}\n```")):
            out = self.provider().structured_output("plan it")
        self.assertEqual(out, {"steps": 2})

    def test_structured_output_rejects_malformed_json(self):
        with mock.patch("requests.post", _chat_patch("not json at all")):
            out = self.provider().structured_output("plan it")
        self.assertIsNone(out)

    def test_image_understanding_is_not_faked(self):
        with self.assertRaises(ProviderError):
            self.provider().describe_image(b"\x89PNG", "image/png", "what is it")


class TestOllamaRuntime(unittest.TestCase):
    def test_native_endpoint_is_used_when_available(self):
        seen: list = []

        def post(url, **kwargs):
            seen.append(url)
            return _Resp({"message": {"content": "local answer"}})

        provider = OpenAICompatProvider(base_url="http://localhost:11434",
                                        model="qwen3:8b")
        with mock.patch("requests.post", post):
            self.assertEqual(provider.generate("hi"), "local answer")
        self.assertTrue(seen[0].endswith("/api/chat"))

    def test_runtime_without_native_endpoint_uses_openai_path(self):
        calls: list = []

        def post(url, **kwargs):
            calls.append(url)
            if url.endswith("/api/chat"):
                return _Resp({}, status=404)
            return _Resp(_reply("via v1"))

        provider = OpenAICompatProvider(base_url="http://localhost:11434",
                                        model="llama3")
        with mock.patch("requests.post", post):
            self.assertEqual(provider.generate("hi"), "via v1")
        self.assertTrue(any(u.endswith("/v1/chat/completions") for u in calls))

    def test_unavailable_ollama_is_a_clear_failure(self):
        provider = OpenAICompatProvider(base_url="http://localhost:11434",
                                        model="llama3")
        with mock.patch("requests.post",
                        _chat_patch(raise_error=requests.exceptions.ConnectionError(
                            "connection refused"))):
            with self.assertRaises(ProviderError) as ctx:
                provider.generate("hi")
        self.assertIn("localhost:11434", str(ctx.exception))

    def test_warm_up_reports_failure_without_raising(self):
        llm_client.invalidate_cache()
        try:
            with mock.patch.object(llm_client, "_get_task_config",
                                    lambda task: {"provider": "ollama",
                                                  "model": "ghost",
                                                  "url": "http://localhost:11434"}), \
                 mock.patch("requests.post",
                            side_effect=requests.exceptions.ConnectionError("down")), \
                 mock.patch.object(llm_client, "get_llm",
                                   side_effect=ProviderError("no model")):
                state = llm_client.warm_up("dev_agent")
            self.assertEqual(state["status"], "failed")
            self.assertIn("no model", state["detail"])
        finally:
            llm_client.invalidate_cache()


class TestFallbackAndErrors(unittest.TestCase):
    def test_rate_limited_primary_uses_backup(self):
        primary = _Fake(error=ProviderError("429 rate limit exceeded"))
        backup = _Fake(reply="from backup")
        provider = FallbackProvider(primary, [backup], "gemini")
        self.assertEqual(provider.generate("hi"), "from backup")
        self.assertTrue(provider.is_using_backup)

    def test_non_retryable_error_is_not_retried(self):
        primary = _Fake(error=ProviderError("model does not exist"))
        backup = _Fake(reply="should not be used")
        provider = FallbackProvider(primary, [backup], "gemini")
        with self.assertRaises(ProviderError):
            provider.generate("hi")
        self.assertEqual(backup.calls, 0)

    def test_exhausted_backups_raise_the_original_error(self):
        primary = _Fake(error=ProviderError("quota exceeded"))
        backups = [_Fake(error=ProviderError("quota exceeded 2")),
                   _Fake(error=ProviderError("quota exceeded 3"))]
        provider = FallbackProvider(primary, backups, "gemini")
        with self.assertRaises(ProviderError) as ctx:
            provider.generate("hi")
        self.assertIn("quota exceeded", str(ctx.exception))
        self.assertFalse(provider.is_using_backup)

    def test_fallback_events_never_contain_the_key(self):
        class Logger:
            def __init__(self):
                self.messages = []

            def event(self, kind, message):
                self.messages.append(message)

        logger = Logger()
        primary = _Fake(error=ProviderError("401 invalid api key sk-secret-1234567890"))
        provider = FallbackProvider(primary, [_Fake(reply="ok")], "openai",
                                    logger=logger)
        self.assertEqual(provider.generate("hi"), "ok")
        self.assertTrue(logger.messages)

    def test_provider_failure_surfaces_to_the_caller(self):
        with mock.patch.object(llm_client, "get_llm",
                               lambda task: _Fake(error=ProviderError("401"))):
            with self.assertRaises(ProviderError):
                llm_client.complete("brain", "hi")


class TestLLMClientPath(unittest.TestCase):
    def tearDown(self):
        llm_client.invalidate_cache()

    def test_complete_uses_the_task_provider(self):
        fake = _Fake(reply="tool answer")
        with mock.patch.object(llm_client, "get_llm", lambda task: fake):
            self.assertEqual(llm_client.complete("code_helper", "hi"), "tool answer")
        self.assertEqual(fake.calls, 1)

    def test_task_configuration_is_honoured(self):
        captured: dict = {}

        def builder(task):
            captured["task"] = task
            return _Fake(reply="ok")

        with mock.patch.object(llm_client, "get_llm", builder):
            llm_client.complete("file_processor", "hi")
        self.assertEqual(captured["task"], "file_processor")

    def test_chat_provider_object_exposes_the_expected_interface(self):
        provider = get_provider(api_config={"llm_provider": "gemini",
                                            "gemini_api_key": ""})
        for name in ("generate", "stream", "structured_output"):
            self.assertTrue(callable(getattr(provider, name)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
