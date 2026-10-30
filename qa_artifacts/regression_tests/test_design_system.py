"""Tests for the design system and the objective design gate.

The design system must produce tokens that pass WCAG on their own; the gate
must catch the failures a generated build actually makes, and must not invent
failures on good output. Both claims are tested here.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import design_check, design_system  # noqa: E402


class TestContrastMath(unittest.TestCase):
    def test_known_ratios(self):
        self.assertAlmostEqual(
            design_system.contrast_ratio("#000000", "#ffffff"), 21.0, places=2)
        self.assertAlmostEqual(
            design_system.contrast_ratio("#ffffff", "#000000"), 21.0, places=2)
        self.assertAlmostEqual(
            design_system.contrast_ratio("#777777", "#777777"), 1.0, places=2)

    def test_luminance_extremes(self):
        self.assertAlmostEqual(design_system.relative_luminance("#000000"), 0.0)
        self.assertAlmostEqual(design_system.relative_luminance("#ffffff"), 1.0)

    def test_three_digit_hex(self):
        self.assertEqual(design_system._hex_to_rgb("#fff"), (255, 255, 255))
        self.assertEqual(design_system._hex_to_rgb("abc"),
                         (0xaa, 0xbb, 0xcc))

    def test_bad_hex_raises(self):
        for bad in ("#12", "#12345", "rebeccapurple"):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    design_system._hex_to_rgb(bad)


class TestTokenGeneration(unittest.TestCase):
    def test_every_seed_kind_and_mood_passes_wcag(self):
        result = design_system.selftest()
        self.assertTrue(result["ok"], msg=f"{result['failures'][:3]}")
        self.assertGreaterEqual(result["checked"], 80)

    def test_deterministic(self):
        a = design_system.build_tokens("stock room", kind="web")
        b = design_system.build_tokens("stock room", kind="web")
        self.assertEqual(a.palette, b.palette)

    def test_different_briefs_look_different(self):
        a = design_system.build_tokens("stock room")
        b = design_system.build_tokens("space shooter")
        self.assertNotEqual(a.palette["accent"], b.palette["accent"])

    def test_explicit_hue_is_honoured(self):
        tokens = design_system.build_tokens("anything", hue=210)
        self.assertEqual(tokens.palette["accent"], 
                         design_system.build_tokens("anything", hue=210)
                         .palette["accent"])

    def test_css_round_trips_through_the_gate(self):
        tokens = design_system.build_tokens("inventory app")
        report = design_check.check_text("static/style.css", tokens.to_css())
        self.assertTrue(report.ok, msg=report.summary())
        self.assertIn("--bg:", tokens.to_css())

    def test_qt_theme_is_real_python(self):
        tokens = design_system.build_tokens("stock room", kind="python-desktop")
        source = tokens.to_qt_theme("Stock Room")
        namespace: dict = {}
        exec(compile(source, "theme.py", "exec"), namespace)  # noqa: S102
        for name in ("ACCENT", "BG", "PANEL", "INK", "MUTED", "LINE", "WARN"):
            self.assertIn(name, namespace, f"{name} missing from the theme")
        self.assertTrue(namespace["STYLESHEET"].strip())
        # The generated theme must itself pass the gate.
        report = design_check.check_text("app/theme.py", source)
        self.assertTrue(report.ok, msg=report.summary())

    def test_prompt_block_states_the_rules(self):
        block = design_system.build_tokens("x").to_prompt_block()
        self.assertIn("WCAG", block)
        self.assertIn("no lorem ipsum", block.lower())

    def test_kind_aliases(self):
        self.assertEqual(design_system.normalise_kind("pygame"), "game")
        self.assertEqual(design_system.normalise_kind("portfolio"), "web")
        self.assertEqual(design_system.normalise_kind("nonsense"), "web")
        self.assertIn("play field", design_system.layout_guidance("game"))


class TestDesignGate(unittest.TestCase):
    def _project(self, files: dict[str, str]) -> Path:
        root = Path(tempfile.mkdtemp(prefix="design_gate_"))
        for name, body in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        return root

    def test_good_project_passes(self):
        tokens = design_system.build_tokens("inventory")
        root = self._project({
            "index.html": f"<html><head><style>{tokens.to_css()}</style></head>"
                          "<body><h1>Stock room</h1></body></html>",
        })
        report = design_check.check_project(root)
        self.assertTrue(report.ok, msg=report.summary())
        self.assertEqual(len(report.checked_files), 1)

    def test_low_contrast_is_an_error(self):
        root = self._project({
            "index.html": "<html><head><style>:root { --bg: #ffffff; "
                          "--ink: #f0f0f0; }</style></head>"
                          "<body><h1>Hello</h1></body></html>",
        })
        report = design_check.check_project(root)
        self.assertFalse(report.ok)
        self.assertIn("contrast", [f.code for f in report.errors])

    def test_qt_theme_low_contrast_is_caught(self):
        root = self._project({"theme.py": 'BG = "#ffffff"\nINK = "#f4f4f4"\n'})
        report = design_check.check_project(root)
        self.assertFalse(report.ok)
        self.assertIn("contrast", [f.code for f in report.errors])

    def test_placeholders_are_errors(self):
        root = self._project({
            "index.html": "<html><body><h1>Lorem ipsum dolor</h1>"
                          "<p>TODO: write copy</p></body></html>",
        })
        codes = [f.code for f in design_check.check_project(root).errors]
        self.assertIn("placeholder", codes)

    def test_placeholder_attribute_is_not_copy(self):
        root = self._project({
            "index.html": '<html><body><input placeholder="Search stock">'
                          "<h1>Stock</h1></body></html>",
        })
        report = design_check.check_project(root)
        self.assertTrue(report.ok, msg=report.summary())

    def test_script_body_is_ignored(self):
        root = self._project({
            "index.html": "<html><body><script>var t = 'lorem ipsum';</script>"
                          "<h1>Stock</h1></body></html>",
        })
        self.assertTrue(design_check.check_project(root).ok)

    def test_missing_local_image_is_an_error(self):
        root = self._project({
            "index.html": '<html><body><img src="assets/nope.png"></body></html>',
        })
        codes = [f.code for f in design_check.check_project(root).errors]
        self.assertIn("broken-image", codes)

    def test_remote_and_data_images_are_fine(self):
        root = self._project({
            "index.html": '<html><body><img src="https://x.test/a.png">'
                          '<img src="data:image/png;base64,AAA"></body></html>',
        })
        self.assertTrue(design_check.check_project(root).ok)

    def test_existing_local_image_passes(self):
        root = self._project({
            "index.html": '<html><body><img src="assets/logo.png"></body></html>',
            "assets/logo.png": "not really a png",
        })
        self.assertTrue(design_check.check_project(root).ok)

    def test_empty_project_fails_rather_than_passing(self):
        root = self._project({"README.md": "nothing here"})
        report = design_check.check_project(root)
        self.assertFalse(report.ok)
        self.assertIn("nothing-checked", [f.code for f in report.errors])

    def test_many_font_sizes_warn(self):
        rules = " ".join(f".s{i} {{ font-size: {10 + i}px; }}"
                         for i in range(10))
        report = design_check.check_text("style.css", rules)
        self.assertTrue(report.ok)
        self.assertIn("type-scale", [f.code for f in report.warnings])

    def test_off_scale_spacing_warns(self):
        css = ".a { padding: 7px; margin: 13px; gap: 19px; }"
        report = design_check.check_text("style.css", css)
        self.assertIn("spacing-scale", [f.code for f in report.warnings])

    def test_dead_links_warn(self):
        report = design_check.check_text(
            "index.html", '<html><body><a href="#">x</a></body></html>')
        self.assertIn("dead-link", [f.code for f in report.warnings])

    def test_non_theme_python_is_skipped(self):
        root = self._project({
            "app/window.py": 'BG = "#ffffff"\nINK = "#fafafa"\n',
        })
        # window.py is not a theme module, so it is not scanned for a palette.
        self.assertEqual(design_check.check_project(root).checked_files, [])

    def test_report_dict_shape(self):
        report = design_check.check_text(
            "style.css", ":root { --bg: #fff; --ink: #fefefe; }")
        payload = report.as_dict()
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["errors"])
        self.assertIn("message", payload["errors"][0])


class TestDesignResearch(unittest.TestCase):
    """A palette may only claim a reference if it sampled that reference."""

    def _image(self, rgb) -> Path:
        from PIL import Image
        path = Path(tempfile.mkdtemp(prefix="design_ref_")) / "ref.png"
        Image.new("RGB", (32, 32), rgb).save(path)
        return path

    def test_hue_comes_from_the_image(self):
        from core import design_research
        blue = self._image((47, 111, 237))
        tokens, prov = design_research.tokens_from_research(
            [blue], seed="stock dashboard")
        self.assertIsNotNone(prov["hue"])
        self.assertTrue(200 <= prov["hue"] <= 260, prov["hue"])
        self.assertEqual(prov["source"], "reference images")
        self.assertFalse(tokens.problems(), msg=tokens.problems())

    def test_a_grey_reference_falls_back_and_says_so(self):
        from core import design_research
        grey = self._image((128, 128, 128))
        tokens, prov = design_research.tokens_from_research([grey], seed="x")
        self.assertIsNone(prov["hue"])
        self.assertIn("brief", prov["source"])
        self.assertFalse(tokens.problems())

    def test_two_references_produce_different_hues(self):
        from core import design_research
        blue, orange = self._image((47, 111, 237)), self._image((232, 96, 60))
        _b, blue_prov = design_research.tokens_from_research([blue])
        _o, orange_prov = design_research.tokens_from_research([orange])
        self.assertNotEqual(blue_prov["hue"], orange_prov["hue"])

    def test_a_missing_file_is_not_claimed_as_a_reference(self):
        from core import design_research
        tokens, prov = design_research.tokens_from_research(
            ["/definitely/not/here.png"], seed="x")
        self.assertEqual(prov["images"], [])
        self.assertIsNone(prov["hue"])

    def test_the_brief_names_the_files_it_used(self):
        from core import design_research
        image = self._image((47, 111, 237))
        brief = design_research.design_research_brief([image], seed="x")
        self.assertIn("WHERE THESE COLOURS CAME FROM", brief)
        self.assertIn(image.name, brief)
        self.assertIn("Do not copy", brief)

    def test_selftest_passes(self):
        from core import design_research
        result = design_research.selftest()
        self.assertTrue(result["ok"], msg=result["failures"])


class TestRuntimeGate(unittest.TestCase):
    """The runtime check must see what source alone cannot."""

    @classmethod
    def setUpClass(cls):
        import base64
        import functools
        import threading
        from http.server import HTTPServer, SimpleHTTPRequestHandler

        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.root = Path(tempfile.mkdtemp(prefix="runtime_gate_"))
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
            "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        (cls.root / "good").mkdir()
        (cls.root / "bad").mkdir()
        (cls.root / "good" / "logo.png").write_bytes(png)
        (cls.root / "good" / "index.html").write_text(
            '<html><body><img src="logo.png"><h1>Fine</h1></body></html>',
            encoding="utf-8")
        (cls.root / "bad" / "index.html").write_text(
            '<html><body><img src="nope.png">'
            '<script>throw new Error("boom");</script>'
            '<script>console.error("logged");</script></body></html>',
            encoding="utf-8")

        handler = functools.partial(SimpleHTTPRequestHandler,
                                    directory=str(cls.root))
        cls.server = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_a_clean_page_passes(self):
        report = design_check.check_rendered(self.base + "/good/")
        self.assertTrue(report.ok, msg=report.summary())

    def test_a_missing_image_is_caught_at_runtime(self):
        report = design_check.check_rendered(self.base + "/bad/")
        self.assertFalse(report.ok)
        codes = [f.code for f in report.errors]
        self.assertIn("broken-image", codes)

    def test_uncaught_errors_and_console_errors_are_caught(self):
        report = design_check.check_rendered(self.base + "/bad/")
        messages = " | ".join(f.message for f in report.errors
                               if f.code == "console-error")
        self.assertIn("boom", messages)
        self.assertIn("logged", messages)

    def test_a_page_that_does_not_load_fails(self):
        import socket
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        report = design_check.check_rendered(
            f"http://127.0.0.1:{port}/", timeout=8.0, settle=200)
        self.assertFalse(report.ok)
        self.assertIn("load-failed", [f.code for f in report.errors])


if __name__ == "__main__":
    unittest.main(verbosity=2)
