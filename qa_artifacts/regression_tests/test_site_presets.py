"""Website design presets and Gemini-first site builds.

Two promises are tested:

1. The preset catalogue holds at least 50 distinct looks, every one inside a
   real studio, with readable accents on the studio's own surface (the acid
   studio is excluded: its accent is a fill behind ink, not text on paper).
2. Site builds prefer Gemini when a key is configured and fall back to the
   local Ollama model when there is no key or the user names a local model.

Selection is deterministic for the same brief (a rebuild looks the same) and
varies across different briefs (a restaurant is not always the same site).
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.design_system import contrast_ratio  # noqa: E402
from core.site_builder import (apply_preset_css, fallback_plan,  # noqa: E402
                               render_studio_page, _provider)
from core.site_studio import ORDER  # noqa: E402
from core.site_studio import presets  # noqa: E402

# The surface each studio paints its accent on. Brutalist is deliberately not
# here: its --acid is a block fill with ink text on it, so paper contrast is
# the wrong measure for that studio.
SURFACES = {
    "aurora": "#070b16",
    "editorial": "#f4efe6",
    "swiss": "#f7f7f4",
    "terminal": "#050806",
    "organic": "#f4f1e8",
    "luxury": "#0c0f14",
    "pop": "#fff7ec",
    "cinematic": "#050505",
    "newsroom": "#fbfaf7",
}


class PresetCatalogueTest(unittest.TestCase):
    def test_at_least_fifty_presets(self):
        self.assertGreaterEqual(len(presets.PRESETS), 50,
                                "the catalogue drifted below the promised 50")

    def test_ids_are_unique(self):
        ids = [p["id"] for p in presets.PRESETS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_preset_uses_a_real_studio(self):
        for preset in presets.PRESETS:
            with self.subTest(preset=preset["id"]):
                self.assertIn(preset["studio"], ORDER)

    def test_every_colour_is_a_full_hex(self):
        for preset in presets.PRESETS:
            with self.subTest(preset=preset["id"]):
                self.assertRegex(preset["accent"], r"^#[0-9a-fA-F]{6}$")
                self.assertRegex(preset["accent2"], r"^#[0-9a-fA-F]{6}$")

    def test_every_preset_serves_at_least_one_kind(self):
        for preset in presets.PRESETS:
            with self.subTest(preset=preset["id"]):
                self.assertTrue(set(preset["kinds"]) >= {"portfolio"}
                                or preset["kinds"])

    def test_accents_are_readable_on_their_studio_surface(self):
        for preset in presets.PRESETS:
            surface = SURFACES.get(preset["studio"])
            if surface is None:
                continue
            with self.subTest(preset=preset["id"]):
                ratio = contrast_ratio(preset["accent"], surface)
                self.assertGreaterEqual(
                    ratio, 3.0,
                    f"{preset['id']} accent {preset['accent']} is {ratio:.2f}:1 "
                    f"on {preset['studio']} and would be hard to read")

    def test_the_css_override_targets_the_studios_own_variable(self):
        expected = {"aurora": "--accent", "editorial": "--accent",
                    "brutalist": "--acid", "swiss": "--red",
                    "terminal": "--accent", "organic": "--green",
                    "luxury": "--gold", "pop": "--pink",
                    "cinematic": "--amber", "newsroom": "--red"}
        for preset in presets.PRESETS:
            css = presets.preset_css(preset)
            variable = expected[preset["studio"]]
            with self.subTest(preset=preset["id"]):
                self.assertIn(f"{variable}:{preset['accent']}", css)
                self.assertIn("--crown-focus:", css)


class PresetSelectionTest(unittest.TestCase):
    def test_the_same_brief_and_seed_pick_the_same_preset(self):
        a = presets.choose_preset("a portfolio for a photographer", "portfolio", seed="p1")
        b = presets.choose_preset("a portfolio for a photographer", "portfolio", seed="p1")
        self.assertEqual(a["id"], b["id"])

    def test_different_briefs_do_not_all_land_on_one_preset(self):
        briefs = [("a portfolio for a photographer", "portfolio"),
                  ("a restaurant website", "website"),
                  ("a fintech saas landing page", "website"),
                  ("a yoga studio site", "website"),
                  ("a music festival page", "website"),
                  ("a law firm website", "website"),
                  ("an art gallery site", "website"),
                  ("a data dashboard", "webapp")]
        chosen = {presets.choose_preset(b, k, seed="s")["id"] for b, k in briefs}
        self.assertGreater(len(chosen), 3, f"selection collapsed to {chosen}")

    def test_a_matched_keyword_chooses_a_preset_built_for_it(self):
        for brief, word in (("a restaurant and cafe website", "restaurant"),
                            ("a photographer portfolio", "photographer"),
                            ("a gaming site", "gaming"),
                            ("a luxury hotel", "hotel")):
            with self.subTest(brief=brief):
                preset = presets.choose_preset(brief, "website", seed="k")
                self.assertIn(word, preset["moods"])

    def test_kind_filtering_stays_inside_the_kind(self):
        for kind in ("portfolio", "website", "webapp"):
            with self.subTest(kind=kind):
                preset = presets.choose_preset("something entirely unrelated", kind)
                self.assertIn(kind, preset["kinds"])


class PresetRenderingTest(unittest.TestCase):
    def test_the_rendered_page_carries_the_preset_accent(self):
        preset = presets.choose_preset("a restaurant and cafe website", "website")
        plan = fallback_plan("a restaurant and cafe website", "website")
        html, studio = render_studio_page(plan, "website", "a restaurant and cafe website",
                                          seed="render", studio=preset["studio"])
        styled = apply_preset_css(html, preset)
        self.assertEqual(studio, preset["studio"])
        self.assertIn(preset["accent"], styled)
        self.assertGreater(len(styled), len(html))

    def test_apply_returns_the_page_unchanged_without_a_preset(self):
        html = "<html><head><style>:root{}</style></head><body></body></html>"
        self.assertEqual(apply_preset_css(html, None), html)


class GeminiFirstTest(unittest.TestCase):
    def _gemini_config(self):
        return {"provider": "gemini", "model": "gemini-2.5-flash"}

    def test_gemini_is_used_when_a_key_exists(self):
        with mock.patch("core.api_config.get_api_key", return_value="test-key"), \
                mock.patch("core.api_config.get_task_model",
                           return_value=self._gemini_config()):
            provider, name, note = _provider()
        from brain.providers.gemini import GeminiProvider
        self.assertIsInstance(provider, GeminiProvider)
        self.assertEqual(name, "gemini-2.5-flash")
        self.assertEqual(note, "gemini")

    def test_local_model_is_used_when_no_key_is_configured(self):
        with mock.patch("core.api_config.get_api_key", return_value=""), \
                mock.patch("core.crown_bridge.load_config",
                           return_value={"ollama_url": "http://127.0.0.1:11434"}), \
                mock.patch("core.crown_bridge.list_models",
                           return_value=["gemma4:12b", "qwen3:8b"]), \
                mock.patch("core.crown_bridge.recommend_model",
                           return_value=("gemma4:12b", "preferred")):
            provider, name, note = _provider()
        self.assertEqual(name, "gemma4:12b")
        self.assertNotEqual(note, "gemini")
        self.assertFalse(provider.__class__.__name__ == "GeminiProvider")

    def test_an_explicit_local_model_skips_gemini(self):
        with mock.patch("core.api_config.get_api_key", return_value="test-key"), \
                mock.patch("core.crown_bridge.load_config",
                           return_value={"ollama_url": "http://127.0.0.1:11434"}), \
                mock.patch("core.crown_bridge.list_models",
                           return_value=["gemma4:12b"]), \
                mock.patch("core.crown_bridge.recommend_model",
                           return_value=("gemma4:12b", "requested")):
            provider, name, _note = _provider(model="gemma4:12b")
        self.assertEqual(name, "gemma4:12b")
        self.assertEqual(provider.__class__.__name__, "OpenAICompatProvider")


if __name__ == "__main__":
    unittest.main(verbosity=2)
