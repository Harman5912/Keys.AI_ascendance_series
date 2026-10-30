# Keys.AI — Checklist Results (self-audit)

Filled against `KEYS_AI_IMPLEMENTATION_VERIFICATION_CHECKLIST.md`. The blank
instrument is left untouched; this file maps to it item for item.

**This is a self-audit, not an independent one.** It was produced by the same
agent that did the work, so treat it as a claim set with evidence attached, not
as a verdict. The independent pass described in §P has not happened.

Audited: 2026-10-29
Project: `C:\Users\harma\Desktop\PROJECTS\Keys-acendence-series\acendence-VIII_GEN-I`
Revision: **no VCS.** `git rev-parse` → `fatal: not a git repository`. Identified
by file set instead (`ui.py` 6771 lines, `main.py` 1500 lines, `globe/` 6 modules).
Environment: MINGW64_NT-10.0-26300 · Python 3.12.10 · Node v26.5.0 · npm 11.17.0 ·
PyQt6 Qt 6.11.0 (QtWebEngine + QtWebChannel importable) · voice via Gemini Live.

**Status vocabulary used:** `PASS`, `FAIL`, `BLOCKED`, `NOT TESTED`, `N/A`,
plus `PARTIAL` where a criterion is partly met — counted under `FAIL` in the
scorecard, because a partly-met requirement is not met.

---

## A. Evidence package and baseline

| ID | Status | Evidence |
|----|--------|----------|
| A1 | PASS | Project root above; 15 top-level Python modules incl. `main.py`, `ui.py`, `globe/` |
| A2 | FAIL | `git rev-parse --short HEAD` → `fatal: not a git repository`. No branch, no commit |
| A3 | BLOCKED | Cannot prove preservation without VCS or a pre-change snapshot. No destructive commands were run; edits were `str_replace` on `ui.py`/`main.py`/`core/tool_*.py` plus new files |
| A4 | PASS | `uname -a`, `python --version`, `node --version`, `npm --version`; PyQt6 Qt 6.11.0 import check |
| A5 | FAIL | No baseline was captured before the change. Post-change only |
| A6 | PASS | 26 unit tests + 97 subtests; 17 live checks (exit 0); 4 pre-existing suites (62 passed / 7 pre-existing failures) |
| A7 | PASS | `KEYS_AI_DEVELOPMENT_AGENT_ROADMAP.md` uses `VERIFIED` / `PARTIAL` / `IN_PROGRESS` / `NOT_VERIFIED_HERE`; 7 numbered blockers |
| A8 | PASS | Regex scan (`AIza…`, `sk-…`, `nvapi-…`, `ghp_…`) over `globe/`, `research/`, `docs/`, both root docs → no matches |

## B. Repository and architecture audit

| ID | Status | Evidence |
|----|--------|----------|
| B1 | PASS | `main.py::main()` → `ui.KeysAIUI` + `KeysAILive`; `if __name__ == "__main__"` guard |
| B2 | PASS | PyQt6 `QMainWindow` (`ui.py:4333`); routing via `_show_center_view` (`ui.py:5304`), `_center_stack`/`_content_stack` (`ui.py:5843`), `run_on_gui_thread` (`ui.py:5341`) |
| B3 | PASS | Desktop Python app; the only Node process is the globe service |
| B4 | PASS | `actions/crown_code.py` (job phases, `DevEvent`), `core/tool_registry.py`, `core/tool_declarations.py`, `core/engine/` |
| B5 | PASS | `core/research_browser/` (tabs, screenshots, downloads, licence status), `main.py::_receive_audio` (voice), `core/audio_devices.py`, `core/undo.py`, `core/confirm.py`, 73 test files |
| B6 | PASS | Reused `_show_center_view`, `core/research_browser`, the tool registry. No second agent, browser or model router was created |
| B7 | PASS | `requirements.txt`; `package.json` engines `>=24.14.0 <25 \|\| >=26 <27`; lockfile v3 |
| B8 | PASS | `MainWindow('icon.png')` constructed, `.show()`n, `app.exec()` exited → printed `MAINWINDOW_OK` then `EXITED_CLEANLY`. A full assistant turn was **not** exercised (needs a live key + mic) |
| B9 | PASS | `docs/DEVELOPMENT_AGENT_ARCHITECTURE.md`, `docs/GLOBE_INTEGRATION.md` cite `file:line` for each claim |

## C. Requirements gathering and task planning

