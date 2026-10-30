# Dev Agent — Keys.AI's coding agent (Crown Code terminal behaviour)

Dev Agent is **Keys.AI's active coding agent** — the Ruby/Jarvis on-screen
coding agent. When you give Keys.AI a coding task it is routed to the Dev
Agent, which plans, inspects files, writes/edits code, runs real shell
commands in the embedded TERMINAL, reads real output and exit codes, fixes
failures, and returns a verified answer through the existing Keys.AI
interface.

The panel still opens as the **TERMINAL** tab in the creation workspace — that is
intentional: the Dev Agent *is* the terminal-based project builder here.
The tab label, the header button (F6), the shortcut guide, and all visible
UI wording in the creation panel still read as "Crown Code Terminal Agent" style
where it helps the live demo read clearly, but the actions behind them are the
Dev Agent workflow (plan → write files → install deps → run → fix errors).

```
Keys.AI (Python / PyQt6)                 Crown Code (Node.js / TypeScript)
┌───────────────────────────┐            ┌──────────────────────────────────┐
│  Gemini tool loop          │            │  dist-headless/headless.js       │
│   └─ crown_code tool ──────┼── NDJSON ──┤   • Agent loop (src/agent)       │
│  Live-creation workspace   │  stdin/    │   • Tool registry (fs/shell/git/ │
│   └─ embedded TERMINAL ◄───┼─ stdout ───┤     search)                      │
│  Permission dialog         │            │   • ProviderRegistry + CrownRouter│
└───────────────────────────┘            │   • OllamaProvider (local model) │
                                          └──────────────────────────────────┘
                                                        │
                                                   Ollama (localhost)
```

Keys.AI spawns Crown Code as a **managed subprocess** (`core/crown_bridge.py`)
and exchanges newline-delimited JSON events. Crown Code runs its real agent
loop and real tools — nothing is reimplemented or mocked.

### Why a subprocess bridge
Crown Code is a Node/TypeScript application (Ink TUI). Keys.AI is Python/PyQt6.
Reusing Crown Code's real code (rather than rewriting it in Python) means running
its agent headlessly and streaming its events into the Keys.AI UI. Node is
already required by Crown Code and is present on this machine.

## What is reused from Crown Code (unchanged source)

The headless entry imports and runs Crown Code's actual modules:

| Module | Reused for |
|--------|-----------|
| `src/agent/Agent.ts` | The agent loop, system prompt, retries, tool orchestration, permissions |
| `src/tools/registry/index.ts` | Tool registry + execution |
| `src/tools/filesystem/index.ts` | `read_file`, `write_file`, `edit_file`, `list_files`, `delete_file` |
| `src/tools/shell/index.ts` | Dangerous-command detection (`DANGEROUS_PATTERNS`, `isDangerousCommand`) |
| `src/tools/git/index.ts` | `git_status`, `git_diff`, `git_log`, `git_branch` |
| `src/tools/search/index.ts` | `search`, `glob` |
| `src/providers/ollama/index.ts` | Local Ollama inference + tool calling |
| `src/providers/registry/ProviderRegistry.ts` | Provider/account/model registry |
| `src/providers/router/index.ts` | CrownRouter model routing |
| `src/providers/anthropic|openai|google|nvidia|openai-compatible` | Optional compatible providers |
| `src/app/state/index.ts` | Zustand store the agent loop drives (works headless) |

One **additive** file is added to Crown Code (no existing file is modified or
deleted): `src/headless.ts`, compiled to `dist-headless/headless.js`.

## Keys.AI files

**Added**
- `actions/crown_code.py` — the coding-agent tool; drives the bridge and maps its events into the Keys.AI UI.
- `core/crown_bridge.py` — bridge client + local-model setup (detect/start/pick/pull/verify Ollama).
- `core/tool_declarations.py`, `core/tool_registry.py` — `crown_code` registered; `dev_agent` now routes to Crown Code.
- `config/crown_code.json` — integration config.
- `test_crown_code.py`, `test_crown_ui.py` — tests.
- `CROWN_CODE_INTEGRATION.md` — this document.

**Modified**
- `ui.py` — embedded terminal pane added to the live-creation workspace (streams stdout/stderr, exit codes, Clear + Stop controls, running indicator, user command input), plus thread-safe `KeysAIUI.terminal_output()` / `terminal_clear()` / `set_terminal_command_handler()` / `set_terminal_stop_handler()`.

