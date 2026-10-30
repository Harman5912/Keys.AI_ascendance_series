# Keys.AI — Development Agent & God's Eye View Roadmap

Living task list for the work described in the master engineering prompt.
Statuses are `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`, `VERIFIED`.

**Verification rule used here:** a task is `VERIFIED` only with evidence produced
in this workspace — a test run, a probe output, or a file inspected. "Code was
written" is not evidence. Anything untested stays `IN_PROGRESS` and says so.

Baseline note: **this workspace is not a git repository** (`git status` →
`fatal: not a git repository`). There is therefore no commit-level baseline and
no diff against a prior state. The pre-existing state was recorded by
inspection instead. See `REQUIREMENTS.md` §*Constraints*.

---

## Phase A — Audit and baseline

| ID | Task | Status | Evidence |
|----|------|--------|----------|
| A1 | Inspect project architecture and current development agent | VERIFIED | `main.py` (1450 lines), `ui.py` (6723), `actions/crown_code.py`, `core/tool_registry.py`, `core/tool_declarations.py`, `brain/`, `core/research_browser/`, `universal_agent/` read directly |
| A2 | Inventory local and cloud AI model integrations | VERIFIED | `core/model_catalog.py` (gemini/nvidia/anthropic/openrouter/openai/ollama, ~40 ids each), `brain/providers/`, `core/llm_client.py`, `core/gemini_ladder.py` |
| A3 | Inventory browser research, voice and filesystem tools | VERIFIED | `core/research_browser/` (QtWebEngine, tabs, screenshots, source/asset collection), `actions/web_search.py`, `actions/browser_control.py`, `actions/file_controller.py` |
| A4 | Identify interface-routing and workspace-management capability | VERIFIED | `MainWindow._show_center_view` (ui.py:5304), `_center_stack`, `_content_stack` (ui.py:5843), `_show_hud_view`, `run_on_gui_thread` (ui.py:5341) |
| A5 | Run baseline tests and record existing failures | PARTIAL | No baseline was captured *before* the change (no VCS, and the app needs live keys). After the change, four pre-existing suites that touch the edited surfaces were run: `test_shutdown_and_tool_failure` 10 passed; `test_demo_and_messaging` 20 passed; `test_repo_index` 31 passed; `test_ua_integration` 21 passed / **7 pre-existing failures** (see blocker 7). The remaining pre-existing suites were **not** run. Recorded in `KEYS_AI_VERIFICATION_RESULTS.md` |
| A6 | Identify dependencies, runtime and compatibility constraints | VERIFIED | `requirements.txt`; Node v26.5.0 on PATH; repo engine range `>=24.14.0 <25 \|\| >=26 <27`; Qt 6.11.0 with QtWebEngine + QtWebChannel importable |

### Audit findings that changed the plan

1. **`dev_agent` is retired.** `core/tool_registry.py` routes `dev_agent` to
   `actions/crown_code.py::crown_code`. Building a second coding agent would have
   duplicated a working one — it was not done.
2. **A real browser already exists.** `core/research_browser` runs the same
   QtWebEngine the user sees, with tool actions for navigation, page text,
   screenshots, downloads, source and asset collection. No new browser was built.
3. **The globe already exposes a control surface.** God's Eye View publishes
   `window.__godsEyeView.voiceCommands.runner(name, args)` from
   `src/app/tools.js` — its own voice action runner. The integration drives that
   rather than inventing an API. See `docs/GLOBE_INTEGRATION.md`.
4. **Model routing is centralised.** `core/llm_client.py` + `core/model_catalog.py`
   are the single entry points; no module needed a new endpoint.

---

## Phase B — Requirements and task planning

| ID | Task | Status | Evidence |
|----|------|--------|----------|
| B1 | Reliable requirements-gathering workflow | VERIFIED (pre-existing) | `crown_code` returns `NEED REQUIREMENTS` with questions and refuses to build; `REQUIREMENTS.md` records the decisions for this change |
| B2 | Identify ambiguous requirements | VERIFIED (pre-existing) | Same path; `clarify` action lists missing slots |
| B3 | Dependency-aware project plans | VERIFIED (pre-existing) | `core/engine/` orchestrator + `actions/crown_code.py` job phases; not modified |
| B4 | Track tasks, blockers and completion evidence | VERIFIED (pre-existing + this file) | Crown Code emits `DevEvent` stages to the Live Coding console; this file tracks the agent work |
| B5 | Resume interrupted tasks without duplicating work | VERIFIED (pre-existing) | Crown Code job records under `config/crown_code.json`; not modified |

No new planning machinery was added: a working one exists, and Rule 14 asks for
the smallest change that meets the requirement.

---

## Phase C — Research and resource acquisition

