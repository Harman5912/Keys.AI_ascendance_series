"""Provider abstraction, streaming and timeout regression tests.

Covers the contract every model provider must honour, without a network call:

* the factory never raises and always returns a usable provider;
* a retryable primary failure moves to a backup key, a non-retryable one does not;
* `stream()` delivers the same text as `generate()` and reports real chunks;
* every provider call is bounded by the configured timeout, and a timeout is
  normalised to ProviderError (never a raw `requests` exception);
* a bridge that never answers is reported as a failed build, not as success.

Run: python -m unittest qa_artifacts.regression_tests.test_provider_streaming -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from brain.providers import get_provider  # noqa: E402
from brain.providers.base import (FallbackProvider, LLMProvider,  # noqa: E402
                                  ProviderError, _chunk_text)
from brain.providers.gemini import GeminiProvider  # noqa: E402
from brain.providers.openai_compat import OpenAICompatProvider  # noqa: E402


# ── fakes ────────────────────────────────────────────────────────────────────

class StubProvider(LLMProvider):
    """A provider whose every call is scripted."""

    name = "stub"

    def __init__(self, text="hello world", error: Exception | None = None,
                 name: str = "stub"):
        self.name = name
        self._text = text
        self._error = error
        self.calls: list[str] = []
        self.stream_tokens: list[str] = []

    def generate(self, prompt, system=None, temperature=0.2, max_tokens=None):
        self.calls.append("generate")
        if self._error:
            raise self._error
        return self._text

    def stream(self, prompt, system=None, on_token=None):
        self.calls.append("stream")
        if self._error:
            raise self._error
        if on_token:
            for piece in self._text.split():
                self.stream_tokens.append(piece)
                on_token(piece)
        return self._text

    def structured_output(self, prompt, system=None, temperature=0.0):
        self.calls.append("structured_output")
        if self._error:
            raise self._error
        return {"ok": True}


class StubResp:
    def __init__(self, payload=None, lines=None, status_code=200):
        self._payload = payload or {}
        self._lines = lines or []
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)


# ── factory ──────────────────────────────────────────────────────────────────

class FactoryTest(unittest.TestCase):
    def setUp(self):
        # Never read the user's real keys or backup rotation in a test.
        self._p = mock.patch("core.api_config.get_backup_api_keys", return_value=[])
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_unknown_provider_falls_back_to_gemini(self):
        provider = get_provider(api_config={"llm_provider": "does-not-exist"})
        self.assertIsInstance(provider, GeminiProvider)

    def test_cloud_provider_gets_a_bounded_timeout(self):
        provider = get_provider(api_config={"llm_provider": "openai",
                                            "openai_api_key": "k"})
        self.assertIsInstance(provider, OpenAICompatProvider)
        self.assertEqual(provider.timeout, 180.0,
                         "a hung cloud call must not hold the chat")

    def test_local_provider_gets_the_shorter_timeout(self):
        provider = get_provider(api_config={"llm_provider": "ollama",
                                            "llm_model": "qwen3:8b"})
        self.assertEqual(provider.timeout, 120.0)

    def test_backup_keys_become_a_fallback_provider(self):
        with mock.patch("core.api_config.get_backup_api_keys",
                        return_value=["key-b", "key-c"]):
            provider = get_provider(api_config={"llm_provider": "openai",
                                                "openai_api_key": "key-a"})
        self.assertIsInstance(provider, FallbackProvider)
        self.assertEqual(provider.backup_count, 2)
        self.assertFalse(provider.is_using_backup)

    def test_configured_local_model_is_the_last_resort(self):
        provider = get_provider(
            cfg={"provider": "gemini"},
            api_config={"llm_provider": "ollama", "gemini_api_key": "k",
                        "llm_model": "qwen3:8b",
                        "llm_url": "http://localhost:11434"})
        self.assertIsInstance(provider, FallbackProvider)
        self.assertEqual(provider.backup_count, 1)


# ── fallback ─────────────────────────────────────────────────────────────────

class FallbackTest(unittest.TestCase):
    def _fallback(self, primary, *backups):
        return FallbackProvider(primary, list(backups), "test")

    def test_retryable_failure_uses_the_backup(self):
        primary = StubProvider(error=ProviderError("429 RESOURCE_EXHAUSTED"))
        backup = StubProvider(text="from backup", name="backup")
        provider = self._fallback(primary, backup)
        self.assertEqual(provider.generate("hi"), "from backup")
        self.assertEqual(backup.calls, ["generate"])
        self.assertTrue(provider.is_using_backup)
        self.assertEqual(provider.active_backup_index, 0)

    def test_invalid_key_payload_is_retryable(self):
        primary = StubProvider(error=ProviderError(
            "400 INVALID_ARGUMENT: API key not valid. Please pass a valid API key."))
        backup = StubProvider(text="ok", name="backup")
        self.assertEqual(self._fallback(primary, backup).generate("hi"), "ok")

    def test_non_retryable_failure_does_not_touch_the_backup(self):
        primary = StubProvider(error=ProviderError("prompt is malformed"))
        backup = StubProvider(text="should not run", name="backup")
        with self.assertRaises(ProviderError):
            self._fallback(primary, backup).generate("hi")
        self.assertEqual(backup.calls, [])
        self.assertFalse(self._fallback(primary, backup).is_using_backup)

    def test_all_backups_exhausted_raises_the_primary_error(self):
        primary = StubProvider(error=ProviderError("quota exceeded"))
        b1 = StubProvider(error=ProviderError("quota exceeded"), name="b1")
        b2 = StubProvider(error=ProviderError("still quota"), name="b2")
        provider = self._fallback(primary, b1, b2)
        with self.assertRaises(ProviderError) as ctx:
            provider.generate("hi")
        self.assertIn("quota exceeded", str(ctx.exception))
        self.assertEqual([b1.calls, b2.calls], [["generate"], ["generate"]])
        self.assertFalse(provider.is_using_backup)

    def test_stream_falls_back_too(self):
        primary = StubProvider(error=ProviderError("rate limit reached"))
        backup = StubProvider(text="one two", name="backup")
        seen: list[str] = []
        out = self._fallback(primary, backup).stream("hi", on_token=seen.append)
        self.assertEqual(out, "one two")
        self.assertEqual(seen, ["one", "two"])
        self.assertEqual(backup.calls, ["stream"])

    def test_available_delegates_to_the_primary(self):
        class Down(StubProvider):
            def available(self):
                return False

        provider = self._fallback(Down(), StubProvider(name="b"))
        self.assertFalse(provider.available())


# ── streaming ────────────────────────────────────────────────────────────────

class PlainProvider(LLMProvider):
    """Implements only the abstract methods — this is the default stream()."""

    name = "plain"

    def __init__(self, text: str):
        self._text = text
        self.generate_calls = 0

    def generate(self, prompt, system=None, temperature=0.2, max_tokens=None):
        self.generate_calls += 1
        return self._text

    def structured_output(self, prompt, system=None, temperature=0.0):
        return None


class BaseStreamTest(unittest.TestCase):
    def test_default_stream_chunks_and_returns_the_full_text(self):
        provider = PlainProvider(text="a" * 60)
        chunks: list[str] = []
        out = provider.stream("hi", on_token=chunks.append)
        self.assertEqual(out, "a" * 60)
        self.assertEqual("".join(chunks), out)
        self.assertTrue(all(chunks), "no empty chunk may be reported")
        self.assertTrue(all(len(c) <= 24 for c in chunks), "chunks must stay small")
        self.assertEqual(provider.generate_calls, 1, "one model call, not one per chunk")

    def test_default_stream_without_a_callback_still_returns_text(self):
        self.assertEqual(PlainProvider(text="plain").stream("hi"), "plain")

    def test_chunk_text_covers_every_character_once(self):
        text = "abcdefghij"
        for size in (1, 3, 4, 10, 25):
            pieces = list(_chunk_text(text, size))
            self.assertEqual("".join(pieces), text)
            self.assertTrue(all(pieces))
            self.assertTrue(all(len(p) <= size for p in pieces))

    def test_empty_text_streams_no_chunks(self):
        self.assertEqual(list(_chunk_text("", 8)), [])


class OpenAICompatStreamTest(unittest.TestCase):
    def _native_provider(self):
        return OpenAICompatProvider(base_url="http://localhost:11434",
                                    model="qwen3:8b")

    def test_native_stream_reports_each_piece_and_stops_at_done(self):
        lines = [
            '{"message": {"content": "Hel"}, "done": false}',
            '{"message": {"content": "lo"}, "done": false}',
            'not json at all',
            '{"message": {"content": ""}, "done": false}',
            '{"message": {"content": "!"}, "done": true}',
            '{"message": {"content": "IGNORED"}, "done": false}',
        ]
        seen: list[str] = []
        with mock.patch("requests.post", return_value=StubResp(lines=lines)) as post:
            out = self._native_provider().stream("hi", on_token=seen.append)
        self.assertEqual(out, "Hello!")
        self.assertEqual(seen, ["Hel", "lo", "!"])
        self.assertFalse(post.call_args.kwargs["json"]["stream"] is False)

    def test_a_raising_callback_does_not_break_the_stream(self):
        lines = ['{"message": {"content": "a"}, "done": false}',
                 '{"message": {"content": "b"}, "done": true}']

        def boom(_):
            raise RuntimeError("UI died")

        with mock.patch("requests.post", return_value=StubResp(lines=lines)):
            out = self._native_provider().stream("hi", on_token=boom)
        self.assertEqual(out, "ab")

    def test_native_404_falls_back_to_a_blocking_call(self):
        provider = self._native_provider()
        seen: list[str] = []
        payload = {"choices": [{"message": {"content": "blocking answer"}}]}
        # First call: the native stream endpoint does not exist (404). Second
        # call: the OpenAI-compatible endpoint answers, so the turn still works.
        with mock.patch("requests.post", side_effect=[StubResp(status_code=404),
                                                      StubResp(payload=payload)]):
            out = provider.stream("hi", on_token=seen.append)
        self.assertFalse(provider._native, "404 must disable the native path")
        self.assertEqual(out, "blocking answer")
        self.assertEqual(seen, ["blocking answer"])

    def test_remote_provider_stream_delegates_to_generate(self):
        provider = OpenAICompatProvider(base_url="https://api.example.com/v1",
                                        model="m", api_key="k")
        payload = {"choices": [{"message": {"content": "remote text"}}]}
        seen: list[str] = []
        with mock.patch("requests.post", return_value=StubResp(payload=payload)):
            out = provider.stream("hi", on_token=seen.append)
        self.assertEqual(out, "remote text")
        self.assertEqual(seen, ["remote text"])


# ── timeouts and error normalisation ─────────────────────────────────────────

class TimeoutTest(unittest.TestCase):
    def test_native_call_passes_read_timeout_and_connect_timeout(self):
        provider = OpenAICompatProvider(base_url="http://localhost:11434",
                                        model="qwen3:8b", timeout=42.0)
        with mock.patch("requests.post",
                        return_value=StubResp(payload={"message": {"content": "x"}})) as post:
            provider.generate("hi")
        self.assertEqual(post.call_args.kwargs["timeout"], (10, 42.0))

    def test_openai_call_passes_the_configured_timeout(self):
        provider = OpenAICompatProvider(base_url="https://api.example.com/v1",
                                        model="m", api_key="k", timeout=37.0)
        payload = {"choices": [{"message": {"content": "x"}}]}
        with mock.patch("requests.post", return_value=StubResp(payload=payload)) as post:
            provider.generate("hi")
        self.assertEqual(post.call_args.kwargs["timeout"], 37.0)

    def test_dropped_native_call_is_a_provider_error(self):
        provider = OpenAICompatProvider(base_url="http://localhost:11434",
                                        model="qwen3:8b")
        with mock.patch("requests.post", side_effect=TimeoutError("read timed out")):
            with self.assertRaises(ProviderError) as ctx:
                provider.generate("hi")
        self.assertIn("localhost:11434", str(ctx.exception))

    def test_dropped_cloud_call_is_a_provider_error_naming_the_endpoint(self):
        provider = OpenAICompatProvider(base_url="https://api.example.com/v1",
                                        model="m", api_key="k")
        with mock.patch("requests.post", side_effect=TimeoutError("timed out")):
            with self.assertRaises(ProviderError) as ctx:
                provider.generate("hi")
        self.assertIn("api.example.com", str(ctx.exception))

    def test_unparseable_structured_output_returns_none(self):
        provider = OpenAICompatProvider(base_url="https://api.example.com/v1",
                                        model="m", api_key="k")
        payload = {"choices": [{"message": {"content": "I cannot do JSON, sorry"}}]}
        with mock.patch("requests.post", return_value=StubResp(payload=payload)):
            self.assertIsNone(provider.structured_output("give me json"))

    def test_cloud_empty_completion_is_an_error_not_an_empty_string(self):
        provider = OpenAICompatProvider(base_url="https://api.example.com/v1",
                                        model="m", api_key="k")
        payload = {"choices": [{"message": {"content": ""}}]}
        with mock.patch("requests.post", return_value=StubResp(payload=payload)):
            with self.assertRaises(ProviderError):
                provider.generate("hi")


# ── bridge timeout reaches the user as a failure ─────────────────────────────

class BridgeTimeoutTest(unittest.TestCase):
    """A bridge that never reports a result must not become a 'done' build."""

    class FakeBridge:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.stopped = 0

        def start(self, task):
            return True, "started"

        def wait(self, timeout=None):
            self.timeout = timeout
            return None          # the model never answered in time

        def stop(self):
            self.stopped += 1

    def test_timeout_is_reported_as_a_failure(self):
        from actions import crown_code as cc
        from core import crown_jobs

        job = crown_jobs.BuildJob(kind="code", brief="x", workspace="", model="m")
        with mock.patch.object(cc, "CrownBridge", self.FakeBridge):
            result = cc._run_bridge(job, "build it", Path("."), "m", "ollama",
                                    "safe", 5, None, max_iterations=1)
        self.assertFalse(result.get("ok"))
        self.assertTrue(result.get("error"), "a timed-out build needs a reason")

    def test_bridge_is_stopped_after_the_timeout(self):
        from actions import crown_code as cc
        from core import crown_jobs

        created: list[BridgeTimeoutTest.FakeBridge] = []

        def factory(**kwargs):
            bridge = self.FakeBridge(**kwargs)
            created.append(bridge)
            return bridge

        job = crown_jobs.BuildJob(kind="code", brief="x", workspace="", model="m")
        with mock.patch.object(cc, "CrownBridge", side_effect=factory):
            cc._run_bridge(job, "build it", Path("."), "m", "ollama", "safe", 5, None)
        self.assertTrue(created)
        self.assertGreaterEqual(created[0].stopped, 1,
                                "the subprocess must be killed, not leaked")


if __name__ == "__main__":
    unittest.main()
