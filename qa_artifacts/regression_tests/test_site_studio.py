"""Regression tests for the multi-studio site engine.

These are deterministic: no model, no browser. They protect the property the
product depends on — ten briefs produce ten different complete pages, each of
which passes the same structural checks the live pipeline enforces.
"""

from __future__ import annotations

import hashlib
import re
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from core.site_checks import acceptance_checklist, check_html, checklist_summary  # noqa: E402
from core.site_builder import fallback_plan  # noqa: E402
from core.site_studio import (SAMPLE_SITES, STUDIOS, choose_studio,  # noqa: E402
                              plan_to_content, render_gallery, render_site)


class StudioShowcaseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="keysai_studio_")
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_ten_sites_ten_distinct_studios(self):
        self.assertEqual(len(SAMPLE_SITES), 10)
        studios = [s["studio"] for s in SAMPLE_SITES]
        self.assertEqual(len(set(studios)), 10, studios)
        self.assertTrue(all(s in STUDIOS for s in studios))

    def test_each_site_is_a_different_document(self):
        hashes = {}
        for site in SAMPLE_SITES:
            html = render_site(site, site["studio"])
            digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
            self.assertNotIn(digest, hashes, f"{site['brand']} duplicates {hashes.get(digest)}")
            hashes[digest] = site["brand"]
        self.assertEqual(len(hashes), 10)

    def test_every_site_passes_the_live_pipeline_checks(self):
        for site in SAMPLE_SITES:
            html = render_site(site, site["studio"])
            path = self.dir / f"{site['folder']}.html"
            path.write_text(html, encoding="utf-8")
            ok, problems = check_html(path, "website")
            self.assertTrue(ok, f"{site['brand']}: {problems}")
            self.assertEqual(html.lower().count("<h1"), 1, site["brand"])

    def test_no_external_assets_are_loaded(self):
        for site in SAMPLE_SITES:
            html = render_site(site, site["studio"])
            self.assertIsNone(re.search(r'(?:src|href)=["\']https?://', html, re.I),
                              site["brand"])
            self.assertIsNone(re.search(r"@import\s+url\(", html, re.I), site["brand"])

    def test_each_studio_ships_a_motion_system(self):
        for site in SAMPLE_SITES:
            html = render_site(site, site["studio"])
            self.assertIn("@keyframes", html, site["brand"])
            self.assertIn("prefers-reduced-motion", html, site["brand"])
            self.assertIn("addEventListener", html, site["brand"])

    def test_plan_adapter_works_in_every_studio(self):
        plan = fallback_plan("Landing page for a coffee roastery", "website")
        passed_items = 0
        for key in STUDIOS:
            content = plan_to_content(plan, "website", "coffee")
            content["studio"] = key
            html = render_site(content, key)
            path = self.dir / f"plan_{key}.html"
            path.write_text(html, encoding="utf-8")
            ok, problems = check_html(path, "website")
            self.assertTrue(ok, f"{key}: {problems}")
            passed, total, failing = checklist_summary(
                acceptance_checklist(html, "website", plan))
            self.assertEqual(failing, [], f"{key}: {passed}/{total}")
            passed_items += passed
        self.assertGreater(passed_items, 100)

    def test_choose_studio_is_deterministic_and_varied(self):
        briefs = [
            "Portfolio for a photographer", "Landing page for a bakery",
            "Website for a law firm", "Website for an AI developer tool",
            "Site for a boutique hotel", "Website for a film festival",
            "Website for a design agency", "Website for a plant shop",
            "Website for a business newspaper", "Portfolio for a writer",
        ]
        picks = [choose_studio(b, "website") for b in briefs]
        self.assertEqual(picks, [choose_studio(b, "website") for b in briefs])
        self.assertGreaterEqual(len(set(picks)), 5, picks)

    def test_no_page_ships_a_dead_anchor(self):
        """A studio that hardcodes a destination must not break when the plan
        lacks that section (nightfall's #programme was exactly this bug)."""
        plan = fallback_plan("portfolio for a documentary photographer", "portfolio")
        plan["sections"] = [s for s in plan["sections"] if s["id"] != "programme"]
        content = plan_to_content(plan, "portfolio", "portfolio for a documentary photographer")
        content["nav"] = content.get("nav", []) + [("Programme", "#programme")]
        for key in STUDIOS:
            html = render_site(content, key)
            ids = set(re.findall(r'\bid="([^"]+)"', html))
            targets = set(re.findall(r'href="#([^"]+)"', html))
            self.assertTrue(targets <= ids, f"{key}: dead anchors {targets - ids}")

    def test_a_studio_can_be_forced_for_page_sets(self):
        """Two pages in one set must be able to avoid the same layout."""
        from core.site_builder import render_studio_page

        plan = fallback_plan("portfolio for Lena Fischer", "portfolio")
        pick = lambda forced: render_studio_page(  # noqa: E731
            plan, "portfolio", "portfolio for Lena Fischer", studio=forced)[1]
        self.assertEqual(pick("swiss"), "swiss")
        self.assertEqual(pick("cinematic"), "cinematic")
        self.assertIn(pick("not-a-studio"), STUDIOS)   # unknown names fall back

    def test_gallery_lists_every_built_site(self):
        links = {str(s["id"]): f"{s['folder']}/index.html" for s in SAMPLE_SITES}
        html = render_gallery(SAMPLE_SITES, links, {})
        for site in SAMPLE_SITES:
            self.assertIn(site["brand"].split()[0], html)
            self.assertIn(site["folder"], html)
        self.assertEqual(html.count('<article class="card">'), 10)
        self.assertIn("Ten design systems", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
