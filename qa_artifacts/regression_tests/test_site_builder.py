"""Regression tests for core.site_builder / core.site_checks.

No model, no network, no browser: a fake provider stands in for Ollama so the
pipeline's decisions are deterministic.

Run:  python -m unittest qa_artifacts.regression_tests.test_site_builder -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
import shutil
import threading
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from core import site_builder as sb  # noqa: E402
from core.site_checks import (acceptance_checklist, check_html,  # noqa: E402
                              checklist_summary, repair_html)

PLAN = {
    "brand": "Arjun Mehta",
    "title": "Arjun Mehta — Full-stack developer",
    "eyebrow": "Full-stack developer",
    "headline": "I build small products that hold up in production",
    "tagline": "Six years shipping web apps for teams of three to thirty.",
    "accent": "#7bd4a4",
    "cta_primary": "See selected work",
    "cta_secondary": "Email me",
    "sections": [
        {"id": "about", "kind": "about", "heading": "About",
         "lead": "I work end to end, from schema to spacing.",
         "items": [{"title": "How I work", "text": "Weekly demos, written decisions."}]},
        {"id": "work", "kind": "projects", "heading": "Selected work",
         "lead": "Three recent builds.",
         "items": [{"title": "Relaydesk", "text": "Cut first response time to 4 minutes.",
                    "meta": "2025 · SaaS", "tags": ["React", "Postgres"]},
                   {"title": "Fieldnotes", "text": "Offline capture for 1,200 staff.",
                    "meta": "2024 · Mobile", "tags": ["Flutter"]},
                   {"title": "Ledger", "text": "Month-end close in four hours.",
                    "meta": "2024 · Data", "tags": ["Python"]}]},
        {"id": "skills", "kind": "skills", "heading": "Tools", "lead": "What I reach for.",
         "items": [{"title": "Python"}, {"title": "Postgres"}, {"title": "TypeScript"}]},
        {"id": "contact", "kind": "contact", "heading": "Contact", "lead": "Say hello.",
         "items": []},
    ],
    "metrics": [{"value": "6", "label": "years"}],
    "faq": [{"q": "Rates?", "a": "Weekly."}],
    "footer": "© Arjun Mehta",
}

GOOD_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arjun Mehta</title>
<style>
*,*::before,*::after{box-sizing:border-box}
body{margin:0;font-family:system-ui;background:#111;color:#eee;max-width:100%;overflow-x:hidden}
:focus-visible{outline:3px solid #7bd4a4}
header,main,footer{max-width:70ch;margin:auto;padding:1rem}
button,a{border-radius:8px;padding:.6rem 1rem}
img{max-width:100%;height:auto}
</style></head>
<body><header><nav><a href="#work">Work</a></nav></header>
<main id="main"><h1>Arjun Mehta builds small products that hold up</h1>
<p>Six years shipping web apps for teams of three to thirty, from schema to
spacing, with weekly demos and written decisions.</p>
<section id="work"><h2>Selected work</h2>
<button type="button" onclick="document.body.dataset.x=1">Filter work</button>
<p>Relaydesk cut first response time to four minutes. Fieldnotes gave 1,200
staff offline capture. Ledger closed month-end in four hours.</p>
<h3>Relaydesk</h3><p>A support inbox for teams of three to thirty. The old flow
routed every message through one queue, so first response times drifted past
an hour on busy Mondays. I rebuilt routing around owner tags and a single
shortcut bar, then measured the queue for six weeks. First response fell from
fifty-eight minutes to four, and the team stopped keeping a side spreadsheet.</p>
<h3>Fieldnotes</h3><p>Offline capture for twelve hundred field staff across three
regions. Sync had to survive long tunnels and a two-day battery. The build uses
a local queue with explicit conflict rules, a compact form that works one-handed,
and a review screen a supervisor can sign off in the field. Adoption reached
ninety-four percent in the first month without a training day.</p>
<h3>Ledger</h3><p>Month-end reconciliation used to take two days of copy and paste
between three systems. I modelled the accounts once, wrote a matching pass that
surfaces only the exceptions, and gave finance a four-hour close with an audit
trail for every adjustment.</p></section>
<section id="about"><h2>About</h2>
<p>I have spent six years on product teams of three to thirty people, mostly on
the parts nobody wants to own: the reconciliation job, the permission model,
the import that has to survive a half-broken CSV. The work I am proudest of is
boring in the best way — a release that goes out on a Thursday and nobody
notices, because the tests cover the ugly cases and the error messages tell you
what to do next.</p>
<p>My usual rhythm is a short discovery, a written plan with scope and
milestones, then weekly builds you can click. I keep a running decision log so
that in month three we still know why the queue is ordered that way, and I
hand over the code with a walkthrough rather than a folder of screenshots.</p>
<p>Recent work includes a support inbox where first response fell from
fifty-eight minutes to four, an offline capture app used by twelve hundred
field staff, and a finance close that went from two days to four hours. Earlier
roles covered a payments integration with an idempotency bug that only appeared
under retry storms, and a migration of forty-two services off a shared
scheduler.</p>
<p>When I am not shipping, I write about testing habits and maintain two small
open-source libraries for structured logging and CSV repair.</p></section>
<form><label for="email">Email</label><input id="email" type="email">
<button type="submit">Send</button></form></main>
<footer><p>© Arjun Mehta</p></footer></body></html>
"""