| ID | Task | Status | Evidence |
|----|------|--------|----------|
| C1 | Inspect the integrated research tool and its real capabilities | VERIFIED | `core/research_browser/tools.py` action list; `core/research_browser/service.py` (`open_tab`, `navigate`, `wait_for_load`, `run_js`, `page_text`, `click_element`, downloads) |
| C2 | Automatic research when a project needs external information | VERIFIED (pre-existing) | `core/research_step.py` — browser-driven research stage with real page text and screenshots |
| C3 | Preserve source URLs, citations, licence status | VERIFIED (pre-existing) | `core/research_browser/library.py`, `collector.py`; assets carry `license_status` defaulting to `unknown` |
| C4 | Retrieve genuine images and downloadable assets | VERIFIED (pre-existing) | `capture_screenshot`, `download_resource`, `collect_image`, `add_asset_to_project` in `core/research_browser/tools.py` |
| C5 | Inspect GitHub repositories and their implementation details | VERIFIED | Done for this task: `integrations/gods_eye_view` cloned and read (README, package.json, `src/voice/gevActions.js`, `src/app/tools.js`, `src/voice/actionSchemas.js`, `src/voice/layerManifest.js`, `DATA_SOURCES.md`, `LICENSE`) |
| C6 | Evaluate dependency compatibility, maintenance, security, licence | VERIFIED | MIT code / non-MIT data split in `DATA_SOURCES.md`; engine range parsed from `package.json`; Node v26.5.0 validated against it. Recorded in `research/RESOURCE_INVENTORY.md` |
| C7 | Connect research findings to implementation tasks | VERIFIED | This roadmap + `docs/GLOBE_INTEGRATION.md` cite the files the decisions came from |

---

## Phase D — Multi-project and multi-UI development

| ID | Task | Status | Evidence |
|----|------|--------|----------|
| D1 | Improve project architecture planning | VERIFIED (pre-existing) | `actions/crown_code.py::classify_task` / `infer_kind`, `core/app_specs.py`, `core/build_recipes.py` |
| D2 | Support different UI styles and multiple distinct pages | VERIFIED (pre-existing + this change) | Existing: `creation workspace`, `research browser`, `image studio`, `presentation overlay`. Added: a fourth centre view (globe) through the same `_show_center_view` route |
| D3 | Build functional frontend and backend components | VERIFIED (pre-existing) | Crown Code site/app/bridge paths; not modified in this task |
| D4 | Connect APIs, databases, auth, state | NOT_VERIFIED_HERE | Out of scope for this change and not exercised; pre-existing capability was not audited to runtime level |
| D5 | Collect and incorporate real approved assets | VERIFIED (pre-existing) | `add_asset_to_project` rejects unapproved licences by design |
| D6 | Responsive layouts, navigation, design systems | NOT_VERIFIED_HERE | Pre-existing; not modified or re-verified in this pass |

---

## Phase E — Local-model orchestration

| ID | Task | Status | Evidence |
|----|------|--------|----------|
| E1 | Discover existing local models and verify availability | VERIFIED (inspection) | `core/model_catalog.py` `ollama` provider (`http://localhost:11434`), editable model dropdown. **Runtime availability was not probed** — no Ollama request was issued in this session |
| E2 | Map model capabilities to tasks | VERIFIED (pre-existing) | Per-task model config in `config/api_keys.json` read by `core/llm_client.py::_build_provider` |
| E3 | Use existing models through established interfaces | VERIFIED (pre-existing) | `core/llm_client.get_llm(task)` / `complete(task, ...)`; `brain.providers.get_provider` |
| E4 | Controlled retries, timeouts, fallbacks, monitoring | VERIFIED (pre-existing) | `core/gemini_ladder.py`, provider exception handling in `core/llm_client.py`; `TypeError` fallback path for older providers |
| E5 | Verify local execution without unintended cloud usage | NOT_VERIFIED | No local inference was executed here, so no claim is made that a local model ran. Not required for the globe work, which does not use an LLM |

---

## Phase F — God's Eye View integration

