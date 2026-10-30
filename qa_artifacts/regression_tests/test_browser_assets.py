"""Group C — image discovery, retrieval and provenance (20 scenarios).

The images are served by the local fixture server and downloaded over HTTP, so
these tests prove real bytes arrive, are decoded, and are recorded with their
source. A mock would not catch the things that actually break: HTML error pages
returned as images, truncated files, wrong dimensions, lost provenance.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from browser_fixtures import BIG, BROKEN, PIXEL, ROOT, BrowserCase, stop_site

sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from core.research_browser import (assets, collector, library, paths,  # noqa: E402
                                   urls)


def tearDownModule():
    stop_site()


class _LibraryCase(BrowserCase):
    """Isolate the library and workspaces in a temp folder for each test."""

    def setUp(self):
        super().setUp()
        self.temp = Path(tempfile.mkdtemp(prefix="rb_assets_"))
        self._patches = [
            mock.patch.object(paths, "library_path",
                              lambda: self.temp / "library.json"),
            mock.patch.object(paths, "workspace_root",
                              lambda: self.temp / "workspace"),
        ]
        for patch in self._patches:
            patch.start()
        self.task = "task_c"

    def tearDown(self):
        for patch in reversed(self._patches):
            patch.stop()
        shutil.rmtree(self.temp, ignore_errors=True)
        super().tearDown()


class TestImageDiscovery(_LibraryCase):
    def test_c01_finds_images_on_the_page(self):
        self.load("/")
        result = self.service.list_page_images(self.tab)
        self.assertTrue(result["ok"])
        srcs = [i["src"] for i in result["images"]]
        self.assertTrue(any(src.endswith("/pixel.png") for src in srcs))

    def test_c02_reports_the_real_source_url(self):
        self.load("/")
        info = self.service.inspect_image_resource(
            self.tab, self.site.url("/big.png"))
        self.assertTrue(info["ok"], info)
        self.assertEqual(info["src"], self.site.url("/big.png"))
        self.assertEqual(info["width"], 800)

    def test_c03_selects_the_responsive_source_not_the_thumbnail(self):
        self.load("/")
        images = self.service.list_page_images(self.tab)["images"]
        responsive = [i for i in images if i["src"].endswith("big.png")]
        self.assertTrue(responsive, images)
        self.assertEqual(responsive[0]["width"], 800)

    def test_c04_downloads_the_actual_bytes(self):
        self.load("/")
        fetched = assets.fetch(self.site.url("/pixel.png"), task_id=self.task)
        self.assertEqual(Path(fetched["path"]).read_bytes(), PIXEL)

    def test_c05_detects_the_real_format(self):
        fetched = assets.fetch(self.site.url("/big.png"), task_id=self.task)
        self.assertEqual(fetched["format"], "PNG")
        self.assertEqual(fetched["width"], 800)
        self.assertEqual(fetched["height"], 600)

    def test_c06_decodes_the_downloaded_file(self):
        fetched = assets.fetch(self.site.url("/big.png"), task_id=self.task)
        with Image.open(fetched["path"]) as im:
            im.load()
            self.assertEqual(im.size, (800, 600))

    def test_c07_validates_dimensions_and_size(self):
        fetched = assets.fetch(self.site.url("/big.png"), task_id=self.task)
        with Image.open(fetched["path"]) as im:
            self.assertEqual((fetched["width"], fetched["height"]), im.size)
        self.assertEqual(fetched["bytes"], len(BIG))
        self.assertEqual(fetched["bytes"],
                         Path(fetched["path"]).stat().st_size)

    def test_c08_broken_image_url_is_rejected(self):
        with self.assertRaises(assets.AssetError):
            assets.fetch(self.site.url("/broken.png"), task_id=self.task)

    def test_c09_missing_resource_is_a_failure(self):
        with self.assertRaises(assets.AssetError) as ctx:
            assets.fetch(self.site.url("/missing.png"), task_id=self.task)
        self.assertIn("404", str(ctx.exception))

    def test_c10_download_timeout_is_reported(self):
        with self.assertRaises(assets.AssetError) as ctx:
            assets.fetch(self.site.url("/slow-image.png"), task_id=self.task,
                         timeout=0.5)
        self.assertIn("ime", str(ctx.exception))

    def test_c11_html_masquerading_as_an_image_is_rejected(self):
        with self.assertRaises(assets.AssetError) as ctx:
            assets.fetch(self.site.url("/fake.png"), task_id=self.task)
        self.assertIn("HTML", str(ctx.exception))

    def test_c12_corrupted_image_is_rejected(self):
        broken = self.temp / "broken.png"
        broken.write_bytes(BROKEN)
        with self.assertRaises(assets.AssetError):
            assets.import_local(str(broken), task_id=self.task)

    def test_c13_size_limit_is_enforced(self):
        with self.assertRaises(assets.AssetError) as ctx:
            assets.fetch(self.site.url("/huge.bin"), task_id=self.task,
                         expect="document", max_bytes=10_000)
        self.assertIn("limit", str(ctx.exception))

    def test_c14_collection_preserves_provenance(self):
        self.load("/")
        collected = collector.collect_image(
            self.service, self.tab, self.site.url("/big.png"),
            task_id=self.task, license_status="open-licence",
            attribution="Test Fixtures CC0")
        self.assertTrue(collected["ok"], collected)
        asset = library.get_asset(collected["asset"]["asset_id"])
        self.assertEqual(asset["source_url"], self.site.url("/big.png"))
        self.assertEqual(asset["page_url"], self.site.url("/"))
        self.assertEqual(asset["task_id"], self.task)
        self.assertEqual(asset["sha256"], hashlib.sha256(BIG).hexdigest())

    def test_c15_attribution_is_kept(self):
        self.load("/")
        collected = collector.collect_image(
            self.service, self.tab, self.site.url("/pixel.png"),
            task_id=self.task, attribution="Someone, CC BY 4.0")
        self.assertEqual(collected["asset"]["attribution"], "Someone, CC BY 4.0")

    def test_c16_unknown_licence_is_explicit(self):
        self.load("/")
        collected = collector.collect_image(
            self.service, self.tab, self.site.url("/pixel.png"),
            task_id=self.task)
        self.assertEqual(collected["asset"]["license_status"], "unknown")
        self.assertFalse(collected["asset"]["approved"])

    def test_c17_assets_are_not_approved_automatically(self):
        self.load("/")
        collected = collector.collect_image(
            self.service, self.tab, self.site.url("/pixel.png"),
            task_id=self.task, license_status="do-not-reuse")
        self.assertFalse(collected["asset"]["approved"])
        approved = library.approve_asset(collected["asset"]["asset_id"], True)
        self.assertTrue(approved["approved"])

    def test_c18_duplicate_content_reuses_the_existing_record(self):
        self.load("/")
        first = collector.collect_image(
            self.service, self.tab, self.site.url("/pixel.png"),
            task_id=self.task)
        second = collector.collect_image(
            self.service, self.tab, self.site.url("/pixel.png"),
            task_id=self.task)
        self.assertEqual(first["asset"]["asset_id"], second["asset"]["asset_id"])
        self.assertEqual(len(library.list_assets(self.task)), 1)

    def test_c19_collected_image_can_be_previewed(self):
        self.load("/")
        collected = collector.collect_image(
            self.service, self.tab, self.site.url("/big.png"),
            task_id=self.task)
        from PyQt6.QtGui import QPixmap
        pixmap = QPixmap(collected["asset"]["path"])
        self.assertFalse(pixmap.isNull())
        self.assertEqual(pixmap.width(), 800)

    def test_c20_library_bytes_match_the_download(self):
        self.load("/")
        collected = collector.collect_image(
            self.service, self.tab, self.site.url("/big.png"),
            task_id=self.task)
        record = library.get_asset(collected["asset"]["asset_id"])
        on_disk = Path(record["path"]).read_bytes()
        self.assertEqual(hashlib.sha256(on_disk).hexdigest(), record["sha256"])
        self.assertEqual(len(on_disk), record["size_bytes"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