class FakeProvider:
    """Returns canned replies in order; records the prompts it was given.

    Implements the provider interface used by the builder: generate (plan) and
    stream (whole-file write), the latter delivering the reply in chunks like
    the real Ollama stream does.
    """

    def __init__(self, replies, chunk: int = 512):
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.chunk = chunk
        self.streamed_chars = 0

    def _next(self, prompt):
        self.prompts.append(prompt)
        reply = self.replies.pop(0) if self.replies else ""
        if isinstance(reply, Exception):
            raise reply
        return reply

    def generate(self, prompt, system=None, temperature=0.2, max_tokens=None):
        return self._next(prompt)

    def stream(self, prompt, system=None, on_token=None, temperature=0.2,
               max_tokens=None):
        text = self._next(prompt)
        self.streamed_chars += len(text)
        if on_token:
            for i in range(0, len(text), self.chunk):
                on_token(text[i:i + self.chunk])
        return text

class PlainProvider:
    """Provider with no streaming support — the builder must still work."""

    def __init__(self, replies):
        self.replies = list(replies)

    def generate(self, prompt, system=None, temperature=0.2, max_tokens=None):
        return self.replies.pop(0) if self.replies else ""

class BuilderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        try:
            self._tmp.cleanup()
        except OSError:
            shutil.rmtree(self._tmp.name, ignore_errors=True)

    def test_model_path_writes_verified_page(self):
        provider = FakeProvider([json.dumps(PLAN), GOOD_HTML])
        result = sb.build_site("Portfolio for Arjun Mehta", self.dir,
                               kind="portfolio", provider=provider, attempts=1,
                               speed="custom")
        self.assertTrue(result["ok"], result["attempts"])
        self.assertEqual(result["mode"], "model")
        self.assertFalse(result["used_fallback"])
        self.assertEqual(result["plan"]["brand"], "Arjun Mehta")
        self.assertEqual(result["model"], "")            # explicit provider, no name
        self.assertTrue((self.dir / "plan.json").exists())
        # the rendered page is kept next to it, ready to restore
        self.assertTrue((self.dir / "index.rendered.html").exists())

    def test_fast_mode_delivers_the_page_without_waiting_for_the_model(self):
        """Default speed: plan → render → verify. No writer call at all."""
        provider = FakeProvider([json.dumps(PLAN), GOOD_HTML])
        result = sb.build_site("Portfolio for Arjun Mehta", self.dir,
                               kind="portfolio", provider=provider)
        self.assertTrue(result["ok"], result["attempts"])
        self.assertEqual(result["mode"], "render")
        self.assertEqual(len(provider.prompts), 1, "fast mode must only plan")
        self.assertEqual(provider.replies, [GOOD_HTML], "fast mode consumed a write reply")
        html = (self.dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("Arjun Mehta", html)
        self.assertIn(":focus-visible", html)

    def test_garbage_planner_still_yields_a_working_page(self):
        provider = FakeProvider(["not json at all", "I cannot help with that."])
        result = sb.build_site("Portfolio for Arjun Mehta", self.dir,
                               kind="portfolio", provider=provider, attempts=2)
        self.assertTrue(result["ok"], result["checks"])
        self.assertEqual(result["mode"], "render")
        self.assertTrue(any("thin" in n or "built-in plan" in n for n in result["notes"]),
                        result["notes"])
        html = (self.dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("Arjun Mehta", html)
        self.assertIn(":focus-visible", html)

    def test_no_planner_available_still_produces_a_passing_page(self):
        # An offline machine must end with a working page plus an honest note,
        # not an exception and not an empty file.
        with mock.patch.object(sb, "_planner_provider",
                               side_effect=RuntimeError("no models")):
            result = sb.build_site("Landing page for a coffee roastery", self.dir,
                                   kind="website", attempts=1)
        ok, problems = check_html(self.dir / "index.html", "website")
        self.assertTrue(ok, problems)
        self.assertEqual(result["mode"], "render")
        self.assertTrue(any("no models" in n for n in result["notes"]), result["notes"])

    def test_cancelled_build_stops_before_rendering(self):
        provider = FakeProvider([json.dumps(PLAN), GOOD_HTML])
        result = sb.build_site("Portfolio", self.dir, kind="portfolio",
                               provider=provider, attempts=2,
                               cancelled=lambda: True)
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("cancelled"))
        self.assertFalse((self.dir / "index.html").exists())

    def test_write_is_streamed_and_reports_file_progress(self):
        provider = FakeProvider([json.dumps(PLAN), GOOD_HTML], chunk=256)
        seen: list[tuple] = []
        result = sb.build_site("Portfolio for Arjun Mehta", self.dir, kind="portfolio",
                               provider=provider, attempts=1, speed="custom",
                               on_phase=lambda name, pct, detail="": seen.append((name, pct, detail)))
        self.assertTrue(result["ok"], result["attempts"])
        self.assertGreaterEqual(provider.streamed_chars, len(GOOD_HTML))
        self.assertFalse(provider.replies, "the write reply was never consumed")
        # Streaming must drive the writing phase past its starting point, with a
        # detail line that names the real file percentage.
        writing = [p for n, p, d in seen if n == "writing" and "of the file" in d]
        self.assertTrue(writing, seen[:8])
        self.assertTrue(max(writing) > 0.2, writing)

    def test_provider_without_streaming_still_builds(self):
        provider = PlainProvider([json.dumps(PLAN), GOOD_HTML])
        result = sb.build_site("Portfolio for Arjun Mehta", self.dir, kind="portfolio",
                               provider=provider, attempts=1, speed="custom")
        self.assertTrue(result["ok"], result["attempts"])
        self.assertEqual(result["mode"], "model")

    def test_truncated_file_is_continued_not_restarted(self):
        truncated = GOOD_HTML.split("<body")[0] + "<body><h1>Partial"
        tail = GOOD_HTML.split("<body>", 1)[1]
        provider = FakeProvider([json.dumps(PLAN),
                                 "```html\n" + truncated + "\n```",
                                 "</h1>" + tail])
        result = sb.build_site("Portfolio for Arjun Mehta", self.dir, kind="portfolio",
                               provider=provider, attempts=1, speed="custom")
        html = (self.dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("</html>", html)
        self.assertTrue(result["ok"], result["attempts"])

    def test_extract_html_handles_fences_prose_and_truncation(self):
        fenced = sb.extract_html("Here you go:\n```html\n<!doctype html><html><body>x</body></html>\n```\n")
        self.assertEqual(fenced, "<!doctype html><html><body>x</body></html>")
        raw = sb.extract_html("preamble <!DOCTYPE html><html><body>y</body></html> trailing")
        self.assertTrue(raw.startswith("<!DOCTYPE html>"))
        self.assertTrue(raw.endswith("</html>"))

    def test_normalise_plan_rejects_thin_plans(self):
        plan, from_model = sb.normalise_plan({"sections": [{"heading": "Hi"}]}, "x", "portfolio")
        self.assertFalse(from_model)
        self.assertGreaterEqual(len(plan["sections"]), 4)

    def test_fallback_plan_reads_the_name_from_the_brief(self):
        plan = sb.fallback_plan("Portfolio for Arjun Mehta, a full-stack developer", "portfolio")
        self.assertEqual(plan["brand"], "Arjun Mehta")
        self.assertIn("full-stack developer", plan["title"].lower())

    def test_normalise_plan_accepts_a_two_section_plan(self):
        """A small model often returns fewer sections than asked for; its copy
        is still better than the generic fallback, so it must be accepted."""
        raw = {"brand": "Lena Fischer", "title": "Lena Fischer Photography",
               "sections": [{"id": "about", "kind": "text", "heading": "About",
                             "items": [{"text": "I photograph people and places."}]},
                            {"id": "gallery", "kind": "gallery", "heading": "Work",
                             "items": [{"title": "Harbour light", "tags": ["portraits"]}]}]}
        plan, from_model = sb.normalise_plan(raw, "x", "portfolio")
        self.assertTrue(from_model)
        self.assertEqual(plan["brand"], "Lena Fischer")
        self.assertEqual([s["kind"] for s in plan["sections"][:2]], ["text", "gallery"])

    def test_normalise_plan_keeps_model_content(self):
        plan, from_model = sb.normalise_plan(PLAN, "x", "portfolio")
        self.assertTrue(from_model)
        self.assertEqual(plan["accent"], "#7bd4a4")
        self.assertEqual(plan["sections"][1]["items"][0]["title"], "Relaydesk")

class ChecksTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        try:
            self._tmp.cleanup()
        except OSError:
            shutil.rmtree(self._tmp.name, ignore_errors=True)

    def _write(self, text: str) -> Path:
        p = self.dir / "index.html"
        p.write_text(text, encoding="utf-8")
        return p

    def test_repair_fixes_mechanical_defects(self):
        p = self._write("<html><head><title></title></head><body><h1>Hi</h1></body></html>")
        fixed = repair_html(p, "website", "Brand")
        text = p.read_text(encoding="utf-8")
        self.assertIn("viewport", text)
        self.assertIn(":focus-visible", text)
        self.assertIn("<footer", text)
        self.assertIn("<button", text)
        self.assertTrue(fixed)

    def test_repair_closes_truncated_markup(self):
        p = self._write("<!doctype html><html><body><style>body{color:red}")
        repair_html(p, "website")
        text = p.read_text(encoding="utf-8")
        self.assertIn("</style>", text)
        self.assertIn("</html>", text)

    def test_rendered_plan_meets_its_own_acceptance_checklist(self):
        plan = sb.fallback_plan("Portfolio for the fictional photographer Lena Fischer",
                                "portfolio")
        html = sb.render_plan_site(plan, "portfolio")
        passed, total, failing = checklist_summary(acceptance_checklist(html, "portfolio", plan))
        self.assertEqual(failing, [], f"{passed}/{total} checklist items met")

    def test_checklist_flags_a_page_that_misses_the_plan(self):
        thin = "<!doctype html><html><head><title>x</title></head><body><h1>Hi</h1></body></html>"
        plan = {"sections": [{"id": "work", "kind": "projects", "heading": "Work",
                              "items": [{"title": "a"}, {"title": "b"}]},
                             {"id": "contact", "kind": "contact", "heading": "Contact"}]}
        passed, total, failing = checklist_summary(acceptance_checklist(thin, "portfolio", plan))
        self.assertLess(passed, total)
        self.assertTrue(any("work" in f.lower() or "Work" in f for f in failing), failing)
        self.assertTrue(any("footer" in f for f in failing), failing)

    def test_check_flags_placeholder_copy_and_external_assets(self):
        p = self._write("<!doctype html><html><head><meta name='viewport' content='width=device-width'>"
                        "<title>X</title></head><body><footer>f</footer><button>b</button>"
                        "<p>Lorem ipsum dolor sit amet, consectetur adipiscing elit sed do.</p>"
                        "<link href='https://cdn.example.com/x.css' rel='stylesheet'>"
                        "<script src='https://cdn.example.com/x.js'></script></body></html>")
        ok, problems = check_html(p, "website")
        self.assertFalse(ok)
        self.assertTrue(any("filler" in p for p in problems), problems)
        self.assertTrue(any("external" in p for p in problems), problems)

class _Player:
    """Records the calls the Creation Workspace would receive."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.progress: list[float] = []

    def __getattr__(self, name):
        if name == "ensure_local_model":
            return lambda **kw: (True, "qwen3:8b")
        if name.startswith("creation_") or name in ("write_log", "begin_creation"):
            return lambda *a, **k: self.calls.append((name,) + a)
        raise AttributeError(name)

    def creation_progress(self, pct):
        self.progress.append(float(pct))
        self.calls.append(("creation_progress", pct))

def _manager_return(manager):
    """Return a callable that hands the given JobManager to the action layer.

    ``actions.crown_code`` resolves every job lookup through its module-level
    ``_get_manager`` alias, so patching that alias replaces the registry for the
    whole action layer instead of only half of it.
    """
    return lambda: manager

class ActionLayerTest(unittest.TestCase):
    """The crown_code action: routing, progress answers, and the site job wiring.

    The site builder is stubbed here, so this covers the action layer itself
    (what the UI and the model's tool call actually get back) without a model.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        from actions import crown_code as cc
        from core import crown_jobs
        self.cc = cc
        # Each test gets its own job registry: the module-level one is shared
        # with the running app, so a leftover finished job would leak in.
        self.manager = crown_jobs.JobManager()
        self._patcher = mock.patch.object(
            cc, "_get_manager", _manager_return(self.manager))
        self._patcher.start()

    def tearDown(self):
        try:
            self._patcher.stop()
        finally:
            try:
                self._tmp.cleanup()
            except OSError:
                shutil.rmtree(self._tmp.name, ignore_errors=True)

    def test_task_routing_site_vs_code(self):
        site = ["build a portfolio website", "make me a landing page",
                "build a homepage for my studio", "create a photography portfolio"]
        code = ["build a python CLI todo app", "fix the nav on my portfolio site",
                "write a fastapi backend", "refactor the parser and run pytest"]
        for brief in site:
            self.assertEqual(self.cc.classify_task(brief), "site", brief)
        for brief in code:
            self.assertEqual(self.cc.classify_task(brief), "code", brief)
        self.assertEqual(self.cc.infer_kind("a portfolio for a photographer"), "portfolio")
        self.assertEqual(self.cc.infer_kind("a website for a bakery"), "website")

    def test_site_job_reports_progress_files_and_checklist(self):
        from core import crown_jobs
        from core import site_builder

        player = _Player()
        job = crown_jobs.BuildJob(kind="site", brief="portfolio for Lena Fischer",
                                  workspace=str(self.dir), model="qwen3:8b")
        index = self.dir / "index.html"
        index.write_text("<!doctype html><html><body>x</body></html>", encoding="utf-8")
        canned = {
            "ok": True, "path": str(index), "bytes": 20949, "seconds": 720.1,
            "model": "qwen3:8b", "used_fallback": False, "notes": [],
            "checklist_score": "17/18",
            "plan": {"brand": "Lena Fischer", "sections": [{"heading": "Gallery"}]},
        }

        def fake_build(brief, out_dir, kind="portfolio", **kw):
            for cb_name in ("on_phase", "on_log"):
                self.assertTrue(callable(kw.get(cb_name)), f"{cb_name} missing")
            kw["on_phase"]("writing", 0.4, "Writing index.html — 40% of the file")
            kw["on_log"]("acceptance checklist 17/18 — open: FAQ accordion")
            return dict(canned)

        with mock.patch.object(site_builder, "build_site", fake_build):
            result = self.cc._run_site(job, self.dir, "portfolio", "qwen3:8b", player)

        self.assertTrue(result["ok"])
        completed = [c for c in player.calls if c[0] == "creation_complete"]
        self.assertTrue(completed, player.calls)
        self.assertIn("17/18", completed[-1][1])
        self.assertGreaterEqual(max(player.progress), 1.0)
        self.assertTrue(any(c[0] == "creation_file_add" for c in player.calls))

    def test_progress_and_cancel_actions_answer_without_a_model(self):
        from core import crown_jobs
        self.assertIn("Nothing is building", self.cc.crown_code({"action": "status"}))
        self.assertIn("Nothing is building", self.cc.crown_code({"action": "cancel"}))
        self.assertIn("No builds have run yet", self.cc.crown_code({"action": "list"}))
        self.assertIn("Tell me what to build", self.cc.crown_code({"description": "  "}))

    def test_background_start_returns_a_job_id_immediately(self):
        calls: list[float] = []

        class _P:
            def __init__(self, store):
                self._store = store

            def __getattr__(self, name):
                if name == "ensure_local_model":
                    return lambda **kw: (True, "qwen3:8b")
                if name.startswith("creation_") or name in ("write_log", "begin_creation"):
                    return lambda *a, **k: None
                raise AttributeError(name)

        def slow_build(brief, out_dir, kind="portfolio", **kw):
            time.sleep(0.4)
            calls.append(1.0)
            return {"ok": True, "path": str(Path(out_dir) / "index.html"), "bytes": 10,
                    "seconds": 0.4, "plan": {}, "notes": []}

        with mock.patch.object(sb, "build_site", slow_build):
            started_at = time.time()
            msg = self.cc.crown_code(
                {"description": "build a portfolio website for Lena Fischer",
                 "workspace": str(self.dir)},
                player=_P({"calls": calls}),
            )
            elapsed = time.time() - started_at
            self.assertLess(elapsed, 3.0, "crown_code blocked the caller")
            self.assertIn("background", msg)

            job = self._get_eventual_job(time.time() + 3.0)
            if job is None:
                self.fail(msg)
            self.assertIn("job " + job.id, msg)
            if job.thread:
                job.thread.join(15)
        self.assertTrue(any(i == 1.0 for i in calls), "the stubbed builder never ran")

    def _get_eventual_job(self, deadline):
        job = None
        while time.time() < deadline:
            job = self.manager.get()
            if job is not None:
                break
            time.sleep(0.05)
        return job

if __name__ == "__main__":
    unittest.main()
