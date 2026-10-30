"""Group A + B — the real browser, tabs, observations and screenshots.

Every test drives the shipped :class:`BrowserService` against a local HTTP
server and a real QtWebEngine view. Nothing here mocks the engine: the page is
loaded over a socket, rendered by Chromium, and observed through the same page
object the user sees.
"""

from __future__ import annotations

import io
import sys
import time
import unittest
from pathlib import Path

from browser_fixtures import (BIG, BROKEN, PIXEL, ROOT, BrowserCase, qt_app,
                              site, stop_site)

sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from core.research_browser import service as service_mod, urls  # noqa: E402


def tearDownModule():
    stop_site()


class TestBrowserAndTabs(BrowserCase):
    """Group A — real browser and tab management (20 scenarios)."""

    def test_a01_navigates_and_renders(self):
        self.load("/")
        text = self.service.page_text(self.tab)
        self.assertIn("Controlled research page", text["text"])

    def test_a02_url_is_accurate(self):
        self.load("/")
        self.assertEqual(self.service.state(self.tab)["url"], self.site.url("/"))

    def test_a03_title_is_the_real_title(self):
        self.load("/")
        self.assertEqual(self.service.page_title(self.tab)["title"],
                         "Research Index")

    def test_a04_navigates_to_a_second_url(self):
        self.load("/")
        self.service.navigate(self.tab, self.site.url("/second"))
        self.assertIn("Second page", self.service.page_text(self.tab)["text"])

    def test_a05_goes_back(self):
        self.load("/")
        self.service.navigate(self.tab, self.site.url("/second"))
        result = self.service.go_back(self.tab)
        self.assertTrue(result["ok"], result)
        self.assertTrue(self.service.state(self.tab)["url"].endswith("/"))

    def test_a06_goes_forward(self):
        self.load("/")
        self.service.navigate(self.tab, self.site.url("/second"))
        self.service.go_back(self.tab)
        result = self.service.go_forward(self.tab)
        self.assertTrue(result["ok"], result)
        self.assertIn("/second", self.service.state(self.tab)["url"])

    def test_a07_reloads(self):
        self.load("/")
        before = self.service.page_text(self.tab)["text"]
        self.service.navigate(self.tab, self.site.url("/second"))
        self.service.navigate(self.tab, self.site.url("/"))
        result = self.service.reload_page(self.tab)
        self.assertTrue(result["ok"])
        self.assertEqual(self.service.page_text(self.tab)["text"][:20],
                         before[:20])

    def test_a08_stops_a_loading_page(self):
        self.service.navigate(self.tab, self.site.url("/slow"), timeout=0.4)
        result = self.service.stop_navigation(self.tab)
        self.assertTrue(result["ok"])
        self.assertFalse(self.service.state(self.tab)["loading"])

    def test_a09_opens_a_new_tab(self):
        before = len(self.service.tabs())
        second = self.service.open_tab(self.site.url("/second"))
        self.assertEqual(len(self.service.tabs()), before + 1)
        self.assertEqual(self.service.active_tab(), second)

    def test_a10_switching_tabs_switches_the_page(self):
        self.load("/")
        other = self.service.open_tab(self.site.url("/second"))
        self.service.select_tab(self.tab)
        self.assertEqual(self.service.page_title(self.tab)["title"],
                         "Research Index")
        self.service.select_tab(other)
        self.assertEqual(self.service.page_title(other)["title"], "Second Page")
        self.service.close_tab(other)

    def test_a11_closing_a_tab_removes_it(self):
        other = self.service.open_tab(self.site.url("/"))
        self.service.close_tab(other)
        self.assertNotIn(other, [t["tab_id"] for t in self.service.tabs()])
        self.assertEqual(self.service.state(other)["ok"], False)

    def test_a12_follows_a_redirect(self):
        self.service.navigate(self.tab, self.site.url("/redirect"))
        self.assertIn("/second", self.service.state(self.tab)["url"])
        self.assertIn("Second page", self.service.page_text(self.tab)["text"])

    def test_a13_text_input_becomes_a_search_not_a_url(self):
        kind, target = urls.normalise_input("modern portfolio design")
        self.assertEqual(kind, "search")
        self.assertIn("google.com", target)
        self.assertIn("modern", target)

    def test_a14_blocks_the_file_scheme(self):
        result = self.service.navigate(self.tab, "file:///C:/Windows/win.ini")
        self.assertFalse(result["ok"])
        self.assertIn("file:", result["error"])

    def test_a15_blocks_javascript_urls(self):
        result = self.service.navigate(self.tab, "javascript:alert(1)")
        self.assertFalse(result["ok"])
        self.assertIn("javascript", result["error"])

    def test_a16_unreachable_site_reports_a_failure(self):
        result = self.service.navigate(self.tab, "http://127.0.0.1:1/",
                                       timeout=6)
        self.assertFalse(result["ok"])
        self.assertIn("did not finish loading", result["error"])

    def test_a17_navigation_timeout_is_reported(self):
        result = self.service.navigate(self.tab, self.site.url("/slow"),
                                       timeout=0.8)
        self.assertTrue(result.get("timeout"), result)

    def test_a18_user_navigation_updates_reported_state(self):
        # A "user" navigation is the view being pointed somewhere by hand.
        self.view.setUrl(service_mod.QUrl(self.site.url("/second")))
        deadline = time.time() + 20
        while time.time() < deadline:
            qt_app().processEvents()
            if "/second" in self.service.state(self.tab)["url"]:
                break
            time.sleep(0.05)
        self.assertIn("/second", self.service.state(self.tab)["url"])

    def test_a19_agent_navigation_shows_in_the_visible_view(self):
        self.load("/second")
        self.assertIn("/second", self.view.url().toString())
        self.assertEqual(self.view.url().toString(),
                         self.service.state(self.tab)["url"])

    def test_a20_actions_target_the_named_tab_only(self):
        other = self.service.open_tab(self.site.url("/second"))
        self.service.select_tab(other)
        self.service.navigate(self.tab, self.site.url("/"))
        self.assertIn("/second", self.service.state(other)["url"])
        self.assertTrue(self.service.state(self.tab)["url"].endswith("/"))
        self.service.close_tab(other)