| ID | Status | Evidence |
|----|--------|----------|
| C1 | PASS | `actions/crown_code.py` returns `NEED REQUIREMENTS`; `REQUIREMENTS.md` records this change's inputs |
| C2 | PASS | `core/model_catalog.py`, `core/api_config.py` inspected rather than assumed |
| C3 | PASS | `clarify` action lists missing slots rather than guessing |
| C4 | PASS | `REQUIREMENTS.md`: confirmed, assumptions, open questions, acceptance criteria |
| C5 | PASS | Roadmap phases A–G with stable IDs |
| C6 | PASS | Roadmap rows carry ID, task, files, evidence |
| C7 | PASS | Statuses distinguish `VERIFIED`, `PARTIAL`, `IN_PROGRESS`, `NOT_VERIFIED_HERE`, `NOT TESTED` |
| C8 | FAIL | Resumption was not demonstrated or tested for this work stream. The pre-existing Crown Code job-resume claim was read, not exercised |
| C9 | PASS | Work continued past planning into implementation and verification |
| C10 | PASS | Roadmap section "Added during implementation" records X1–X5 discovered mid-work |

## D. Integrated web research

| ID | Status | Evidence |
|----|--------|----------|
| D1 | PASS | Research triggered by a real need: exact repo version, engine range, dependency set, licences |
| D2 | **FAIL** | Research was done with HTTP fetches (`web_search`, `read_url` on `raw.githubusercontent.com`) and `git clone` — **not** through the app's `core/research_browser` tool. The integrated browser was inventoried but not used to gather this material |
| D3 | PASS | Actual pages and source files opened, not titles collected |
| D4 | PASS | `README.md`, `package.json`, `DATA_SOURCES.md`, `LICENSE`, `src/app/tools.js`, `src/voice/*.js` read from the checkout |
| D5 | PASS | Canonical URL recorded in `research/RESOURCE_INVENTORY.md` |
| D6 | PASS | Inventory has a file → why-read table; roadmap cites the files decisions came from |
| D7 | PASS | Engine range and installed versions verified against the manifest, not memory |
| D8 | PASS | Unavailable keys (`AISSTREAM_API_KEY`, Google 3D tiles) recorded as limitations, not smoothed over |
| D9 | PASS | No invented endpoints or downloads; the "keyless globe" fallback is disclosed |
| D10 | PASS | Vendor docs treated as data; no instruction from them was executed |

## E. Imported repositories, files, assets, data

| ID | Status | Evidence |
|----|--------|----------|
| E1 | **FAIL** | No commit/tag recorded. Version `0.3.0` + SHA-256 only |
| E2 | PASS | `git clone` of `bilawalsidhu/gods-eye-view` performed |
| E3 | PASS | 2206 files / 516 MB at `integrations/gods_eye_view/` |
| E4 | PASS | `package.json`, `package-lock.json`, `LICENSE`, `README.md`, `src/`, `CONTRIBUTING.md`, `SECURITY.md`, `DATA_SOURCES.md` present |
| E5 | PASS | File count + SHA-256 of `package.json`, `package-lock.json`, `LICENSE` in `RESOURCE_INVENTORY.md` |
| E6 | PASS | Lockfile resolution: cesium 1.138.0, vite 6.4.3, satellite.js 6.0.2; `npm ci` completed |
| E7 | PASS | Server serves the app on 4173 and the page initialises (live probe, 17/17) |
| E8 | PASS | `globe/service.py` and `globe/workspace_ui.py` reference the vendored path; removing it makes the integration fail loudly (`globe/install.py`) |
| E9 | N/A | No standalone image/model/animation assets were imported |
| E10 | N/A | Same |
| E11 | N/A | No external document/dataset was parsed |
| E12 | N/A | Same |
| E13 | PASS | No placeholder records; the command surface is the app's own `voiceCommands.runner` |
| E14 | PASS | `LICENSE` kept; MIT recorded; TeleGeography **NonCommercial** flagged |
| E15 | PASS | Secret scan clean; no keys were imported |
| E16 | PASS | Lifecycle test stopped and restarted the service and re-served the app |

## F. Free asset sources and licences

All **N/A** (F1–F13): no React Bits / Magic UI / Motion / Three.js / Lottie / Lucide /
Poly Haven / ambientCG / Unsplash / Pexels / Google Fonts material was added. The
host UI is PyQt6, not React, so these libraries do not apply, and the globe ships
its own bundled assets unmodified.