**Retired**
- The old `dev_agent` project-builder execution path. The tool name still exists
  but its handler now calls Crown Code, so the old agent can never run in
  parallel. `actions/dev_agent.py` is left on disk but is no longer referenced by
  the registry.

## Automatic local model setup

On a coding task, before starting, Keys.AI:
1. checks Ollama is installed; 2. starts it if it is not running; 3. lists local
models; 4. picks a compatible coding model for this machine's RAM (prefers the
configured/preferred model, honours it when set, and warns when a model is too
large — it never assumes a 30B model runs everywhere); 5. pulls the model if
missing (with progress); 6. runs a real inference to verify it. The choice is
saved to `config/crown_code.json` and reused next launch. If local setup fails,
the real error and a recovery step are shown — **it never silently falls back to
a remote provider**.

## Permissions & safety

- Tool execution is restricted to the authorized workspace (`--cwd`); the bridge
  `chdir`s there so relative writes land inside it.
- `terminal` output is streamed live; timeouts and cancellation kill children.
- Policy `safe` (default): reads/searches/`git` inspect are auto-allowed; normal
  `write_file`/`edit_file` are allowed; **destructive** actions (`delete_file`,
  `rm -rf`, `git reset --hard`, `git push`, `sudo`, …) prompt Keys.AI's
  permission dialog. Policy `readonly` blocks mutation; `all` auto-approves.
- Child processes are tracked and killed on stop/abort/exit.

## Configuration (`config/crown_code.json`)

| Key | Meaning |
|-----|---------|
| `crown_dir` | Path to the Crown Code checkout (or set `CROWN_CODE_DIR`) |
| `provider` | `ollama` (default) or a configured provider id |
| `model` | Model override; empty = auto-pick for this machine |
| `ollama_url` | Ollama server URL |
| `policy` | `safe` \| `readonly` \| `all` |
| `max_iterations` | Max agent-loop iterations |

## Running

Keys.AI runs exactly as before (Administrator required; `python main.py` — UAC
prompt first). Then ask it to code, e.g. *“crown code: add a health-check
endpoint to this project”* or *“fix the failing tests in C:\path\to\project”*.

If the headless build is missing it is built automatically on first use
(`npx tsup src/headless.ts …`). To build manually:

```bash
cd "C:/Users/harma/Desktop/PROJECTS/Crown CODE"
npx --no-install tsup src/headless.ts --format esm --target node20 \
    --out-dir dist-headless --no-splitting
```

## Tests (actual results)

```bash
python test_crown_code.py   # bridge: local model, terminal, coding loop, cleanup
python test_crown_ui.py     # embedded terminal UI (offscreen)
```

- `test_crown_code.py` → **PASS**: `qwen3-coder:30b` verified with a real
  inference; Crown Code wrote a file in the authorized workspace, ran
  `type verify.txt`, streamed `WS_OK`, exit code 0; bridge returned a successful
  result and cleaned up its child process.
- `test_crown_ui.py` → **PASS**: terminal panel exists in the live-creation
  workspace; stdout/stderr stream; clear; running indicator; command and stop
  signals; lifecycle.

## Remaining limitations

- The dev model is now a LIGHT tool-capable local model (`qwen3.5:4b` /
  `qwen3:8b`, both verified to emit native tool calls) — a 30B model (~19 GB)
  is far too heavy for this ~16 GB machine. On every launch,
  `crown_bridge.sync_local_models()` starts Ollama if idle and re-pins an
  installed model in both `config/crown_code.json` and `api_keys.json`
  `task_models`, so the AI Provider settings always match what actually runs.
  NOTE: `qwen2.5-coder:3b/7b` and `deepseek-r1:8b` write tool calls as plain
  prose and do NOT drive the agent loop — only tool-capable models work here.
- Node.js must be on PATH at runtime (it is on this machine).
- The full GUI end-to-end run (UAC launch) was not executed headlessly; the
  bridge, tool wiring, and terminal widget were each verified directly.
- Keys.AI's old `dev_agent` LLM warm-up task is unchanged; Crown Code manages
  its own local model independently.

## Background builds, live progress, and the reliable site pipeline