| ID | Task | Status | Evidence |
|----|------|--------|----------|
| F1 | Inspect the official repository, licence and data sources | VERIFIED | Shallow clone at `integrations/gods_eye_view` (v0.3.0, MIT, `Copyright (c) 2026 Bilawal Sidhu`); `DATA_SOURCES.md` read |
| F2 | Choose an integration approach for the existing frontend | VERIFIED | Local service + QtWebEngine centre view + the app's own `voiceCommands.runner`. Rationale in `docs/GLOBE_INTEGRATION.md` |
| F3 | Integrate the actual globe application | VERIFIED | 17/17 live checks pass: `qa_artifacts/regression_tests/globe_live_probe.py` |
| F4 | Connect text and voice commands to globe actions | VERIFIED (routing) | `globe` tool declared (`core/tool_declarations.py`), handled (`core/tool_registry.py`), dispatched (`main.py` `_execute_tool`), plus a deterministic guard `_route_globe_utterance`. The voice glue is now covered by 5 tests that drive `_route_globe_utterance` with synthetic recognised transcripts (`TestVoiceRoutingGlue`), including a source assertion that `_receive_audio` still calls it. **Physical microphone still not exercised** — see blocker 2 |
| F5 | Precise location search and navigation | VERIFIED | Kanpur → camera 26.459, 80.321 (≈2 km, city framing); New Delhi resolved to "New Delhi, Delhi, India"; Eiffel Tower coordinates honoured to 0.2 km |
| F6 | Data-layer controls and error handling | VERIFIED (partial) | `set_layer_visibility` invoked and answered `ok`. Layers needing API keys are unavailable on a keyless install — reported, not faked |
| F7 | No additional globe button | VERIFIED | `grep` of `ui.py` shows no globe entry in the actions menu or header; the workspace is reachable only through `_open_globe_workspace`, called by the tool |
| F8 | Startup, navigation, rendering, lifecycle, shutdown, failure | VERIFIED | Cold start 6.0 s; adopt/reuse; owner-stop kills; adopted-stop does not; restart after stop; unknown action refused. Output quoted in `docs/GLOBE_INTEGRATION.md` |

---

## Phase G — Verification and delivery

| ID | Task | Status | Evidence |
|----|------|--------|----------|
| G1 | Unit, integration and end-to-end tests | VERIFIED (scoped) | 26 unit tests pass (`test_globe_integration.py`, 97 subtests); 17 live checks pass (`globe_live_probe.py`, exit 0). Four pre-existing suites touching the edited files were run (62 passed, 7 pre-existing failures). The rest of the pre-existing suite was not run |
| G2 | Verify each major feature in the running application | VERIFIED (globe) | Live probe drives the real page in QtWebEngine |
| G3 | Error handling, cancellation, recovery | VERIFIED | Cancelled-flight retry, unknown-action refusal, missing-checkout message, Node-range refusal, WebGL hint on readiness failure |
| G4 | Performance and resource use | IN_PROGRESS | Server cold start measured (6.0 s). No GPU/memory profile was taken for the globe |
| G5 | Fix failures and rerun affected tests | VERIFIED | Four parser bugs, one JS-contract bug and one result-envelope bug were found by the tests and fixed; suites re-run green |
| G6 | Update technical documentation | VERIFIED | This file, `REQUIREMENTS.md`, `research/RESOURCE_INVENTORY.md`, `docs/DEVELOPMENT_AGENT_ARCHITECTURE.md`, `docs/GLOBE_INTEGRATION.md` |
| G7 | Truthful completion report with evidence | VERIFIED | Final report separates verified, partial and blocked items |

---

## Added during implementation

