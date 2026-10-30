"""Regression tests for core/repo_index.py and the repo_inspect tool.

What is being protected:

    * the index actually parses Python (symbols, line numbers, imports) rather
      than grepping;
    * build output, virtualenvs and caches are skipped, so an agent is not told
      that `node_modules` is part of the project;
    * credentials are never indexed, searched or returned — the audit found
      plaintext keys on disk, and a code-intelligence tool must not become the
      thing that reads them into a prompt;
    * the declaration/handler contract holds: every declared tool has a
      handler, so no route can end in "Unknown tool".

Run: python -m unittest qa_artifacts.regression_tests.test_repo_index -v
"""

from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from core import repo_index  # noqa: E402


def _project(root: Path) -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "core.py").write_text(textwrap.dedent('''
        """The core module."""
        import os
        from pkg import utils

        CONSTANT = 1

        class Engine:
            """Runs things."""

            def start(self):
                return utils.helper()

        def helper_two(value):
            """Second helper."""
            return value * 2
    '''), encoding="utf-8")
    (root / "pkg" / "utils.py").write_text(textwrap.dedent('''
        def helper():
            return "ok"
    '''), encoding="utf-8")
    (root / "app.py").write_text(
        "from pkg.core import Engine\n\nif __name__ == '__main__':\n    Engine().start()\n",
        encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text("def test_x():\n    assert True\n",
                                                encoding="utf-8")
    # things that must be skipped
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "junk.py").write_text("x = 1\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "lib.js").write_text("var x = 1;\n", encoding="utf-8")
    (root / "dist").mkdir()
    (root / "dist" / "bundle.js").write_text("var y = 2;\n", encoding="utf-8")
    # credentials that must never be read
    (root / ".env").write_text("GEMINI_API_KEY=SECRETVALUE\n", encoding="utf-8")
    (root / "api_keys.json").write_text('{"gemini_api_key": "SECRETVALUE"}',
                                        encoding="utf-8")
    (root / "server.pem").write_text("-----BEGIN PRIVATE KEY-----\n",
                                     encoding="utf-8")


class TestInventory(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _project(self.root)
        self.index = repo_index.build(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_source_files_are_indexed(self):
        for rel in ("app.py", "pkg/core.py", "pkg/utils.py", "pkg/__init__.py"):
            self.assertIn(rel, self.index.files, rel)

    def test_build_output_and_caches_are_skipped(self):
        indexed = set(self.index.files)
        for unwanted in ("__pycache__/junk.py", "node_modules/lib.js",
                         "dist/bundle.js"):
            self.assertNotIn(unwanted, indexed, f"{unwanted} is not project source")

    def test_credentials_are_never_indexed(self):
        for secret in (".env", "api_keys.json", "server.pem"):
            self.assertNotIn(secret, self.index.files, f"{secret} was indexed")

    def test_language_and_line_counts(self):
        entry = self.index.files["pkg/core.py"]
        self.assertEqual(entry.language, "python")
        self.assertGreater(entry.lines, 5)

    def test_test_files_are_recognised(self):
        self.assertEqual([t.path for t in self.index.tests()], ["tests/test_app.py"])

    def test_summary_is_human_readable(self):
        text = self.index.summary()
        self.assertIn("Files indexed", text)
        self.assertIn("python", text)
        self.assertNotIn("SECRETVALUE", text)


class TestSymbols(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _project(self.root)
        self.index = repo_index.build(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_class_and_methods_are_found_with_lines(self):
        engine = self.index.find_symbol("Engine")
        self.assertTrue(engine)
        self.assertEqual(engine[0].kind, "class")
        self.assertGreater(engine[0].line, 0)
        start = self.index.find_symbol("start")
        self.assertEqual(start[0].kind, "method")
        self.assertEqual(start[0].parent, "Engine")
        self.assertEqual(start[0].qualified(), "Engine.start")

    def test_functions_and_docstrings(self):
        found = self.index.find_symbol("helper_two")
        self.assertEqual(found[0].kind, "function")
        self.assertEqual(found[0].doc, "Second helper.")

    def test_imports_include_from_import_names(self):
        mods = self.index.imports["pkg/core.py"]
        self.assertIn("os", mods)
        self.assertIn("pkg.utils", mods)

    def test_who_imports(self):
        users = self.index.who_imports("pkg.utils")
        self.assertIn("pkg/core.py", users)
        callers = self.index.who_imports("Engine")
        self.assertIn("app.py", callers)

    def test_context_for_lists_symbols_not_contents(self):
        text = self.index.context_for("pkg/core.py")
        self.assertIn("class Engine", text)
        self.assertNotIn("CONSTANT = 1", text)


class TestSearch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _project(self.root)
        self.index = repo_index.build(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_search_reports_enclosing_symbol(self):
        hits = repo_index.search(self.index, "return value * 2")
        self.assertTrue(hits)
        self.assertEqual(hits[0].path, "pkg/core.py")
        self.assertEqual(hits[0].symbol, "helper_two")

    def test_search_never_returns_credentials(self):
        hits = repo_index.search(self.index, "SECRETVALUE")
        self.assertEqual(hits, [], "search read a credential file")

    def test_regex_search(self):
        hits = repo_index.search(self.index, r"def\s+helper\w*", regex=True)
        self.assertGreaterEqual(len(hits), 1)

    def test_type_filter(self):
        hits = repo_index.search(self.index, "def", language="javascript")
        self.assertEqual(hits, [])

    def test_empty_pattern_is_empty_result(self):
        self.assertEqual(repo_index.search(self.index, ""), [])


class TestSecretPaths(unittest.TestCase):
    def test_known_secret_paths(self):
        for path in ("config/api_keys.json", ".env", ".env.local",
                     "config/secrets.enc", "config/certs/server.key",
                     "id_rsa", "cert.pem", "credentials.json"):
            self.assertTrue(repo_index.is_secret_path(path), path)

    def test_ordinary_source_is_not_secret(self):
        for path in ("core/api_config.py", "docs/README.md",
                     "qa_artifacts/regression_tests/test_security.py"):
            self.assertFalse(repo_index.is_secret_path(path), path)


class TestRepoInspectTool(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _project(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _call(self, **params):
        from actions.repo_tool import repo_inspect
        return repo_inspect(params)

    def test_summary(self):
        out = self._call(action="summary", root=str(self.root))
        self.assertIn("Files indexed", out)

    def test_symbol(self):
        out = self._call(action="symbol", query="Engine", root=str(self.root))
        self.assertIn("class Engine", out)

    def test_imports(self):
        out = self._call(action="imports", query="pkg.utils", root=str(self.root))
        self.assertIn("pkg/core.py", out)

    def test_search(self):
        out = self._call(action="search", query="helper", root=str(self.root))
        self.assertIn("utils.py", out)

    def test_file(self):
        out = self._call(action="file", query="pkg/core.py", root=str(self.root))
        self.assertIn("defines:", out)

    def test_tests(self):
        out = self._call(action="tests", root=str(self.root))
        self.assertIn("test_app.py", out)

    def test_secret_file_is_refused(self):
        out = self._call(action="file", query="api_keys.json", root=str(self.root))
        self.assertIn("will not read", out)

    def test_unknown_action_is_reported(self):
        out = self._call(action="explode", root=str(self.root))
        self.assertIn("Unknown action", out)

    def test_missing_root_is_reported(self):
        out = self._call(action="summary", root="Z:/definitely/not/here")
        self.assertNotIn("Traceback", out)


class TestRegistryConsistency(unittest.TestCase):
    """A declared tool with no handler is a route that ends in 'Unknown tool'."""

    def test_every_declared_tool_has_a_handler(self):
        from core.tool_declarations import TOOL_DECLARATIONS
        from core.tool_registry import TOOL_HANDLERS
        from brain.tools import ToolRegistry

        # Tools main.py handles inline because they need session state.
        inline = {"save_memory", "screen_process", "close_camera", "web_search",
                  "system_status", "shutdown_keysai", "recall_memory", "undo",
                  "manage_monitor"}
        registry = ToolRegistry()
        missing = [d["name"] for d in TOOL_DECLARATIONS
                   if d["name"] not in TOOL_HANDLERS
                   and d["name"] not in inline
                   and not registry.has(d["name"])]
        self.assertEqual(missing, [], f"declared but unreachable: {missing}")

    def test_every_handler_is_declared(self):
        from core.tool_declarations import TOOL_DECLARATIONS
        from core.tool_registry import TOOL_HANDLERS
        declared = {d["name"] for d in TOOL_DECLARATIONS}
        undeclared = [name for name in TOOL_HANDLERS if name not in declared]
        self.assertEqual(undeclared, [], f"handled but not declared: {undeclared}")

    def test_repo_inspect_is_read_only_in_the_permission_config(self):
        import json
        cfg = json.loads((BASE / "config" / "brain.json").read_text(encoding="utf-8"))
        self.assertIn("repo_inspect", cfg["permissions"]["SAFE"])

    def test_unknown_tool_execution_is_a_failure(self):
        from brain.tools import ToolRegistry
        out = ToolRegistry().execute("definitely_not_a_tool", {})
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
