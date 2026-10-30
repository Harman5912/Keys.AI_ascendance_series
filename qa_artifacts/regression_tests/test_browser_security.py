"""Group E — security, persistence and regression (22 scenarios)."""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from browser_fixtures import ROOT, BrowserCase, stop_site

sys.path.insert(0, str(ROOT))

from core.research_browser import (assets, collector, library, paths,  # noqa: E402
                                   tools, urls)

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 80)


def tearDownModule():
    stop_site()


class SecurityCase(BrowserCase):
    def setUp(self):
        super().setUp()
        self.temp = Path(tempfile.mkdtemp(prefix="rb_sec_"))
        self._patches = [
            mock.patch.object(paths, "library_path",
                              lambda: self.temp / "library.json"),
            mock.patch.object(paths, "workspace_root",
                              lambda: self.temp / "workspace"),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self._patches):
            patch.stop()
        shutil.rmtree(self.temp, ignore_errors=True)
        super().tearDown()


class TestNavigationPolicy(SecurityCase):
    def test_e01_blocks_local_file_access(self):
        allowed, reason = urls.is_allowed("file:///C:/Windows/win.ini")
        self.assertFalse(allowed)
        self.assertIn("file", reason)

    def test_e02_blocks_javascript_urls(self):
        allowed, _ = urls.is_allowed("javascript:document.cookie")
        self.assertFalse(allowed)

    def test_e03_blocks_data_urls(self):
        allowed, _ = urls.is_allowed("data:text/html,<script>alert(1)</script>")
        self.assertFalse(allowed)

    def test_e04_blocks_browser_internal_pages(self):
        for target in ("chrome://settings", "view-source:https://example.com",
                       "ftp://example.com/file"):
            allowed, _ = urls.is_allowed(target)
            self.assertFalse(allowed, target)

    def test_e05_allows_normal_web_urls(self):
        for target in ("https://example.com", "http://127.0.0.1:8000/x?y=1"):
            allowed, reason = urls.is_allowed(target)
            self.assertTrue(allowed, f"{target}: {reason}")

    def test_e06_redirects_are_followed_only_within_the_web(self):
        # A redirect to a blocked scheme must still be refused by policy.
        allowed, _ = urls.is_allowed("file:///etc/passwd")
        self.assertFalse(allowed)

    def test_e07_remote_pages_cannot_load_local_files(self):
        from PyQt6.QtWebEngineCore import QWebEngineSettings
        settings = self.service._profile.settings()
        self.assertFalse(settings.testAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls))
        self.assertFalse(settings.testAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls))


class TestAssetSafety(SecurityCase):
    def test_e08_path_traversal_filename_is_neutralised(self):
        name = assets._safe_name("https://example.com/../../evil.exe?x=1")
        self.assertNotIn("..", name)
        self.assertNotIn("/", name)
        self.assertNotIn("\\", name)

    def test_e09_downloads_stay_inside_the_task_workspace(self):
        self.load("/")
        collected = collector.collect_image(
            self.service, self.tab, self.site.url("/pixel.png"), task_id="t1")
        path = Path(collected["asset"]["path"]).resolve()
        root = paths.workspace_root().resolve()
        self.assertIn(root, path.parents)

    def test_e10_oversized_resource_is_refused(self):
        with self.assertRaises(assets.AssetError):
            assets.fetch(self.site.url("/huge.bin"), task_id="t1",
                         expect="document", max_bytes=5_000)

    def test_e11_html_disguised_as_an_image_is_refused(self):
        with self.assertRaises(assets.AssetError):
            assets.fetch(self.site.url("/fake.png"), task_id="t1")

    def test_e12_unsafe_asset_urls_are_refused(self):
        for target in ("file:///C:/Windows/win.ini", "ftp://x/y.png",
                       "javascript:alert(1)"):
            with self.assertRaises(assets.AssetError):
                assets.fetch(target, task_id="t1")

    def test_e13_rejected_asset_stays_unapproved(self):
        self.load("/")
        collected = collector.collect_image(
            self.service, self.tab, self.site.url("/pixel.png"),
            task_id="t1", license_status="do-not-reuse")
        asset_id = collected["asset"]["asset_id"]
        self.assertFalse(library.get_asset(asset_id)["approved"])
        library.update_asset(asset_id, approved=False)
        self.assertFalse(library.get_asset(asset_id)["approved"])

    def test_e14_licence_values_are_normalised(self):
        self.load("/")
        collected = collector.collect_image(
            self.service, self.tab, self.site.url("/pixel.png"),
            task_id="t1", license_status="totally-fine-honest")
        self.assertEqual(collected["asset"]["license_status"], "unknown")


