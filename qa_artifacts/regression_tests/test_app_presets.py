"""Application presets: dashboards, web apps and Python apps.

The catalogue promises 50 dashboards plus the common kinds of web and Python
application, each carrying a hue and mood that really reach the generated
palette. These tests check the catalogue's shape, that selection matches the
brief (and still varies between near-ties), and that a rendered dashboard uses
the chosen preset's accent rather than a fixed one.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.app_presets import (ALL_PRESETS, DASHBOARD_PRESETS,  # noqa: E402
                              PYTHON_PRESETS, WEBAPP_PRESETS,
                              choose_app_preset, describe, token_kwargs)
from core.design_system import build_tokens, design_brief  # noqa: E402


class CatalogueTest(unittest.TestCase):
    def test_fifty_dashboards(self):
        self.assertGreaterEqual(len(DASHBOARD_PRESETS), 50)

    def test_web_and_python_catalogues_exist(self):
        self.assertGreaterEqual(len(WEBAPP_PRESETS), 40,
                                "common web application types are missing")
        self.assertGreaterEqual(len(PYTHON_PRESETS), 20,
                                "common Python application types are missing")
        self.assertGreaterEqual(len(ALL_PRESETS), 100)

    def test_ids_are_unique_and_kind_prefixed(self):
        ids = [p["id"] for p in ALL_PRESETS]
        self.assertEqual(len(ids), len(set(ids)))
        for preset in ALL_PRESETS:
            with self.subTest(preset=preset["id"]):
                self.assertTrue(preset["id"].startswith(preset["kind"] + "-"))

    def test_every_preset_has_a_usable_palette_input(self):
        for preset in ALL_PRESETS:
            with self.subTest(preset=preset["id"]):
                self.assertIsInstance(preset["hue"], int)
                self.assertTrue(0 <= preset["hue"] < 360)
                self.assertIn(preset["mood"], ("dark", "light", "vivid"))
                self.assertTrue(preset["summary"])
                self.assertTrue(preset["keywords"])

    def test_every_palette_passes_contrast_checks(self):
        for preset in ALL_PRESETS:
            tokens = build_tokens(preset["id"], kind=preset["kind"],
                                  **token_kwargs(preset))
            with self.subTest(preset=preset["id"]):
                self.assertEqual(tokens.problems(), [])


class SelectionTest(unittest.TestCase):
    def test_same_brief_and_seed_pick_the_same_preset(self):
        a = choose_app_preset("a fleet dashboard", "dashboard", seed="x")
        b = choose_app_preset("a fleet dashboard", "dashboard", seed="x")
        self.assertEqual(a["id"], b["id"])

    def test_dashboard_domains_get_their_own_preset(self):
        for brief, expected in (("a fleet dashboard for our trucks", "fleet"),
                                ("a support desk dashboard with SLA tickets", "support"),
                                ("a security operations dashboard", "security"),
                                ("a pharmacy dashboard", "pharmacy"),
                                ("an ecommerce dashboard with orders", "ecommerce")):
            with self.subTest(brief=brief):
                preset = choose_app_preset(brief, "dashboard", seed="d")
                self.assertIn(expected, preset["id"] + " " + " ".join(preset["keywords"]))

    def test_web_app_types_match(self):
        for brief, expected in (("a CRM for the sales team", "webapp-crm"),
                                ("a booking system for a salon", "webapp-booking"),
                                ("a helpdesk for support tickets", "webapp-helpdesk"),
                                ("a kanban board for sprints", "webapp-kanban")):
            with self.subTest(brief=brief):
                self.assertEqual(choose_app_preset(brief, "webapp", seed="w")["id"],
                                 expected)

    def test_python_app_types_match(self):
        for brief, expected in (("a python desktop app to track inventory",
                                 "python-desktop-crud"),
                                ("a web scraper that exports csv", "python-web-scraper"),
                                ("a pdf merge tool in python", "python-pdf-tool")):
            with self.subTest(brief=brief):
                self.assertEqual(choose_app_preset(brief, "python", seed="p")["id"],
                                 expected)

    def test_unmatched_briefs_still_vary(self):
        chosen = {choose_app_preset(f"project {n}", "dashboard", seed="z")["id"]
                  for n in range(12)}
        self.assertGreater(len(chosen), 3, f"selection collapsed to {chosen}")


class PromptAndRenderTest(unittest.TestCase):
    def test_token_kwargs_carry_hue_and_mood(self):
        preset = choose_app_preset("a fleet dashboard", "dashboard")
        kwargs = token_kwargs(preset)
        self.assertEqual(kwargs["hue"], float(preset["hue"]))
        self.assertEqual(kwargs["mood"], preset["mood"])

    def test_design_brief_accepts_a_preset_hue(self):
        preset = choose_app_preset("a fleet dashboard", "dashboard")
        kwargs = token_kwargs(preset)
        text = design_brief("fleet", kind="dashboard", **kwargs)
        self.assertIn("LAYOUT", text)
        accent = build_tokens("fleet", kind="dashboard", **kwargs).palette["accent"]
        self.assertIn(accent, text)
        # The hue genuinely selects the palette, it is not decoration.
        other = design_brief("fleet", kind="dashboard", mood=kwargs["mood"],
                             hue=(kwargs["hue"] + 180) % 360)
        self.assertNotEqual(text, other)
        self.assertIn("DESIGN PRESET", describe(preset))

    def test_rendered_dashboard_uses_the_preset_palette(self):
        from core.app_builder import build_dashboard
        brief = "a fleet dashboard for our trucks and fuel costs"
        out = Path(tempfile.mkdtemp(prefix="app_preset_test_"))
        result = build_dashboard(brief, out, verify=False)
        preset = choose_app_preset(brief, "dashboard", seed=out.name)
        tokens = build_tokens(brief, kind="dashboard", **token_kwargs(preset))
        css = (out / "static" / "style.css").read_text(encoding="utf-8")
        self.assertEqual(result["preset"], preset["id"])
        self.assertIn(tokens.palette["accent"], css)


if __name__ == "__main__":
    unittest.main(verbosity=2)