## G. Multi-page and multi-UI project building

| ID | Status | Evidence |
|----|--------|----------|
| G1 | PASS | Globe identified as a fourth centre view beside Image Studio, Research Browser, presentations |
| G2 | PASS | `docs/GLOBE_INTEGRATION.md` documents hierarchy, navigation and return path |
| G3 | PASS | PyQt6 + QtWebEngine, matching the existing app |
| G4 | PASS | Workspace backed by the real local service (live probe) |
| G5 | N/A | No forms were added |
| G6 | N/A | No new search/upload/export controls; the app's own controls are untouched |
| G7 | PASS | `globe/workspace_ui.py` has explicit loading, ready and error states; readiness failure gives an actionable WebGL hint |
| G8 | N/A | Desktop app; no responsive layout work |
| G9 | N/A | No reference images used |
| G10 | PASS | No mock globe; the real application renders and flies |
| G11 | PASS | No placeholder buttons. One `aria-hidden` warning originates in the vendor app, not Keys.AI |
| G12 | PASS | Close returns to the assistant; `aboutToQuit` tears down the service |

## H. Existing local models and routing

| ID | Status | Evidence |
|----|--------|----------|
| H1 | PASS | `core/model_catalog.py`, `core/llm_client.py`, `brain/providers/`, `core/gemini_ladder.py` read; nothing rebuilt |
| H2 | **FAIL** | Runtime availability not confirmed. `curl http://127.0.0.1:11434/api/tags` returned empty — Ollama is not listening |
| H3 | N/A | DeepSeek 4.1 Flash is this agent's model, not a configured Keys.AI provider; nothing to set |
| H4 | N/A | No model selection was changed |
| H5 | PASS | No new provider endpoints; nothing bypasses `get_llm(task)` / `complete()` |
| H6 | NOT TESTED | No provider request was issued (needs configured keys) |
| H7 | NOT TESTED | Timeout/invalid-model behaviour not exercised |
| H8 | NOT TESTED | No paid/cloud fallback observed because no request was made |
| H9 | N/A | No vision/embedding capability was used |
| H10 | NOT TESTED | Cancellation/provider switching not exercised |
| H11 | PASS | Secret scan clean in docs and new code |
| H12 | PASS | No "ran locally" claim is made anywhere; roadmap E5 is `NOT_VERIFIED` |

## I. God's Eye View integration

| ID | Status | Evidence |
|----|--------|----------|
| I1 | **FAIL** | Commit/branch not recorded (`.git` removed when vendoring) |
| I2 | PASS | Real clone, real source read — not a link or screenshot |
| I3 | PASS | README, manifest, engines, deps, data-source and licence notes checked |
| I4 | PASS | `integrations/gods_eye_view/`, source unmodified; no Keys.AI file replaced |
| I5 | PASS | Own `node_modules`, own service, own port; host Python env untouched; engine range validated |
| I6 | PASS | Real interactive 3D Earth renders; camera flies (probe) |
| I7 | PASS | Opens in Keys.AI's centre view via `_show_center_view("_globe_ws", …)` |
| I8 | PASS | `grep -i globe ui.py \| grep -i "button\|QPushButton\|toolbar\|action"` → only the comment "There is no globe button, by design" |
| I9 | **FAIL** | Assistant availability *during* globe use was not tested; only close → return |
| I10 | PASS | Reopen reuses the live page (`reopening reuses the live page`) |
| I11 | PASS | Two-phase readiness (`_wait_ready`): document, then runner |
| I12 | PASS | Close returns without restarting Keys.AI |
| I13 | **FAIL** | Busy/already-bound port was not tested. Shutdown, restart and adopt-vs-own were |
| I14 | PASS | Credentials, freshness, quotas and the NC dataset documented |

## J. Globe commands, voice, location precision