class TestObservationsAndScreenshots(BrowserCase):
    """Group B — genuine observations and screenshots (20 scenarios)."""

    def test_b01_extracts_page_text(self):
        self.load("/")
        text = self.service.page_text(self.tab)
        self.assertIn("quick brown fox", text["text"])

    def test_b02_extracts_headings(self):
        self.load("/")
        structure = self.service.page_structure(self.tab)
        texts = [h["text"] for h in structure["headings"]]
        self.assertIn("Controlled research page", texts)
        self.assertIn("Section one", texts)

    def test_b03_extracts_a_selected_section(self):
        self.load("/")
        self.service._run_js(self.tab, """
            (() => { const el = document.getElementById('paragraph');
              const r = document.createRange(); r.selectNodeContents(el);
              const s = window.getSelection(); s.removeAllRanges();
              s.addRange(r); return true; })()""")
        result = self.service.extract_selection(self.tab)
        self.assertTrue(result["has_selection"])
        self.assertIn("quick brown fox", result["text"])

    def test_b04_reads_table_headers_and_rows(self):
        self.load("/")
        tables = self.service.page_structure(self.tab)["tables"]
        self.assertEqual(tables[0]["headers"], ["Name", "Value"])
        self.assertEqual(tables[0]["rows"][0], ["alpha", "1"])
        self.assertEqual(len(tables[0]["rows"]), 2)

    def test_b05_finds_page_elements(self):
        self.load("/")
        found = self.service.find_page_elements(self.tab, "#submit")
        self.assertTrue(found["ok"])
        self.assertEqual(found["elements"][0]["tag"], "button")

    def test_b06_clicks_a_dom_element(self):
        self.load("/")
        result = self.service.click_element(self.tab, selector="#second-link")
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["navigated"])
        self.assertIn("/second", result["url_after"])

    def test_b07_waits_for_dynamic_content(self):
        self.load("/")
        result = self.service.wait_for_element(self.tab, "#dynamic", timeout=8)
        self.assertTrue(result["ok"], result)
        self.assertIn("Dynamically inserted", self.service.page_text(self.tab)["text"])

    def test_b08_detects_a_content_change(self):
        self.load("/")
        before = self.service.page_text(self.tab)["text"]
        self.service.navigate(self.tab, self.site.url("/second"))
        after = self.service.page_text(self.tab)["text"]
        self.assertNotEqual(before, after)

    def test_b09_capture_writes_a_file(self):
        self.load("/")
        shot = self.service.capture_screenshot(self.tab)
        self.assertTrue(shot["ok"], shot)
        self.assertTrue(Path(shot["path"]).is_file())

    def test_b10_capture_is_a_real_png_with_dimensions(self):
        self.load("/")
        shot = self.service.capture_screenshot(self.tab)
        with Image.open(shot["path"]) as im:
            self.assertEqual(im.format, "PNG")
            self.assertEqual(im.size, (shot["width"], shot["height"]))
        self.assertGreater(shot["width"], 300)

    def test_b11_full_page_is_taller_than_the_viewport(self):
        self.load("/long")
        viewport = self.service.capture_screenshot(self.tab)
        full = self.service.capture_full_page(self.tab)
        self.assertTrue(full["ok"], full)
        self.assertGreater(full["height"], viewport["height"])

    def test_b12_element_capture_is_smaller_than_the_viewport(self):
        self.load("/")
        viewport = self.service.capture_screenshot(self.tab)
        element = self.service.capture_screenshot(self.tab, element="#title")
        self.assertTrue(element["ok"], element)
        self.assertLess(element["width"], viewport["width"])

    def test_b13_capture_records_url_and_tab(self):
        self.load("/second")
        shot = self.service.capture_screenshot(self.tab)
        self.assertIn("/second", shot["url"])
        self.assertEqual(shot["tab_id"], self.tab)
        self.assertTrue(shot["captured_at"])
        self.assertEqual(shot["title"], "Second Page")

    def test_b14_capture_of_a_background_tab_restores_the_active_one(self):
        self.load("/")
        other = self.service.open_tab(self.site.url("/second"))
        self.service.select_tab(self.tab)
        self.assertEqual(self.service.active_tab(), self.tab)
        shot = self.service.capture_screenshot(other)
        self.assertTrue(shot["ok"], shot)
        self.assertIn("/second", shot["url"])
        self.assertEqual(self.service.active_tab(), self.tab)
        self.service.close_tab(other)

    def test_b15_capture_bytes_are_real_pixels(self):
        self.load("/big.png")
        shot = self.service.capture_screenshot(self.tab)
        raw = Path(shot["path"]).read_bytes()
        self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(len(raw), Path(shot["path"]).stat().st_size)
        self.assertGreater(len(set(raw[-5000:])), 8)

    def test_b16_capture_without_a_view_fails_with_a_reason(self):
        self.load("/")
        self.service.detach_view()
        try:
            shot = self.service.capture_screenshot(self.tab)
        finally:
            self.service.attach_view(self.view)
        self.assertFalse(shot["ok"])
        self.assertIn("view", shot["error"].lower())

    def test_b17_empty_page_text_is_empty_not_invented(self):
        self.load("/empty")
        text = self.service.page_text(self.tab)
        self.assertTrue(text["ok"])
        self.assertEqual(text["text"].strip(), "")

    def test_b18_failed_observation_reports_failure(self):
        self.service.close_tab(self.tab)
        result = self.service.page_text(self.tab)
        self.assertFalse(result["ok"])
        self.assertIn("Unknown tab", result["error"])

    def test_b19_structure_reflects_actual_metadata(self):
        self.load("/")
        structure = self.service.page_structure(self.tab)
        self.assertEqual(structure["meta"].get("description"),
                         "A controlled page for tests")
        self.assertEqual(structure["meta"].get("og:title"), "Research Index OG")

    def test_b20_capture_is_marked_as_a_capture_not_generated_art(self):
        self.load("/")
        shot = self.service.capture_screenshot(self.tab)
        self.assertEqual(shot["format"], "PNG")
        self.assertIn("capture_", Path(shot["path"]).name)
        self.assertIn(self.site.base, shot["url"])
        # A generated illustration would not carry the page URL it depicts.
        self.assertTrue(shot["url"].startswith("http://127.0.0.1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
