"""Provider fallback — the chat path must never go silent on a quota outage.

Defect being locked down (Phase 2, D-006): config/brain.json pins the primary
provider to the Gemini free tier (5 requests/minute). Under burst use that
returns 429 RESOURCE_EXHAUSTED; ReasoningEngine.answer() swallowed the error
and the user received an EMPTY reply. The app already has a local Ollama model
configured (api_keys.json llm_provider=ollama), but it was never part of the
brain's provider chain.

Now get_provider() appends that local model as the last backup, so a cloud
quota outage degrades to a slower answer instead of no answer.

Run:  python -m unittest qa_artifacts.regression_tests.test_provider_fallback -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from brain.providers import FallbackProvider, get_provider  # noqa: E402
from brain.providers.base import LLMProvider, ProviderError  # noqa: E402


class _QuotaBlownProvider(LLMProvider):
    """Primary that behaves like the Gemini free tier at its limit."""

    name = "gemini-quota-blown"

    def __init__(self, message: str = "429 RESOURCE_EXHAUSTED: quota exceeded"):
        self.message = message
        self.calls = 0

    def generate(self, prompt, system=None, temperature=0.2, max_tokens=None):
        self.calls += 1
        raise ProviderError(self.message)

    def structured_output(self, prompt, system=None, temperature=0.0):
        raise ProviderError(self.message)


class _LocalProvider(LLMProvider):
    """Stand-in for the local Ollama model."""

    name = "local"

    def __init__(self, answer: str = "answer from the local model",
                 fail: bool = False):
        self.answer = answer
        self.fail = fail
        self.calls = 0

    def generate(self, prompt, system=None, temperature=0.2, max_tokens=None):
        self.calls += 1
        if self.fail:
            raise ProviderError("ollama not reachable")
        return self.answer

    def structured_output(self, prompt, system=None, temperature=0.0):
        if self.fail:
            raise ProviderError("ollama not reachable")
        return {"ok": True}


class WiringTest(unittest.TestCase):
    """get_provider must attach the configured local model as a backup."""

    def test_local_ollama_model_is_appended_for_a_cloud_primary(self):
        provider = get_provider(
            cfg={"provider": "gemini", "model": "gemini-2.5-flash"},
            api_config={"llm_provider": "ollama", "llm_model": "qwen3:8b"})
        self.assertIsInstance(provider, FallbackProvider)
        self.assertEqual(len(provider._backups), 1)
        local = provider._backups[0]
        self.assertEqual(local.model, "qwen3:8b")
        self.assertEqual(local.base_url, "http://localhost:11434")

    def test_ollama_primary_does_not_get_a_duplicate_backup(self):
        provider = get_provider(
            cfg={"provider": "ollama", "model": "qwen3:8b"},
            api_config={"llm_provider": "ollama", "llm_model": "qwen3:8b"})
        self.assertNotIsInstance(provider, FallbackProvider)

    def test_no_local_model_configured_means_no_extra_backup(self):
        provider = get_provider(
            cfg={"provider": "gemini", "model": "gemini-2.5-flash"},
            api_config={"llm_provider": "gemini"})
        self.assertNotIsInstance(provider, FallbackProvider)

    def test_chat_path_timeouts_are_bounded(self):
        """A hung provider must not stall a live conversation for 10
        minutes. The 600s library default produced observed turns of
        602.6s / 604.1s that ended in an EMPTY reply."""
        ollama = get_provider(
            cfg={"provider": "ollama", "model": "qwen3:8b"},
            api_config={"llm_provider": "ollama", "llm_model": "qwen3:8b"})
        self.assertLessEqual(ollama.timeout, 120.0,
                             "local chat must fail fast, not in 600s")

        cloud = get_provider(
            cfg={"provider": "gemini", "model": "gemini-2.5-flash"},
            api_config={"llm_provider": "ollama", "llm_model": "qwen3:8b"})
        self.assertIsInstance(cloud, FallbackProvider)
        chain = [cloud._primary] + cloud._backups
        for member in chain:
            timeout = getattr(member, "timeout", None)
            if timeout is not None:
                self.assertLessEqual(timeout, 180.0,
                                     f"{type(member).__name__} unbounded")

    def test_backup_keys_are_still_tried_before_the_local_model(self):
        api = {"llm_provider": "ollama", "llm_model": "qwen3:8b",
               "gemini_api_key_backups": ["backup-key-1"]}
        with mock.patch(
                "brain.providers._build_backups",
                return_value=[_LocalProvider(answer="backup key")]):
            provider = get_provider(
                cfg={"provider": "gemini", "model": "gemini-2.5-flash"},
                api_config=api)
        self.assertIsInstance(provider, FallbackProvider)
        self.assertEqual(len(provider._backups), 2,
                         "the local model must come AFTER backup keys")


class RotationTest(unittest.TestCase):
    """FallbackProvider must actually rotate on the error the cloud throws."""

    def test_quota_error_rotates_to_the_local_model(self):
        primary = _QuotaBlownProvider()
        local = _LocalProvider()
        chain = FallbackProvider(primary, [local], "gemini")
        out = chain.generate("hello")
        self.assertEqual(out, "answer from the local model")
        self.assertEqual(primary.calls, 1)
        self.assertEqual(local.calls, 1)

    def test_local_outage_still_raises_the_original_quota_error(self):
        primary = _QuotaBlownProvider()
        chain = FallbackProvider(primary, [_LocalProvider(fail=True)], "gemini")
        with self.assertRaises(ProviderError) as ctx:
            chain.generate("hello")
        self.assertIn("429", str(ctx.exception))

    def test_non_retryable_errors_do_not_hit_the_backup(self):
        class _BugProvider(_QuotaBlownProvider):
            def generate(self, *a, **k):
                # deliberately free of retryable keywords (429/quota/expired)
                raise ValueError("programming bug: 'NoneType' has no attribute 'x'")

        local = _LocalProvider()
        chain = FallbackProvider(_BugProvider(), [local], "gemini")
        with self.assertRaises(ValueError):
            chain.generate("hello")
        self.assertEqual(local.calls, 0,
                         "a real bug must surface, not be masked by a backup")

    def test_structured_output_rotates_too(self):
        """The planner asks for JSON — it needs the same protection."""
        primary = _QuotaBlownProvider()
        local = _LocalProvider()
        chain = FallbackProvider(primary, [local], "gemini")
        self.assertEqual(chain.structured_output("{}"), {"ok": True})

    def test_google_invalid_api_key_payload_rotates(self):
        """Google's REAL auth error (found live in Phase 2) contains no
        'auth' word — it must still rotate instead of going silent:
        400 INVALID_ARGUMENT … 'API key not valid. Please pass a valid API
        key.' / 'reason': 'API_KEY_INVALID'."""
        google_shape = (
            "Gemini generate failed: 400 INVALID_ARGUMENT. {'error': "
            "{'code': 400, 'message': 'API key not valid. Please pass a "
            "valid API key.', 'status': 'INVALID_ARGUMENT', 'details': "
            "[{'@type': 'google.rpc.ErrorInfo', 'reason': "
            "'API_KEY_INVALID', 'domain': 'googleapis.com'}]}}")
        primary = _QuotaBlownProvider(message=google_shape)
        local = _LocalProvider()
        chain = FallbackProvider(primary, [local], "gemini")
        self.assertEqual(chain.generate("hi"), "answer from the local model")

    def test_missing_key_message_rotates(self):
        """F08 (missing API key) must degrade to the backup, not crash."""
        primary = _QuotaBlownProvider(
            message="Gemini generate failed: 400 INVALID_ARGUMENT. "
                    "API key missing. Please pass a valid API key.")
        local = _LocalProvider()
        chain = FallbackProvider(primary, [local], "gemini")
        self.assertEqual(chain.generate("hi"), "answer from the local model")


if __name__ == "__main__":
    unittest.main(verbosity=2)