| ID | Status | Evidence |
|----|--------|----------|
| J1 | PASS | Tool + guard; live "the globe is open at …" |
| J2 | PASS | `"Open GRO."` routes in unit tests and in the live guard; `"grow the plant taller"`, `"how do I go home"` do not |
| J3 | **NOT TESTED** | No microphone was opened. Routing is verified by code path + synthetic transcripts only |
| J4 | PASS | `"Show me the Earth."` → `OPEN_GLOBE` |
| J5 | NOT TESTED | `"Show India"` parses correctly but was never flown live |
| J6 | PASS | Camera 26.459, 80.321 ≈ **2 km** from Kanpur (26.4499, 80.3319) |
| J7 | PASS | Resolved label "New Delhi, Delhi, India" |
| J8 | PASS | Eiffel Tower coordinates honoured within **0.2 km** |
| J9 | PASS | Explicit lat/lon used as-is, range-validated, not geocoded |
| J10 | PASS | Zoom in 205 m → 78 m |
| J11 | PASS | Reset → range 18,000,000 m (full Earth) |
| J12 | PASS | "Closed the globe." |
| J13 | NOT TESTED | Conversational-context resolution not implemented or tested |
| J14 | **FAIL** | Ambiguous names are not clarified; the geocoder's top hit is used and its label reported |
| J15 | PASS | Unknown action refused before reaching the page; failures surfaced verbatim |
| J16 | PASS | Success is read back from camera state / the app's own result, not from dispatch |
| J17 | **FAIL** | Recognition vs routing vs execution failures are not systematically distinguished |
| J18 | PASS | Every report states the microphone was not tested |

## K. Globe layers and real data

| ID | Status | Evidence |
|----|--------|----------|
| K1 | PASS | Every alias asserted against `src/voice/layerManifest.js` (`id: '<layer>'`) — invented ids fail the test |
| K2 | NOT TESTED | Aircraft not toggled and inspected |
| K3 | NOT TESTED | Vessels unavailable: `AISSTREAM_API_KEY not set` |
| K4 | NOT TESTED | Satellites not toggled |
| K5 | NOT TESTED | Earthquakes not toggled |
| K6 | NOT TESTED | Weather/CCTV not toggled |
| K7 | PASS | Missing providers produce clear log/status errors, not silence |
| K8 | PASS | No fabricated feed anywhere |
| K9 | PASS | Source/freshness limitations documented |
| K10 | NOT TESTED | A single toggle answered `ok`; state duplication was not exercised |

## L. Security and safe execution

| ID | Status | Evidence |
|----|--------|----------|
| L1 | PASS | Pre-existing path validation; globe paths confined to the vendored dir |
| L2 | PASS | Repository inspected before `npm ci`; postinstall scripts were blocked by npm's allow-scripts policy |
| L3 | PASS | Web/repo content treated as data, never as instructions |
| L4 | PASS | No elevated or destructive command was run |
| L5 | PASS | Secret scan clean |
| L6 | N/A | No files were downloaded as assets |
| L7 | PASS | MIT attribution retained; NC dataset restriction recorded |
| L8 | **FAIL** | Network loss during a globe session was not tested |
| L9 | PASS | The globe path uses no LLM; nothing was sent anywhere |

## M. Tests and regression

| ID | Status | Evidence |
|----|--------|----------|
| M1 | **FAIL** | `py_compile` passes on all edited files; no linter — `python -m ruff` → `No module named ruff` |
| M2 | PASS | 26 passed, 97 subtests (0.34 s) |
| M3 | PASS | 17 live checks, exit 0 |
| M4 | PASS | `npm ci`; server serves; lifecycle start/adopt/stop/restart |
| M5 | **FAIL** | No browser UI automation; the Qt probe is the only UI-level evidence |
| M6 | N/A | No research/asset import workflow exercised |
| M7 | NOT TESTED | No provider request made |
| M8 | PASS | Text-command paths covered by tool + guard tests |
| M9 | **FAIL** | No live voice test. Synthetic transcripts only (`TestVoiceRoutingGlue`) |
| M10 | **FAIL** | Ambiguity not implemented, so not testable |
| M11 | PASS | Shutdown, restart after stop, unknown action, cancelled-flight retry |
| M12 | **FAIL** | Only 4 pre-existing suites run; 7 pre-existing failures remain |
| M13 | PASS | 4 parser bugs, 1 JS-contract bug, 1 result-envelope bug found and fixed; suites re-run green |
| M14 | PASS | This document separates PASS/FAIL/BLOCKED/NOT TESTED |
| M15 | PASS | Commands and outputs quoted, not paraphrased |

## N. Documentation and delivery