A coding run used to block the conversation until it finished. It no longer
does: every build runs as a **job** (`core/crown_jobs.py`) on its own thread,
and the assistant answers progress questions from that job's record without
waiting for the build.

```
"build me a portfolio website for Lena Fischer"
    → returns in ~7s: "Started: portfolio_lena (job c72646dce9) … ask me how it's going"
    → the Creation Workspace shows PHASE · 62% · 1m12s · ETA 45s and the live log
"how's it going?"            → answered from the job record, outside the task lock
crown_code(action="status")  → phase, percent, ETA, files, last log lines
crown_code(action="cancel")  → sets the cancel flag; Stop button in the UI does the same
crown_code(action="list")    → every job this session
```

### Two execution paths, chosen from the task

| Request | Path | Why |
| --- | --- | --- |
| website, portfolio, landing page, web page | `core/site_builder.py` | a small local model cannot be trusted to drive a tool loop for a page, so the page is built by plan → write → verify → repair |
| anything else (apps, scripts, fixes, tests) | Crown Code headless agent | it needs reads, shell commands and iteration, and it reports its own results |

### The site pipeline (why a page now always finishes)

1. **Plan** — one JSON-only call: brand, copy, sections, acceptance list. JSON
   survives a weak model far better than tool calls, and a bad plan costs
   seconds. One retry if the JSON does not parse; the raw reply is kept in
   `plan.raw.txt`.