| ID | Task | Status | Note |
|----|------|--------|------|
| X1 | Readiness is two-phase (document, then runner) | VERIFIED | A page that has answered HTTP 200 can still do nothing. `globe/service.py::_wait_ready` |
| X2 | Do not probe WebGL repeatedly | VERIFIED | Probing created a WebGL context per call and exhausted the browser's context pool; the probe now runs once, only on failure |
| X3 | Retry a `cancelled` flight once | VERIFIED | A command issued during the app's own startup restoration is cancelled by the app. One bounded retry, then an honest failure |
| X4 | Server lifecycle ownership | VERIFIED | A server Keys.AI did not start is adopted and never killed on exit |
| X5 | Do not let the app's action names shadow ours | VERIFIED | `_with_action` keeps `globe_action` (upstream) alongside the logical `action` |
| X6 | Research must discover its own pages | VERIFIED | `core/research_step._search_for_query` was a placeholder returning `None`, so the browser could read a page but never find one. Wired to `actions.web_search._web_results` (the app's own keyless backend); live check returned `https://docs.python.org/3/library/asyncio.html`. Video/social silos skipped (`_is_noise`); duplicate URLs visited once (`seen_urls`) |
| X7 | The research browser has no launcher either | VERIFIED | Removed the sidebar `RESEARCH BROWSER` button and the F1 palette entry; added a real `open` action to `research_browser` so text/voice open it. Tests assert both entry points stay gone and that `_open_research_browser` still exists |
| X9 | Builds get real design tokens | VERIFIED | `core/design_system.py`: a deterministic palette from the brief, every pair contrast-checked with the WCAG 2.2 formula (4.5:1 body / 3:1 large). 84 seed×kind×mood combinations pass with zero failures. Renders CSS `:root`, a drop-in Qt `app/theme.py` that is exec'd in tests, and a prompt block. 27 tests |
| X10 | "Well designed" is enforced, not asserted | VERIFIED | `core/design_check.py` fails a build on: contrast below AA, lorem ipsum / TODO in visible copy, a local `<img>` that does not exist, or nothing checkable at all. Warns on >8 font sizes, off-4px spacing, dead `href="#"`. Wired into `crown_code` for projects that have a UI, and reported in the result |
| X12 | "Build me a game" builds a game | VERIFIED | `core/game_builder.py` + a `game` recipe. Rules live in `game/state.py` with no pygame import; the scene renders them. `--selftest` proves movement clamp, fire cooldown, hit scoring, life loss, game over, pause, restart and seed replay, then builds the scene under `SDL_VIDEODRIVER=dummy`. A real build reported `ok=True, selftest OK` |
| X13 | Previews use the Research Browser | VERIFIED | The creation workspace's own preview browser is out of the splitter and `show_preview` is a no-op; `_on_cr_preview` opens the Research Browser and navigates it. Verified against a local HTTP server: the tab URL matched and the old widget stayed invisible |
| X14 | Built-in templates meet the contrast bar | VERIFIED | The dashboard `:root` and the desktop `app/theme.py` are now generated from design tokens (with `--good/--warn/--bad/--radius` aliases so existing rules keep working). Generated dashboard and desktop projects pass the gate with 0 errors |
| X15 | The gate also checks the running page | VERIFIED | `design_check.check_rendered(url)` loads the page, reads `document.images` for failed loads, and captures uncaught errors plus `console.error` via a DocumentCreation hook. Wired into `crown_code` after launch: a broken image fails the build, console errors are reported |
| X16 | Palettes can come from collected references | VERIFIED | `core/design_research.py` samples the hue from real pixels of images the research browser collected, then builds tokens from it. Blue reference → 220°, orange → 13°, grey → honest fallback. The brief names the files it used and says not to copy their layout |
| X11 | Fixed a pre-existing NameError in the build bridge | VERIFIED | The `research_mode`/browser-tools block sat inside the `on_event` closure, which has no `p`, so every event raised `NameError` and the browser-tool merge could never run. Moved to the caller that owns the params; `_run_bridge`/`_agent_build` now take `tools`. `test_crown_build_verification` went 6 failed → 3 passed |
| X8 | The research browser became a wide page | VERIFIED | Sidebar minimum 320→190 px, split stretch 5:2→9:2 (`setSizes([1120, 250])`); `SCREENSHOT`, `FULL PAGE`, `A-`, `A+` removed from the toolbar. Page keeps back/forward/reload/stop, address, GO and tabs |

---

## Known blockers and limits

1. **No git repository.** No commits, no baseline diff, no rollback point. Left as
   found; creating a repo was not requested.
2. **Physical microphone / speaker not tested.** Voice routing is verified down to
   the tool call and the deterministic utterance guard. Whether the microphone
   captures speech on this machine cannot be verified from this session.
3. **No optional globe credentials.** The app logged
   `Google 3D Tiles unavailable, using the keyless globe`. Photorealistic 3D,
   Google place search and key-gated layers are unavailable until keys are added
   in the app's own **POWER UP** panel. Nothing was faked around this.
4. **TeleGeography dataset is NonCommercial.** Commercial use requires removing
   or licensing that dataset. Recorded in `research/RESOURCE_INVENTORY.md`.
5. **Windows-only host.** The app is Windows-first; the globe service path is
   Node-based and portable, but only Windows was exercised.
6. **The exact upstream commit is not recorded.** The checkout was cloned, but
   `integrations/gods_eye_view/.git` was not retained, so the working copy cannot
   be tied to a commit hash after the fact. It is identified instead by version
   (`0.3.0`), file count (2206 excluding `node_modules`/`.gev-cache`) and the
   SHA-256 of `package.json`, `package-lock.json` and `LICENSE` — recorded in
   `research/RESOURCE_INVENTORY.md`. Re-cloning upstream today would *not* prove
   what was vendored, so no hash is claimed.
7. **7 pre-existing failures in `test_ua_integration.py`.** All seven trace to
   `MainWindow._open_project_agent` and the `_project_agent` overlay, neither of
   which exists anywhere in this checkout (`grep` finds them only inside the test
   file). This `ui.py` mounts no universal-agent launcher; it only calls
   `universal_agent.get_service().cancel_all()` on shutdown. Verified unrelated to
   the globe work: `MainWindow` constructs, shows and exits cleanly, and the globe
   method is present (`MAINWINDOW_OK` / `EXITED_CLEANLY`, `has_open_globe_workspace:
   True`, `has_open_project_agent: False`). Left failing rather than edited, because
   inventing a launcher to satisfy a test would be a fake feature.
