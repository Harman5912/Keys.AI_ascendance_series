"""Regression tests for the provider/model catalog."""

import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from core.model_catalog import default_model_for, models_for  # noqa: E402
from brain.providers.gemini import GeminiProvider  # noqa: E402


class GeminiGemmaModelsTest(unittest.TestCase):
    def test_gemma_4_models_are_selectable_on_the_gemini_provider(self):
        models = models_for("gemini")
        self.assertIn("gemma-4-26b-a4b-it", models)
        self.assertIn("gemma-4-31b-it", models)

    def test_gemma_models_do_not_change_the_gemini_default(self):
        self.assertEqual(default_model_for("gemini"), "gemini-2.5-flash")

    def test_gemini_model_list_has_no_duplicates(self):
        models = models_for("gemini")
        self.assertEqual(len(models), len(set(models)))


class GeminiGemmaTimeoutTest(unittest.TestCase):
    def test_gemma_gets_a_longer_deadline_than_gemini_flash(self):
        gemma = GeminiProvider(api_key="test", model="gemma-4-26b-a4b-it")
        flash = GeminiProvider(api_key="test", model="gemini-2.5-flash")
        self.assertEqual(gemma.timeout_s, GeminiProvider.GEMMA_TIMEOUT_S)
        self.assertEqual(flash.timeout_s, GeminiProvider.DEFAULT_TIMEOUT_S)
        self.assertGreater(gemma.timeout_s, flash.timeout_s)


if __name__ == "__main__":
    unittest.main()
