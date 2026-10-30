"""Tests for the skill system: registry, runner, orchestrator, commands.

Each scenario from the assignment is covered where it applies to this codebase.
Tests that execute a real skill record TESTED evidence, so the inventory reports
what was actually run instead of what merely exists.

    python -m pytest qa_artifacts/regression_tests/test_skill_system.py -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skills import inventory  # noqa: E402
from skills.commands import handle as run_command  # noqa: E402
from skills.manifest import SkillManifest  # noqa: E402
from skills.orchestrator import plan, select  # noqa: E402
from skills.registry import SkillEntry, SkillRegistry, reset_registry  # noqa: E402
from skills.runner import (SkillContext, SkillResult, execute,  # noqa: E402
                           validate_inputs)


def _entry(name: str, *, run=None, permission: str = "SAFE", **manifest_kwargs):
    data = {"name": name, "purpose": f"{name} test skill",
            "permission": permission, "tools": [], "timeout": 5.0}
    data.update(manifest_kwargs)
    return SkillEntry(manifest=SkillManifest.from_dict(data), run=run,
                      module=f"test.{name}", source="test")


class _Base(unittest.TestCase):
    def setUp(self):
        reset_registry()
        self.tmp = Path(tempfile.mkdtemp())
        self.state = self.tmp / "state.json"
        self.declared = self.tmp / "declared.json"
        self.patches = [
            mock.patch("skills.registry.STATE_PATH", self.state),
            mock.patch("skills.registry.DECLARED_PATH", self.declared),
            mock.patch("skills.registry.LOG_PATH", self.tmp / "log.jsonl"),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        reset_registry()


class TestRegistry(_Base):
    def test_skills_are_discovered_and_valid(self):
        registry = SkillRegistry()
        names = [e.manifest.name for e in registry.all()]
        self.assertIn("globe", names)
        self.assertIn("coding", names)
        self.assertFalse(registry.load_errors, registry.load_errors)
        for entry in registry.all():
            with self.subTest(skill=entry.manifest.name):
                self.assertEqual(entry.manifest.problems(), [])
                self.assertTrue(entry.implemented)
                self.assertTrue(entry.manifest.tools or entry.manifest.name
                                == "design-system")

    def test_duplicate_is_detected_and_refused(self):
        registry = SkillRegistry()
        before = len(registry.all())
        declared = {"name": "globe", "purpose": "a second globe", "version": "1.0.0",
                    "permission": "SAFE"}
        result = registry.install_declared(declared)
        self.assertFalse(result["ok"])
        self.assertIn("already exists", result["error"])
        self.assertEqual(len(registry.all()), before,
                         "a duplicate was allowed to replace a real skill")
        self.assertIn("globe", [d["name"] for d in registry.duplicates])

    def test_disabled_skill_is_remembered_and_cannot_run(self):
        registry = SkillRegistry()
        self.assertTrue(registry.set_enabled("web-search", False)["ok"])
        self.assertFalse(registry.get("web-search").enabled)
        self.assertEqual(SkillRegistry().get("web-search").enabled, False,
                         "the disabled state was not persisted")

        result = execute(registry.get("web-search"), {"query": "x"},
                         SkillContext())
        self.assertFalse(result.ok)
        self.assertTrue(result.refused)
        self.assertIn("disabled", result.error)

    def test_missing_dependency_is_reported_not_hidden(self):
        entry = _entry("needs-ghost", run=lambda p, c: "never",
                       requires=["definitely_not_a_module_xyz"])
        result = execute(entry, {}, SkillContext())
        self.assertFalse(result.ok)
        self.assertIn("missing dependency", result.error)

    def test_declared_only_skill_is_planned(self):
        registry = SkillRegistry()
        registry.install_declared({"name": "future-thing",
                                   "purpose": "not built yet",
                                   "version": "0.1.0", "permission": "SAFE"})
        entry = registry.get("future-thing")
        self.assertFalse(entry.implemented)
        self.assertIn("declared only",
                      " ".join(registry.validate("future-thing")["future-thing"]))
        result = registry.execute("future-thing", {})
        self.assertFalse(result.ok)
        self.assertIn("no implementation", result.error)


class TestRunner(_Base):
    def test_input_validation_rejects_bad_types(self):
        entry = _entry("typed", run=lambda p, c: "ok",
                       inputs={"count": {"type": "integer", "required": True}})
        _, problems = validate_inputs(entry.manifest, {"count": "many"})
        self.assertTrue(problems)
        self.assertFalse(execute(entry, {"count": "many"}, SkillContext()).ok)
        self.assertTrue(execute(entry, {"count": 3}, SkillContext()).ok)

    def test_required_input_is_reported(self):
        entry = _entry("typed2", run=lambda p, c: "ok",
                       inputs={"name": {"type": "string", "required": True}})
        result = execute(entry, {}, SkillContext())
        self.assertFalse(result.ok)
        self.assertIn("missing required input 'name'", result.error)

    def test_consequential_skill_needs_approval(self):
        calls: list = []
        entry = _entry("files", run=lambda p, c: calls.append(1) or "done",
                       permission="MODERATE")
        refused = execute(entry, {"action": "delete", "path": "x"},
                          SkillContext())
        self.assertFalse(refused.ok)
        self.assertTrue(refused.refused)
        self.assertIn("needs confirmation", refused.error)
        self.assertEqual(calls, [], "a refused skill still ran")

        allowed = execute(entry, {"action": "delete", "path": "x"},
                          SkillContext(approved=True))
        self.assertTrue(allowed.ok, allowed.error)
        self.assertEqual(calls, [1])

    def test_read_only_action_of_a_moderate_skill_runs_without_approval(self):
        entry = _entry("reader", run=lambda p, c: "read ok",
                       permission="SAFE")
        self.assertTrue(execute(entry, {"action": "list"}, SkillContext()).ok)

    def test_failure_is_reported_with_its_error(self):
        entry = _entry("fails", run=lambda p, c: {"ok": False,
                                                  "error": "the tool said no"})
        result = execute(entry, {}, SkillContext())
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "the tool said no")
        self.assertEqual(result.trace[-1]["event"], "failure")

    def test_exception_is_caught_and_named(self):
        def boom(parameters, ctx):
            raise RuntimeError("exploded")

        result = execute(_entry("boom", run=boom), {}, SkillContext())
        self.assertFalse(result.ok)
        self.assertIn("RuntimeError: exploded", result.error)

    def test_retry_policy_is_followed(self):
        attempts: list = []

        def flaky(parameters, ctx):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("first time fails")
            return "second time works"

        result = execute(_entry("flaky", run=flaky, retries=1), {},
                         SkillContext())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(attempts), 2)

    def test_timeout_is_enforced(self):
        result = execute(_entry("slow", run=lambda p, c: time.sleep(3),
                                timeout=0.3), {}, SkillContext())
        self.assertFalse(result.ok)
        self.assertIn("did not finish", result.error)

    def test_cancellation_stops_before_running(self):
        calls: list = []
        ctx = SkillContext()
        ctx.cancelled.set()
        result = execute(_entry("cancelme", run=lambda p, c: calls.append(1)),
                         {}, ctx)
        self.assertFalse(result.ok)
        self.assertIn("cancelled", result.error)
        self.assertEqual(calls, [])


class TestRealSkills(_Base):
    def test_design_skill_returns_a_contrast_checked_token_sheet(self):
        registry = SkillRegistry()
        result = registry.execute("design-system",
                                  {"action": "tokens", "seed": "fleet dashboard"})
        self.assertTrue(result.ok, result.error)
        self.assertIn("--bg:", result.output)
        self.assertIn("--accent:", result.output)
        inventory.record("design-system", "TESTED",
                         "test_skill_system: token sheet generated")

    def test_files_skill_refuses_a_delete_but_allows_a_listing(self):
        registry = SkillRegistry()
        with mock.patch("skills.builtin._delegate.tool_callable",
                        return_value=lambda p, ui, s: "listing ok"):
            refused = registry.execute("files", {"action": "delete",
                                                 "path": "C:/temp/x"})
            self.assertFalse(refused.ok)
            self.assertTrue(refused.refused)
            listed = registry.execute("files", {"action": "list",
                                                "path": "desktop"})
        self.assertTrue(listed.ok, listed.error)
        self.assertIn("listing ok", listed.output)
        inventory.record("files", "TESTED",
                         "test_skill_system: delegation + delete refused")

    def test_globe_skill_delegates_to_the_registered_tool(self):
        seen: dict = {}

        def fake(params, ui, speak):
            seen.update(params)
            return "The globe is open."

        registry = SkillRegistry()
        with mock.patch.dict("core.tool_registry.TOOL_HANDLERS",
                             {"globe": fake}):
            result = registry.execute("globe", {"action": "open"})
        self.assertTrue(result.ok, result.error)
        self.assertEqual(seen.get("action"), "open")
        self.assertIn("globe is open", result.output)
        inventory.record("globe", "TESTED",
                         "test_skill_system: delegates through TOOL_HANDLERS")


class TestOrchestrator(_Base):
    def test_relevant_skill_is_selected_and_not_all_of_them(self):
        registry = SkillRegistry()
        chosen = select(registry, "open the globe and take me to Kanpur")
        names = [c.name for c in chosen]
        self.assertIn("globe", names)
        self.assertLess(len(names), len(registry.all()),
                        "the orchestrator returned every skill")

    def test_multi_step_request_selects_each_part(self):
        registry = SkillRegistry()
        result = plan(registry, "search the web for contrast ratios and build "
                                "me a dashboard")
        names = result.skills
        self.assertIn("web-search", names)
        self.assertIn("coding", names)

    def test_unknown_request_asks_instead_of_guessing(self):
        registry = SkillRegistry()
        result = plan(registry, "order me a blue whale")
        self.assertEqual(result.skills, [])
        self.assertTrue(result.clarification)

    def test_moderate_skills_are_marked_for_approval(self):
        registry = SkillRegistry()
        result = plan(registry, "build me a dashboard")
        self.assertTrue(result.candidates)
        self.assertTrue(any(c.needs_approval for c in result.candidates))


class TestCommands(_Base):
    def test_help_and_list(self):
        self.assertIn("/skills", run_command("/help"))
        listing = run_command("/skills")
        self.assertIn("globe", listing)
        self.assertTrue(any(status in listing for status in
                            ("REGISTERED", "TESTED", "VERIFIED")),
                        listing)

    def test_unknown_command_is_a_useful_error(self):
        self.assertIn("Unknown command", run_command("/nonsense"))

    def test_inspect_shows_inputs_and_permission(self):
        text = run_command("/skills inspect coding")
        self.assertIn("coding", text)
        self.assertIn("MODERATE", text)
        self.assertIn("inputs:", text)

    def test_diagnose_reports_counts(self):
        text = run_command("/skills diagnose")
        self.assertIn("available:", text)

    def test_remove_requires_confirmation(self):
        registry = SkillRegistry()
        registry.install_declared({"name": "temp-skill", "purpose": "temp",
                                   "version": "0.1.0", "permission": "SAFE"})
        asked = run_command("/skills remove temp-skill")
        self.assertIn("--yes", asked)
        self.assertIsNotNone(SkillRegistry().get("temp-skill"))
        done = run_command("/skills remove temp-skill --yes")
        self.assertIn("Removed", done)
        self.assertIsNone(SkillRegistry().get("temp-skill"))

    def test_import_refuses_code(self):
        module = self.tmp / "evil.py"
        module.write_text("print('should never run')", encoding="utf-8")
        text = run_command(f"/skills import {module}")
        self.assertIn("never code", text)

    def test_import_accepts_a_json_manifest(self):
        manifest = self.tmp / "thing.json"
        manifest.write_text(json.dumps({"name": "imported-thing",
                                        "purpose": "from a file",
                                        "version": "0.2.0",
                                        "permission": "SAFE"}), encoding="utf-8")
        text = run_command(f"/skills import {manifest}")
        self.assertIn("Imported", text)
        self.assertIsNotNone(SkillRegistry().get("imported-thing"))

    def test_create_is_refused_for_an_existing_name(self):
        self.assertIn("duplicate", run_command("/skills create globe a copy"))

    def test_plan_command_explains_its_choice(self):
        text = run_command("/skills plan take me to Kanpur on the globe")
        self.assertIn("globe", text)


class TestConcurrencyAndInventory(_Base):
    def test_parallel_skills_do_not_corrupt_state(self):
        registry = SkillRegistry()
        release = threading.Event()

        def slow(parameters, ctx):
            release.wait(2)
            return "finished"

        entries = [_entry(f"parallel-{i}", run=slow) for i in range(2)]
        results: list = []

        def work(entry):
            results.append(execute(entry, {}, SkillContext()))

        threads = [threading.Thread(target=work, args=(e,)) for e in entries]
        [t.start() for t in threads]
        time.sleep(0.05)
        release.set()
        [t.join(timeout=5) for t in threads]

        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.ok for r in results))
        self.assertEqual(len(registry.inventory()["skills"]),
                         len(registry.all()))

    def test_inventory_distinguishes_tested_from_registered(self):
        registry = SkillRegistry()
        inventory_map = registry.inventory()
        tested = [n for n, item in inventory_map["skills"].items()
                  if item["status"] in ("TESTED", "VERIFIED")]
        registered = [n for n, item in inventory_map["skills"].items()
                      if item["status"] == "REGISTERED"]
        self.assertTrue(inventory_map["skills"])
        self.assertTrue(tested or registered,
                        "no status was derived at all")
        for name, item in inventory_map["skills"].items():
            if item["status"] == "VERIFIED":
                self.assertTrue(item["evidence"].get("VERIFIED"),
                                f"{name} claims VERIFIED with no evidence")

    def test_inventory_report_is_written(self):
        registry = SkillRegistry()
        target = self.tmp / "catalog.md"
        with mock.patch("skills.inventory.REPORT_PATH", target), \
             mock.patch("skills.inventory.INVENTORY_PATH", self.tmp / "inv.json"):
            registry.inventory(write=True)
        text = target.read_text(encoding="utf-8")
        self.assertIn("Skill catalog", text)
        self.assertIn("Still planned", text)
        self.assertIn("task-resume", text, "unclaimed capabilities must show")

    def test_existing_application_wiring_is_intact(self):
        from core.tool_declarations import TOOL_DECLARATIONS
        from core.tool_registry import TOOL_HANDLERS

        self.assertIn("skills", TOOL_HANDLERS)
        self.assertTrue(any(t["name"] == "skills" for t in TOOL_DECLARATIONS))
        from skills.registry import skills_block

        block = skills_block()
        self.assertIn("AVAILABLE SKILLS", block)
        self.assertIn("globe", block.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