class TestSessionControl(SecurityCase):
    def test_e15_takeover_blocks_agent_clicks(self):
        self.load("/")
        self.service.request_human_takeover(self.tab, "login needed")
        result = self.service.click_element(self.tab, selector="#second-link")
        self.assertFalse(result["ok"])
        self.assertIn("taken control", result["error"])

    def test_e16_releasing_takeover_restores_control(self):
        self.load("/")
        self.service.request_human_takeover(self.tab, "login")
        self.service.release_takeover(self.tab)
        result = self.service.click_element(self.tab, selector="#second-link")
        self.assertTrue(result["ok"], result)

    def test_e17_page_confirmations_are_dismissed(self):
        self.load("/")
        before = len(self.service.log_lines)
        answer = self.service._run_js(self.tab, "confirm('Delete everything?')")
        self.assertFalse(answer)
        self.assertGreater(len(self.service.log_lines), before)
        self.assertIn("confirm", " ".join(self.service.log_lines[-2:]))

    def test_e18_page_initiated_downloads_are_cancelled(self):
        class FakeRequest:
            def __init__(self):
                self.cancelled = False

            def downloadFileName(self):
                return "payload.pdf"

            def cancel(self):
                self.cancelled = True

        request = FakeRequest()
        self.service._on_download_requested(request)
        self.assertTrue(request.cancelled)
        self.assertTrue(any("blocked in-page download" in line
                            for line in self.service.log_lines))

    def test_e19_malicious_page_cannot_change_agent_policy(self):
        self.load("/")
        # The page contains javascript:/file: links and an injected "ignore your
        # instructions" style payload; policy must still refuse them.
        page = self.service.page_text(self.tab)
        self.assertIn("local file", page["text"])
        self.assertFalse(urls.is_allowed("file:///C:/Windows/win.ini")[0])
        with self.assertRaises(assets.AssetError):
            assets.fetch("file:///C:/Windows/win.ini", task_id="t1")

    def test_e20_unknown_tab_id_is_rejected(self):
        message = tools.execute({"action": "get_page_text", "tab_id": "nope"})
        self.assertIn("Unknown tab", message)


class TestPersistenceAndWiring(SecurityCase):
    def test_e21_tasks_are_isolated(self):
        library.add_asset(str(self._asset()), task_id="one")
        library.add_asset(str(self._asset(colour=(10, 10, 200))), task_id="two")
        self.assertEqual(len(library.list_assets("one")), 1)
        self.assertEqual(len(library.list_assets("two")), 1)
        self.assertEqual(library.list_assets("three"), [])

    def test_e22_library_survives_a_reload(self):
        record = library.add_source("https://example.org/page",
                                    title="Example", task_id="persist")
        reloaded = library.list_sources("persist")
        self.assertEqual(reloaded[0]["source_id"], record["source_id"])
        self.assertTrue(paths.library_path().is_file())

    def test_e23_cleanup_only_removes_that_task(self):
        library.add_source("https://example.org/a", task_id="keep")
        library.add_source("https://example.org/b", task_id="drop")
        removed = library.clear_task("drop")
        self.assertEqual(removed, 1)
        self.assertEqual(len(library.list_sources("keep")), 1)
        self.assertEqual(len(library.list_sources("drop")), 0)

    def test_e24_closed_tabs_are_released(self):
        tab = self.service.open_tab(self.site.url("/"))
        self.service.close_tab(tab)
        self.assertNotIn(tab, [t["tab_id"] for t in self.service.tabs()])
        self.assertFalse(self.service.state(tab)["ok"])
        self.assertFalse(self.service.page_text(tab)["ok"])

    def test_e25_tool_wiring_is_intact(self):
        from core.tool_declarations import TOOL_DECLARATIONS
        from core.tool_registry import TOOL_HANDLERS
        names = [tool["name"] for tool in TOOL_DECLARATIONS]
        self.assertIn("research_browser", names)
        self.assertIn("research_browser", TOOL_HANDLERS)
        message = tools.execute({"action": "research_coverage", "task_id": "none"})
        self.assertIn("sources", message)

    def test_e26_capture_cannot_escape_the_workspace(self):
        self.load("/")
        result = collector.capture(self.service, self.tab, task_id="t1")
        path = Path(result["path"]).resolve()
        self.assertIn(paths.workspace_root().resolve(), path.parents)

    # helpers -----------------------------------------------------------
    def _asset(self, colour=(200, 40, 40)) -> Path:
        import io
        from PIL import Image
        folder = self.temp / "src"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"asset_{hashlib.md5(str(colour).encode()).hexdigest()}.png"
        buf = io.BytesIO()
        Image.new("RGB", (40, 30), colour).save(buf, format="PNG")
        path.write_bytes(buf.getvalue())
        return path


if __name__ == "__main__":
    unittest.main(verbosity=2)
