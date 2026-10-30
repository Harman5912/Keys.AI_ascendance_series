"""Group C — software construction, inspection and repair.

The software worker is tested through its real code path with an injected
builder: the same function the service calls with Crown Code in production.
That keeps every test deterministic while exercising the parts that matter —
the project workspace, the file scan, the artifact registry and the validators
that decide whether a build may be reported as complete.

Crown Code itself is not mocked into a model: these tests never claim a model
built a site. They prove what the worker accepts, rejects and records.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from universal_agent import security, validation  # noqa: E402
from universal_agent.workers import Context  # noqa: E402
from universal_agent.workers import software as sw  # noqa: E402

_INDEX = "<!doctype html><html><body><h1>Ada — photographer</h1></body></html>"
_CSS = "body { font-family: Georgia, serif; }"
_README = "# Portfolio\n\nOpen index.html in a browser to view the site.\n"


def _write(project: Path, files: dict) -> None:
    for name, text in files.items():
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ua_sw_"))
        self.workspace = self.tmp / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ctx(self, request: str, builder=None, params=None) -> Context:
        task = {"id": "t1", "request": request, "answers": {}, "plan": [],
                "artifacts": []}
        return Context(task=task, workspace=self.workspace,
                       params=params or {}, build_project=builder)

    def builder(self, files: dict, ok: bool = True, error: str = "",
                summary: str = "", workspace: str = ""):
        def build(job):
            project = Path(job["workspace"])
            if ok:
                _write(project, files)
            return {"ok": ok,
                    "workspace": workspace or str(project),
                    "summary": summary or "Built the project.",
                    "error": error}
        return build

    def paths(self, result: dict) -> set[str]:
        return {Path(a["path"]).name for a in result["artifacts"]}


class TestSoftwareBuild(_Base):
    def test_clear_brief_builds_a_valid_project(self):
        result = sw.run(self.ctx("Build a portfolio site for Ada",
                                 self.builder({"index.html": _INDEX,
                                               "style.css": _CSS,
                                               "README.md": _README})))
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(self.paths(result),
                         {"index.html", "style.css", "README.md"})
        for artifact in result["artifacts"]:
            check = validation.validate_artifact(artifact["path"], self.workspace)
            self.assertTrue(check["ok"], check["detail"])

    def test_unspecified_noncritical_preference_still_builds(self):
        # The brief names no colour scheme; the builder picks one and the worker
        # must not block on it.
        result = sw.run(self.ctx("Build a portfolio",
                                 self.builder({"index.html": _INDEX,
                                               "README.md": _README})))
        self.assertTrue(result["ok"], result["error"])
        self.assertIn("index.html", self.paths(result))

    def test_project_gets_its_own_folder_from_the_request(self):
        result = sw.run(self.ctx("Build a portfolio for Ada",
                                 self.builder({"index.html": _INDEX})))
        folder = Path(result["artifacts"][0]["path"]).parent
        self.assertEqual(folder.parent, self.workspace)
        self.assertIn("portfolio", folder.name.lower())

    def test_multi_file_frontend_is_fully_registered(self):
        files = {"index.html": _INDEX, "css/site.css": _CSS,
                 "js/app.js": "console.log('ready');\n",
                 "README.md": _README}
        result = sw.run(self.ctx("Build a website", self.builder(files)))
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["artifacts"]), 4)

    def test_startup_instructions_are_delivered(self):
        result = sw.run(self.ctx("Build a portfolio",
                                 self.builder({"index.html": _INDEX,
                                               "README.md": _README})))
        readme = [a for a in result["artifacts"]
                  if Path(a["path"]).name == "README.md"]
        self.assertTrue(readme)
        text = Path(readme[0]["path"]).read_text(encoding="utf-8")
        self.assertIn("index.html", text)

    def test_artifacts_live_inside_the_workspace(self):
        result = sw.run(self.ctx("Build a page",
                                 self.builder({"index.html": _INDEX})))
        for artifact in result["artifacts"]:
            self.assertTrue(
                security.is_within(artifact["path"], self.workspace))

    def test_existing_unrelated_file_is_preserved(self):
        keep = self.workspace / "notes-from-user.txt"
        keep.write_text("Do not delete this.\n", encoding="utf-8")
        result = sw.run(self.ctx("Build a page",
                                 self.builder({"index.html": _INDEX})))
        self.assertTrue(result["ok"])
        self.assertTrue(keep.is_file())
        self.assertNotIn("notes-from-user.txt", self.paths(result))

    def test_edit_in_place_keeps_other_project_files(self):
        project = self.workspace / "portfolio"
        project.mkdir()
        _write(project, {"index.html": _INDEX, "about.html": "<html></html>"})

        def editor(job):
            target = Path(job["workspace"]) / "index.html"
            target.write_text(_INDEX.replace("Ada", "Ada Lovelace"),
                              encoding="utf-8")
            return {"ok": True, "workspace": str(target.parent),
                    "summary": "Edited index.html"}

        result = sw.run(self.ctx("Build a portfolio", editor))
        self.assertTrue(result["ok"])
        text = (project / "index.html").read_text(encoding="utf-8")
        self.assertIn("Ada Lovelace", text)
        self.assertTrue((project / "about.html").is_file())

    def test_empty_files_are_not_registered(self):
        result = sw.run(self.ctx("Build a page",
                                 self.builder({"index.html": _INDEX,
                                               "empty.css": ""})))
        self.assertTrue(result["ok"])
        self.assertEqual(self.paths(result), {"index.html"})

    def test_dependency_and_build_folders_are_skipped(self):
        files = {"index.html": _INDEX,
                 "node_modules/lib/index.js": "x();\n",
                 ".git/config": "[core]\n"}
        result = sw.run(self.ctx("Build a page", self.builder(files)))
        self.assertTrue(result["ok"])
        self.assertEqual(self.paths(result), {"index.html"})

    def test_oversized_file_is_skipped(self):
        original = sw._MAX_FILE_BYTES
        sw._MAX_FILE_BYTES = 512
        try:
            result = sw.run(self.ctx("Build a page",
                                     self.builder({"index.html": _INDEX,
                                                   "bundle.js": "x" * 4096})))
        finally:
            sw._MAX_FILE_BYTES = original
        self.assertTrue(result["ok"])
        self.assertNotIn("bundle.js", self.paths(result))


class TestSoftwareFailures(_Base):
    def test_builder_failure_is_reported_not_hidden(self):
        result = sw.run(self.ctx("Build an app",
                                 self.builder({}, ok=False,
                                              error="tests failed: 2 assertions")))
        self.assertFalse(result["ok"])
        self.assertIn("tests failed", result["error"])
        self.assertFalse(result["artifacts"])

    def test_success_with_no_files_is_rejected(self):
        result = sw.run(self.ctx("Build an app", self.builder({})))
        self.assertFalse(result["ok"])
        self.assertIn("no file", result["summary"].lower())

    def test_builder_writing_outside_the_workspace_is_refused(self):
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        result = sw.run(self.ctx(
            "Build an app",
            self.builder({"index.html": _INDEX}, workspace=str(outside))))
        self.assertFalse(result["ok"])
        self.assertIn("outside the task workspace", result["error"])

    def test_builder_exception_is_contained(self):
        def boom(_job):
            raise RuntimeError("toolchain exploded")

        result = sw.run(self.ctx("Build an app", boom))
        self.assertFalse(result["ok"])
        self.assertIn("toolchain exploded", result["error"])

    def test_missing_dependency_is_named(self):
        def missing(_job):
            raise ModuleNotFoundError("No module named 'vite'")

        result = sw.run(self.ctx("Build a frontend", missing))
        self.assertFalse(result["ok"])
        self.assertIn("vite", result["error"])

    def test_python_syntax_error_is_detected_by_the_validator(self):
        result = sw.run(self.ctx("Build a script",
                                 self.builder({"run.py": "def broken(:\n"})))
        # The worker itself only reports files; the validator is what catches
        # the defect, and it must do so rather than trusting the builder.
        self.assertTrue(result["ok"])
        check = validation.validate_artifact(
            result["artifacts"][0]["path"], self.workspace)
        self.assertFalse(check["ok"])
        self.assertIn("could not be reopened", check["detail"])

    def test_repaired_syntax_error_then_passes(self):
        broken = sw.run(self.ctx("Build a script",
                                 self.builder({"run.py": "def broken(:\n"})))
        # The repair happens in a fresh attempt workspace, so the first build's
        # file is still there to compare against.
        second = self.tmp / "retry"
        second.mkdir()
        applied = sw.run(Context(
            task={"id": "t2", "request": "Build a script", "answers": {},
                  "plan": [], "artifacts": []},
            workspace=second,
            build_project=self.builder({"run.py": "def ok():\n    return 1\n"})))
        self.assertTrue(broken["ok"] and applied["ok"])
        self.assertFalse(validation.validate_all(
            broken["artifacts"], self.workspace)["ok"])
        fixed = [a for a in applied["artifacts"]
                 if a["path"].endswith("run.py")]
        self.assertTrue(fixed)
        self.assertTrue(validation.validate_artifact(
            fixed[0]["path"], second)["ok"])

    def test_validation_reports_every_broken_artifact(self):
        files = {"a.json": "{not json", "b.html": "plain text, no markup",
                 "c.md": "fine, this markdown has enough characters in it."}
        result = sw.run(self.ctx("Build a site", self.builder(files)))
        report = validation.validate_all(result["artifacts"], self.workspace)
        self.assertFalse(report["ok"])
        self.assertEqual(len(report["failures"]), 2)

    def test_build_notes_are_carried_into_the_result(self):
        def with_notes(job):
            _write(Path(job["workspace"]), {"index.html": _INDEX})
            return {"ok": True, "workspace": job["workspace"],
                    "notes": ["Node was unavailable; served with Python"]}

        result = sw.run(self.ctx("Build a page", with_notes))
        self.assertTrue(result["ok"])
        self.assertIn("Python", " ".join(result["notes"]))

    def test_cancellation_is_honoured_before_the_build(self):
        calls = []

        def builder(job):
            calls.append(job)
            return {"ok": True, "workspace": job["workspace"]}

        ctx = self.ctx("Build a page", builder)
        ctx.should_cancel = lambda: True
        result = sw.run(ctx)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "cancelled")
        self.assertFalse(calls)
        self.assertFalse(list(self.workspace.iterdir()))


class TestSoftwareDelivery(_Base):
    def test_result_summary_states_what_was_built(self):
        result = sw.run(self.ctx(
            "Build a portfolio",
            self.builder({"index.html": _INDEX}, summary="Portfolio ready")))
        self.assertEqual(result["summary"], "Portfolio ready")

    def test_file_sizes_are_recorded(self):
        result = sw.run(self.ctx("Build a page",
                                 self.builder({"index.html": _INDEX})))
        detail = result["artifacts"][0]["detail"]
        self.assertIn("bytes", detail)

    def test_html_without_structure_fails_validation(self):
        result = sw.run(self.ctx("Build a page",
                                 self.builder({"index.html": "just words\n"})))
        check = validation.validate_artifact(
            result["artifacts"][0]["path"], self.workspace)
        self.assertFalse(check["ok"])

    def test_artifact_path_traversal_is_never_registered(self):
        # A builder that reports a workspace outside the task must not smuggle
        # a path into the artifact list.
        outside = Path(tempfile.mkdtemp(prefix="ua_sw_out_"))
        try:
            (outside / "leak.txt").write_text("secret\n", encoding="utf-8")
            result = sw.run(self.ctx(
                "Build a page",
                self.builder({"index.html": _INDEX}, workspace=str(outside))))
            self.assertFalse(result["ok"])
            self.assertEqual(result["artifacts"], [])
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_crown_code_absence_is_a_clear_failure(self):
        ctx = self.ctx("Build a page", None)   # no injected builder
        with self._patch_crown(raise_error=RuntimeError("crown unavailable")):
            result = sw.run(ctx)
        self.assertFalse(result["ok"])
        self.assertIn("unavailable", result["error"].lower())

    # ── helper ────────────────────────────────────────────────────────────
    def _patch_crown(self, raise_error=None):
        from unittest import mock
        import actions.crown_code as cc

        def fake(params):
            if raise_error:
                raise raise_error
            return "Crown Code is not configured for this test."

        return mock.patch.object(cc, "crown_code", fake)


if __name__ == "__main__":
    unittest.main(verbosity=2)