| ID | Status | Evidence |
|----|--------|----------|
| N1 | PASS | Roadmap updated to today's counts (26 tests, regression numbers, 7 blockers) |
| N2 | PASS | `REQUIREMENTS.md`, `docs/DEVELOPMENT_AGENT_ARCHITECTURE.md` match the code |
| N3 | PASS | `docs/GLOBE_INTEGRATION.md`: commands, setup, limitations, troubleshooting |
| N4 | **FAIL** | `RESOURCE_INVENTORY.md` has URLs, version, checksums and licences but **no commit hash** |
| N5 | N/A | No assets to attribute |
| N6 | PASS | `npm ci` and `python -m pytest …` commands work as written |
| N7 | PASS | Roadmap lists 7 numbered blockers |
| N8 | PASS | Final report lists changed files, tests, outcomes |

## O. High-priority acceptance gate

| ID | Status | Note |
|----|--------|------|
| O1 | PASS | File set known, no VCS |
| O2 | **FAIL** | Window constructs and exits cleanly, but a live assistant turn was never exercised |
| O3 | NOT TESTED | Requires configured providers |
| O4 | **FAIL** | Research bypassed the integrated browser (see D2) |
| O5 | PASS | Real clone, 2206 files, checksums, and the app imports and runs it |
| O6 | PASS | Real repository integrated |
| O7 | PASS | No globe button |
| O8 | PASS | Text command opens it |
| O9 | **FAIL** | No live voice test; route exists and is wired, but was not exercised with a microphone |
| O10 | PASS | Kanpur 2 km, Eiffel 0.2 km, explicit coordinates preserved |
| O11 | PASS | Refusals and keyless fallbacks reported, never faked |
| O12 | **FAIL** | Known failures and untested paths remain |

---

## Scorecard

| | |
|---|---|
| Applicable items | 176 |
| PASS | 111 |
| FAIL | 22 |
| BLOCKED | 1 |
| NOT TESTED | 15 |
| N/A (with rationale) | 27 |
| High-priority gates | **7 / 12** |

**Critical failures**

1. `D2` / `O4` — research used raw HTTP + git, not the app's research browser.
2. `J3` / `O9` — no live-microphone test of the voice route.
3. `J14` / `M10` — ambiguous place names are not clarified.
4. `A2` / `A5` — no VCS and no pre-change baseline.
5. `M12` / `O12` — 7 pre-existing failures left unresolved; `E1`/`I1`/`N4` no commit hash.

**Recommended status: `PASS WITH LIMITATIONS`**

The globe is real, integrated, and measured: it renders, flies to correctly
resolved places, zooms, resets, reuses its instance, refuses unknown actions and
shuts down cleanly, with no globe button added and no existing feature replaced.
The limitations above are real and are not hidden by that.

**What an independent reviewer still needs:** a configured API key to exercise a
live assistant turn, a microphone to test voice end-to-end, and either a git
baseline or a pre-change archive to judge regressions rather than infer them.

---

## Addendum — changes made after this audit

This snapshot was taken before the following work. It is recorded here so the
verdict above is not mistaken for covering it.

| Item | Change | Evidence |
|------|--------|----------|
| `D2` / `O4` (research bypassed the app's browser) | `core/research_step._search_for_query` was a placeholder returning `None`; it now uses `actions.web_search._web_results`, so browser research discovers its own pages | Live call returned `docs.python.org/3/library/asyncio.html`; 6 mocked-search tests |
| Research browser launcher | Sidebar button and F1 palette entry removed; `open` action added to the `research_browser` tool so text/voice open it | `test_research_browser_routing.py` (14 tests), including source assertions that the entry points stay gone |
| Research browser width | Sidebar 320→190 px, split 5:2→9:2, `SCREENSHOT`/`FULL PAGE`/`A-`/`A+` removed | Widget built offscreen; button set asserted; splitter sizes read |

| Design system | `core/design_system.py` — deterministic palette, WCAG-checked pairs, CSS + Qt + prompt renderers, layout patterns per target | 84 combinations pass `selftest()`; 27 tests, including one that `exec`s the generated `app/theme.py` as real Python |
| Design gate | `core/design_check.py` — contrast, placeholder copy, broken local images, type/spacing scales, and an empty folder counts as a failure | Wired into `crown_code` for UI builds only; 14 gate tests including "empty project must fail" |
| Pre-existing `NameError` | The `research_mode`/browser-tools block lived inside the `on_event` closure with no `p` in scope, so it raised on every event and the browser-tool merge never ran | Moved to the caller that owns the params; `test_crown_build_verification` 6 failed → 3 passed |

Regression after these changes: browser suites 10+40+20+26+24+6, globe 26,
tool-surface 20+10, crown 27+6+3, app_builder 18, design 27 — all passing.
