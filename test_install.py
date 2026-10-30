"""Tests for install.py — scaffolding safety and template validity.

The installer must NEVER overwrite existing config (e.g. a user's real API
keys) and every template it writes must parse as valid JSON.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import install

EXPECTED_SCAFFOLD_FILES = (
    "api_keys.json", "call_rules.json", "agent_control.json",
    "brain.json", "entities.json", "personality.json",
    "session_state.json", "window_state.json",
)


class ScaffoldTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_scaffold_creates_all_files_and_certs_dir(self):
        created = install.scaffold_configs(self.base)
        for name in EXPECTED_SCAFFOLD_FILES:
            self.assertTrue((self.base / "config" / name).exists(),
                            f"missing config/{name}")
        self.assertTrue((self.base / "config" / "certs").is_dir())
        # every created file is reported
        self.assertEqual(len(created), len(EXPECTED_SCAFFOLD_FILES))

    def test_all_templates_parse_as_valid_json(self):
        install.scaffold_configs(self.base)
        for name in EXPECTED_SCAFFOLD_FILES:
            p = self.base / "config" / name
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertIsInstance(data, dict, f"{name} should be a JSON object")

    def test_never_overwrites_existing_config(self):
        cfg = self.base / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        sentinel = {"gemini_api_key": "MY-REAL-KEY", "os_system": "windows"}
        (cfg / "api_keys.json").write_text(json.dumps(sentinel), encoding="utf-8")
        install.scaffold_configs(self.base)
        self.assertEqual(
            json.loads((cfg / "api_keys.json").read_text(encoding="utf-8")),
            sentinel, "existing api_keys.json must not be touched")

    def test_api_keys_template_has_expected_shape(self):
        self.assertIn("gemini_api_key", install.API_KEYS_TEMPLATE)
        self.assertIn("os_system", install.API_KEYS_TEMPLATE)
        self.assertIn("google_oauth_client_id", install.API_KEYS_TEMPLATE)
        self.assertIn("firebase_project_id", install.API_KEYS_TEMPLATE)
        self.assertEqual(install.API_KEYS_TEMPLATE["gemini_api_key"], "")

    def test_scaffold_is_idempotent(self):
        first = install.scaffold_configs(self.base)
        second = install.scaffold_configs(self.base)
        self.assertEqual(len(second), 0, "second run should create nothing")


class InstallerSmokeTest(unittest.TestCase):
    def test_flags_parse(self):
        args = install.build_parser().parse_args(["--doctor"])
        self.assertTrue(args.doctor)
        args = install.build_parser().parse_args(
            ["--no-venv", "--skip-deps", "--skip-playwright",
             "--skip-scaffold", "--quiet", "--test"])
        self.assertTrue(args.no_venv and args.skip_deps and args.skip_playwright
                        and args.skip_scaffold and args.quiet and args.test)

    def test_doctor_returns_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            code = install.doctor(Path(td))
        self.assertIn(code, (0, 1))   # never raises, reports health


if __name__ == "__main__":
    unittest.main()