2. **Write** — one whole-file call (aider's whole-file format), streamed so
   progress is real: `Writing index.html — 42% of the file`. The request runs
   with `num_ctx=8192`; Ollama's 4096 default was silently dropping the brief,
   after which the model wrote 1000 lines of CSS and no page.
3. **Finish truncated files** — if the model stops inside `<style>`, it is asked
   to continue from its own last characters instead of paying for a fresh
   attempt.
4. **Verify** — `core/site_checks.py`: structure, copy, accessibility rules,
   then a real Chromium pass (console errors, 375 px/1280 px overflow, dead
   in-page anchors). The same rules the QA harness uses.
5. **Repair** — deterministic fixes first (viewport meta, `box-sizing`,
   `:focus-visible`, footer, truncation), then one targeted rewrite quoting the
   exact failures.
6. **Guaranteed floor** — if the model still cannot produce a valid page, the
   approved *plan* is rendered by `render_plan_site()` (responsive, accessible,
   working filters/form/JS, CSS-art tiles) and the result says
   `used_fallback: true`. The user gets a working site and an honest note.

### Configuration

| Setting | Where | Effect |
| --- | --- | --- |
| `model` | `config/crown_code.json` | dev-agent model; the site path auto-picks `qwen3:8b` unless a model is passed |
| `num_ctx` | `core/site_builder._provider` | 8192 for page writes |
| `attempts` | `build_site(attempts=2)` | model write attempts before the plan is rendered |
| `browser` | `build_site(browser=True)` | run the Chromium audit as part of the build |

### Verification

* `qa_artifacts/live_site_build.py` — end-to-end, real model: asserts the call
  returns immediately, reads progress mid-build (both `action=status` and the
  brain's progress answer), then audits the artifact in Chromium.
  Result: **PASS** (`qa_artifacts/reports/live_site_build.json`).
* `qa_artifacts/regression_tests/test_site_builder.py`, `test_crown_jobs.py` —
  17 deterministic tests (fake provider, no network, no browser).

## Outside inspiration (what was borrowed, and from where)

No agent code was copied — implementations differ, and licences vary — but the
*shapes* come from the tools that already solved these problems:

| Idea | Where it comes from | What this repo does with it |
| --- | --- | --- |
| Plan/Act split — plan with one prompt, execute with another | Cline (Plan/Act modes), Claude Code plan mode | `core/site_builder.py`: a JSON-only *plan* call, then a separate *write* call; the plan is saved to `plan.json` |
| Whole-file edit format instead of surgical patching | aider ("whole file" edits beat diff formats on weak models) | the write step asks for the complete `index.html` in one reply, extracted by `extract_html()` |
| Automatic "continue the file" when output is truncated | aider / Cursor apply-continuation | `_finish_truncated()` re-prompts with the model's own last 2.5 KB |
| Explicit task list, verified afterwards | Claude Code TodoWrite, Devin/OpenHands task plans | `acceptance_checklist()` turns the plan into checked items (sections rendered, form validation, focus styles, offline rule) shown in `checklist_score` |
| Act → observe → verify → retry with the exact error | Cline, OpenHands, SWE-agent | verify (static + Chromium) then repair quoting the failing checks; the failure text is fed back, never swallowed |
| Deterministic post-processing of model output | OpenHands (lint/format pass after every edit) | `repair_html()` fixes the mechanical class of defects itself: viewport, `box-sizing`, `:focus-visible`, footer, unclosed markup |
| Non-blocking long jobs with a pollable status | gh/CI-style job records; Claude Code background tasks | `core/crown_jobs.py` + `brain._build_progress()` answer "how's it going?" outside the task lock |
| Context sizing for local reasoning models | Ollama docs / `think: false`, `num_ctx` in Qwen3 | `num_ctx=8192`, `think=false`, `/no_think` on the OpenAI-compatible path |

**Not** adopted: multi-agent swarms, remote sandboxes and full-repo indexing —
they need resources this machine does not have, and the acceptance checks above
cover the failure modes actually observed here.

### Verification

* `qa_artifacts/live_site_build.py` — real `qwen3:8b`, real Chromium: returns in
  ~7 s, progress readable mid-build, artifact passes the checks and the browser
  audit → **PASS** (`qa_artifacts/reports/live_site_build.json`, 20 949 bytes,
  692 lines, 12 min, `used_fallback: false`).
* `python -m unittest` over `qa_artifacts/regression_tests/` — **123 tests, OK**
  (`qa_artifacts/logs/full_suite_after.log`).
* `python test_crown_ui.py` — offscreen workspace: phase chip, progress, DONE
  state → **PASS**, screenshot `qa_artifacts/screenshots/creation_workspace_build.png`.

## Fast path (measured, October 2026)

The site pipeline now produces a working page in **15 seconds** and finishes the
whole build — planner copy, re-render, Chromium audit — in **~105 s**. Before
this change the same portfolio took **12–19 minutes** and often failed.

What changed:

1. **Instant first page.** The built-in plan is rendered *before* any model call,
   so `index.html` exists and passes the checks 15 s after the request. The
   planner's copy is rendered afterwards and swapped in only if it also passes;
   a bad planner reply can no longer cost the user a working page.
2. **Small model for the plan, big model for the design.** The plan is JSON, so
   it goes to the fastest installed model. Measured on this machine (same
   prompt): `qwen2.5-coder:3b` 19 s · `qwen3.5:4b` 37 s · `qwen2.5-coder:7b`
   52 s · `qwen3:8b` 88 s (and the 3B model produced the valid plan; the 8B one
   did not). The 3B coder is the default planner.
3. **Truncated JSON is continued, not discarded.** Small models stop mid-object;
   the reply is continued from its own last characters so its copy survives.
4. **Two speeds.** `speed="fast"` (default) stops after plan + render + verify.
   `speed="custom"` keeps that page and then asks `qwen3:8b` for a bespoke
   design, verified before it replaces the rendered page — extra minutes can
   never cost a working site.

Live evidence (`qa_artifacts/live_site_build.py`, real Ollama + Chromium):

| Measure | Before | Now |
| --- | --- | --- |
| Request returns to the user | 7–20 s (then blocked) | 15 s, build in background |
| Working `index.html` on disk | never / 12–19 min | **15.5 s** |
| Full build with planner copy + browser audit | 12–19 min, often FAIL | **105 s, PASS** |
| Plan quality | 1 of 3 runs used the model's plan | planner copy every run, checklist 19/19 |

## Studio engine — ten design systems, one content model

The site path no longer renders every brief through one template. `core/site_studio/`
contains ten independent studios. Each owns its palette, typography, layout,
decoration and motion; they share only the functional base (box-sizing, focus
rings, reduced-motion).

| Studio | Visual language | Signature structure / motion |
| --- | --- | --- |
| Aurora | dark glass, drifting colour fields | bento grid, pointer parallax, animated counters |
| Editorial | paper, masthead, double rules | numbered story rows, drop cap, reading-progress rule |
| Brutalist | acid yellow, 3 px borders, offset shadows | marquee, index table, hard-cut hovers |
| Swiss | strict 12-column grid, hairlines, red index | numbered rows, red square draw-in |
| Terminal | phosphor green, scanlines | typed hero, boot log, copyable commands |
| Organic | warm paper, botanical blobs | swaying leaves, product grid, add-to-basket counter |
| Luxury | ink and gold, framed hero | slow fades, gold frame, suite gallery |
| Pop | candy palette, stickers, chunky cards | sticker spin, bouncy hover, mosaic products |
| Cinematic | full-bleed lightfield, letterbox | ken-burns field, draggable filmstrip |
| Newsroom | masthead, ticker, column rules | live ticker, SVG sparkline, story columns |

Selection is deterministic per brief but varies with it: keyword affinity
(`score_studios`) narrows the field, then the brief's own hash breaks ties.
`render_studio_page(plan, kind, brief, seed)` is what `build_site` calls; the
plan is adapted by `plan_to_content`, so model-planned builds get the same
variety as the curated showcase.

**Showcase:** `crown_sites/showcase/index.html` — ten complete sites, one per
studio, plus screenshots in `crown_sites/showcase/_shots/`. Rebuild with:

```bash
python scripts/build_site_showcase.py          # render + Chromium audit + screenshots
python scripts/build_site_showcase.py --static # render + static checks only
```

Verification: 10/10 sites passed static checks, Chromium audit (console,
375/1280 px overflow, anchors) and a real interaction audit (mobile nav,
filters, form rejection/confirmation, counters, sparkline, filmstrip scroll,
add-to-cart). Report: `qa_artifacts/reports/site_showcase.json`.
All 20 studio × plan combinations also pass `check_html`, the 17-item
acceptance checklist and the overflow audit.

## Office artifacts — Word, PowerPoint, Excel, Power BI

`actions/file_processor.create` now handles all four formats:

| Format | Builder | Result |
| --- | --- | --- |
| `.docx` | `actions/_office_builder.build_docx` | cover, styled headings, paragraphs, bullet/numbered lists, tables, header/footer page numbers; markdown instructions become real Word headings and bold runs |
| `.pptx` | `build_pptx` | 16:9 deck with topic-specific outlines (pitch, architecture, demo, analytics, lesson, strategy, research, security, status, launch), honours an explicit *N slides* request, native chart on the metrics/results slide, slide numbers and footer |
| `.xlsx` | `actions/_office_xlsx.build_xlsx` | 4 worksheets (Dashboard, Trend, Data, Assumptions), KPI cards, live formulas, native bar/line charts, conditional formatting, table style; columns adapt to revenue / budget / inventory briefs (inventory plots only on-hand vs reorder point) |
| `.pbix` | `_create_powerbi` | report spec + semantic model + DAX module, validated structurally |

The read path is implemented too (`actions/_file_readers.py`): PDF info /
extract_text / to_word, DOCX, PPTX, XLSX, CSV stats, JSON validate/format and
text files. Unsupported actions say exactly what is supported. JSON extraction
now survives fences, prose, doubled quotes, raw newlines and missing commas.

Independent validation: **20/20** generated DOCX/PPTX artifacts pass
`qa_artifacts/validate_docs.py` (structure, required content, no placeholders,
no markdown leakage, widescreen PPTX). Excel samples reopen with openpyxl
(4 sheets, 2 charts, 69 formulas each). PowerPoint samples are 7 or 8 slides
exactly as briefed, with distinct titles throughout. Power BI sample emits
3 pages, 11 visuals, a 2-table semantic model and a 15-measure DAX module.

## Live code display

The Creation Workspace code pane is now a `QPlainTextEdit` with:

- real line numbers and a current-line highlight;
- per-language syntax highlighting (HTML, CSS, JS/TS, Python, JSON, Markdown, SQL);
- language + live line/byte counters in the header;
- COPY and WRAP controls;
- automatic language detection from filename and content.

`set_code` starts at line 1 (a build preview should show the top of the file),
while `append_code` still streams to the end. Verified offscreen with Qt:
language detection, stats, wrap toggle, clipboard copy and reset, screenshot at
`qa_artifacts/screenshots/code_viewer.png`.

## Verification for this pass

- `python -m pytest qa_artifacts/regression_tests -q` → **141 passed, 11 subtests passed**.
- `python scripts/build_site_showcase.py` → **10/10 sites pass** browser + interaction audit.
- `python qa_artifacts/validate_docs.py --kind both` → **20/20** artifacts pass.
- `python -m py_compile` on every changed module → clean.

## Application artifacts — rendered from a recipe, then proven to run

Two artifact kinds were being reported as builds and were not. In the last
`two_of_each` batch, **both dashboards** finished with a folder that could not
be started (one had no `static/` files, one had only `brief.json`), and the
**Python desktop app** came back `finished: false` after the agent "searched the
empty workspace and answered instead of building". The documents and websites in
the same batch passed 11/11 — because they are rendered from a plan and then
checked, not delegated to an 8B model's tool loop.

`core/app_builder.py` closes that gap for the two kinds whose acceptance is
fully mechanical.

### Routing (three paths, chosen from the request)

| Request | Path | Needs a model? |
| --- | --- | --- |
| portfolio, marketing page | `core/site_builder.py` | yes (planner) |
| dashboard, Python desktop app — single user, file-backed | `core/app_builder.py` | **no** |
| stores, Electron, Android, MySQL/Postgres dashboards, anything with login | Crown Code agent | yes |

`app_kind_for()` decides this and is deliberately conservative. A request that
names MySQL, Postgres, Firebase/Supabase, Redis, a login, OAuth, roles or
permissions is **not** routed to the recipe: the recipe is SQLite and
single-user, so serving it would silently replace a stated requirement. Negated
requirements ("no login", "without authentication") are read as negations —
treating them as requests is what sent ordinary dashboards to the agent, where a
build could burn five minutes and still fail.

### What is generated

| Artifact | Files | Runtime |
| --- | --- | --- |
| dashboard | `app.py`, `db.py`, `schema.sql`, `seed.py`, `templates/index.html`, `static/dashboard.js`, `static/style.css`, `requirements.txt`, `.env.example`, `README.md` | Flask + SQLite, `python app.py` |
| python-desktop | `main.py`, `app/{__init__,window,db,theme}.py`, `requirements.txt`, `README.md` | PyQt6 + SQLite, `python main.py` |

The dashboard is not a page with numbers typed into it: `/api/kpis`,
`/api/series`, `/api/breakdown`, `/api/status` and `/api/rows` all run SQL over
the seeded table, and `static/dashboard.js` draws the line chart, category bars,
status pills and table from those responses. Labels and sample rows come from
`core/app_specs.py` (fleet / newsroom / inventory / sales detected from the
brief, generic otherwise). The footer says the data is sample data.

The desktop app has a `--selftest` that builds the window on Qt's `offscreen`
platform against a throwaway database, checks the row count and total, prints
`OK` and exits 0 — so its correctness is measurable without a human.

### Verification is graded, and every level is reported

`core/app_checks.py` replaced "the files are on disk" with four levels, each
carrying the command that ran and its real output:

| Level | What it proves |
| --- | --- |
| `compiles` | `python -m py_compile` accepted every module |
| `executes` | the seeder ran, or `main.py --selftest` printed `OK` and exited 0 |
| `serves` | the server answered each endpoint with 200 and JSON, and the payload contained the promised keys **and rows** |
| `renders` | Chromium loaded the page, found the KPI cards and the chart `<svg>`, and logged no console errors (opt-in via `browser=True`) |

A skipped check is never reported as a pass. If the entry point is missing, that
is recorded as a failed check — `ok` is true only when at least one check ran and
all of them passed.

### Measured

`python qa_artifacts/build_recipe_apps.py` drives the real tool
(`crown_code(wait=True)`) for two dashboards and two desktop apps:

| Artifact | Result | Files | Time |
| --- | --- | --- | --- |
| dashboard_01_fleet | verified (8 checks) | 12 | 1.0 s |
| dashboard_02_newsroom | verified (8 checks) | 12 | 0.9 s |
| python_01_ledger | verified (2 checks) | 8 | 0.8 s |
| python_02_inventory | verified (2 checks) | 8 | 0.5 s |

Delivered artifacts were then re-verified on disk: the ledger prints
`selftest: 6 rows, total 638.90 / OK`, and the fleet dashboard passes the
Chromium pass (`#kpis .kpi=4, svg=1`, no console errors) with a full-page
screenshot at `qa_artifacts/screenshots/recipe_dashboard_fleet.png`.
Before this change the same two kinds took 5–10 minutes each and produced nothing
runnable.

Tests: `qa_artifacts/regression_tests/test_app_builder.py` — 17 tests over specs,
routing, both builders and every verification level, including four negative
cases (broken syntax, missing entry point, a script that is not a server, an
empty database). Full suite: **193 passed** (baseline before this change: 174).

### Known limits

- The dashboard schema is deliberately generic (`events`: date, label, category,
  quantity, amount, status). Domain tables named after the brief's own nouns —
  vehicles/trips for fleet, articles/sections for newsroom — are **not**
  generated; a request that needs a specific schema still belongs on the agent
  path.
- These artifacts are **not model-authored**: `authored_by` says "recipe
  renderer (no model)" in the result. Copy and labels are derived from the spec,
  not written per request.
- No authentication, no multi-user, no external database in either recipe — by
  design, and the reason such requests are refused the recipe.
- The Chromium pass is opt-in (`browser=True`); the tool path runs the first
  three levels so a build never depends on a browser being installed.

### Considered and not adopted

- **OpenMAIC** (`THU-MAIC/OpenMAIC`) — verified: a Next.js/pnpm multi-agent
  "interactive classroom" platform for turning a topic into lessons, quizzes and
  slides. Not a document or application builder; its coordination ideas are
  already covered by the job/phase model here. Reference only.
- **GenOffice** (`genspark-ai/genoffice`) — verified: a Genspark Electron office
  suite (end-user app, not a library). Nothing importable into a Python backend;
  this repo already produces `.docx/.pptx/.xlsx` with python-docx/pptx/openpyxl.
  Rejected as a dependency.
- **OpenHands** — the plan → act → observe → verify loop is already the shape of
  `site_builder` and now `app_builder`; embedding the runtime would add a
  container-scale dependency for capability this machine already has. Reference
  architecture only.
- **Word Craft / SlidePoise / AI App Builder Open** — not confirmed as the
  specific projects intended; no capability was assumed from the names and
  nothing was integrated.


---

## The Next-Gen 4-Stage Autonomous Pipeline

Integrating architectural strengths from **OpenHands**, **OpenCode**, and **Block Goose**, Crown Code operates through an error-free 4-stage pipeline tuned specifically for local models:

### Stage 1: Brain & Clarification Gate (`core/brief_spec.py`)
- **Goose-inspired Recipe Clarification**: Automatically inspects tasks for missing requirements (data sources, metrics, chart types, tech stack, scope, UI theme).
- Generates interactive multiple-choice questions with `(Recommended)` defaults.
- Offers `apply_recommended_defaults` so one-click execution never gets blocked.

### Stage 2: Deep Research Mode & Asset Harvesting (`core/research_harvester.py`)
- **OpenHands-inspired Browsing & Asset Harvesting**: Launches browser inspection to crawl live documentation and web references.
- **Real Vector Assets**: Generates clean, valid Lucide/Feather vector SVG icons into `<workspace>/assets/icons/`.
- **Authentic Media**: Fetches license-cleared CC photography into `<workspace>/assets/images/`.
- **Contrast-Checked Design Tokens**: Samples dominant colors from reference imagery into `<workspace>/assets/design_tokens.json`.
- **Synthesized Knowledge**: Writes `<workspace>/references/RESEARCH_DOSSIER.md`.

### Stage 3: Master Blueprint Synthesis (`core/blueprint_engine.py`)
- **Deterministic Blueprinting**: Compiles brief, requirements, and assets into `<workspace>/BLUEPRINT.json`.
- **Anti-Hallucination Manifest**: Generates an exact, ordered target file list with roles.
- **Fortified Master Prompt**: Binds real local asset paths and Windows shell commands into an unambiguous execution contract.

### Stage 4: Fortified Crown Code Execution & Self-Repair
- **OpenCode-inspired Dual-Stream Parsing**: Robust parsing of native Ollama tool calls as well as XML/JSON fallback blocks in `xml-parser.ts`.
- **Sliding Window Context Compaction**: Automatically compacts older tool outputs in `Agent.ts`, preventing context exhaustion and hallucinations on local models.
- **Bounded Test Self-Repair**: Executes build and pytest verification, feeding error traces back into the loop to fix syntax or logic bugs.
- **Instant Preview Launch**: Immediately opens the finished HTML/SPA in the browser or runs the server/desktop application upon completion.
