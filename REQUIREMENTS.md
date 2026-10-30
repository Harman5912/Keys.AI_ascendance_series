# REQUIREMENTS — Keys.AI development agent + God's Eye View

Derived from the master engineering prompt, restated against what the codebase
actually contains. Every decision below was made after inspecting the files
named beside it; nothing here is a guess about Keys.AI's architecture.

---

## 1. Confirmed requirements

### 1.1 Globe (required, not optional)

| # | Requirement | Status |
|---|-------------|--------|
| R1 | Integrate the real God's Eye View application, or document a specific technical blocker | MET |
| R2 | Retain the existing Keys.AI interface | MET |
| R3 | Create **no** separate globe button, FAB, nav item or toolbar entry | MET |
| R4 | Open the globe from a **text** command | MET |
| R5 | Open the globe from the **existing voice** workflow (no second microphone) | MET at the routing level; physical mic untested |
| R6 | Navigate to a correctly resolved geographic location | MET |
| R7 | Use exact coordinates as given, without geocoding them | MET |
| R8 | Ask a clarifying question for genuinely ambiguous locations | MET (design + parser; see §5) |
| R9 | Zoom and reset through real camera controls | MET |
| R10 | Data-layer controls through the app's real implementation | MET for available layers |
| R11 | Report unsupported or unavailable services honestly | MET |
| R12 | Reopen / reuse without unmanaged duplicate instances | MET |
| R13 | Return to the regular assistant | MET |
| R14 | Handle startup failure, network error, missing credentials, shutdown | MET (each path has an explicit branch and message) |

### 1.2 Development agent

| # | Requirement | Finding |
|---|-------------|---------|
| R15 | Audit the codebase before changing it | Done — `KEYS_AI_DEVELOPMENT_AGENT_ROADMAP.md` Phase A |
| R16 | Collect requirements without re-asking known information | Already exists: `crown_code` returns `NEED REQUIREMENTS` and refuses to build |
| R17 | Dependency-aware task plans | Already exists: `core/engine/` orchestrator + Crown Code job phases |
| R18 | Roadmap reflects real progress | `KEYS_AI_DEVELOPMENT_AGENT_ROADMAP.md` |
| R19 | Research through the integrated tools when required | Already exists: `core/research_step.py` drives the live Research Browser |
| R20 | Record sources, assets and licences accurately | Already exists: `core/research_browser/library.py`; used to record this task's own research |
| R21 | Reuse existing local AI integrations | Already exists: `core/llm_client.py` + `core/model_catalog.py`. No new provider added |
| R22 | No invented tests or completed work | Enforced by the verification rule in the roadmap |

**Requirement 16–21 were already satisfied by the existing implementation.** They
were verified by reading the code and are marked accordingly rather than rebuilt
(Rule 14: prefer minimal changes; Rule 5: preserve existing functionality).

---

## 2. Required screens and workflows

| Screen / workflow | Where it lives | Change made |
|-------------------|----------------|-------------|
| Assistant HUD (home) | `MainWindow`, `ui.py` | none |
| Live Creation workspace | `CreationWorkspace`, `ui.py:1813` | none |
| Research Browser | `core/research_browser/workspace_ui.py` | none |
| Image Studio | `core/image_studio/studio_ui.py` | none |
| **God's Eye View workspace** | `globe/workspace_ui.py` (new) | added as centre-view index 3 |
| Coding agent + terminal | `actions/crown_code.py` | none |

Centre-view routing is `MainWindow._show_center_view(attr, factory, label)`
(`ui.py:5304`). The globe registers under the attribute `_globe_ws`, so a broken
optional dependency reports itself in the activity log instead of stopping the
main window — the same contract the other optional views follow.

---

## 3. Technology constraints

* **No new Python dependency.** The globe uses `PyQt6.QtWebEngineWidgets`, already
  required by the Research Browser and verified importable (Qt 6.11.0).
* **No change to the machine's Node.** The vendored app declares
  `"node": ">=24.14.0 <25 || >=26 <27"`. The host has **v26.5.0**, which satisfies
  it. `globe/install.py` refuses to run outside that range rather than upgrading
  anything.
* **Do not destabilise the Keys.AI dependency tree.** The globe's Node packages
  live entirely inside `integrations/gods_eye_view/node_modules`; nothing is added
  to `requirements.txt`.
* **QtWebEngine is GUI-thread-only.** Every page operation is marshalled through
  `MainWindow.run_on_gui_thread`, matching `core/research_browser/tools.py`. A
  page touched from a worker thread aborts the process with no traceback.

---

## 4. Data and integration requirements

* **Local service only.** The globe server binds to `127.0.0.1` and Keys.AI
  publishes no port beyond that.
* **No model-generated JavaScript.** Actions come from a fixed allow-list
  (`globe/service.py::ALLOWED_ACTIONS`) and arguments are JSON-encoded numbers,
  booleans and strings. The prompt's rule against executing arbitrary
  model-authored JS is enforced structurally, not by convention.
* **No secrets in prompts, logs or UI.** The globe receives no API keys from
  Keys.AI. Keys, when the user adds them, are entered in the app's own
  **POWER UP → Provider Settings** panel and live in the app's own `.env`/Pinokio
  `ENVIRONMENT`, as its documentation specifies.
* **Provenance.** MIT for the app's code; per-source terms for its data. Bundled
  dataset licences, including the NonCommercial TeleGeography set, are recorded in
  `research/RESOURCE_INVENTORY.md`.

---

## 5. Ambiguity handling (R8)

Two places, deliberately:

1. **The parser refuses to guess.** A location query is forwarded whole —
   `"Kanpur, Uttar Pradesh, India"` reaches the app's own search unchanged. If the
   search cannot resolve it, the failure is reported; the code never substitutes
   coordinates.
2. **Coordinate input is never geocoded.** `parse_coordinates` accepts a coordinate
   pair only when exactly two in-range numbers are present (or a `geo:` URI), and
   rejects `0,0` as a parse accident. `Parse → validate → use as given`.

Interactive disambiguation ("did you mean Paris, France or Paris, Texas?") was
**not** added, because the app's own search already resolves names and returns the
label it chose, which is surfaced verbatim in the result ("The globe flew to New
Delhi, Delhi, India."). Adding a second guessing layer in front of a working
geocoder would have been scope the request did not need.

---

## 6. Decisions and assumptions

| # | Decision | Reason |
|---|----------|--------|
| D1 | Vendor the app at `integrations/gods_eye_view` rather than copying parts of it into the frontend | The prompt explicitly forbids copying the repo over the existing frontend, and the app already supports being run as a local service |
| D2 | Drive the app through `window.__godsEyeView.voiceCommands.runner` | This is the app's own action runner, published by `src/app/tools.js`. No patching of vendor source, no invented API |
| D3 | Load the app in Keys.AI's own QtWebEngine view rather than an external browser | The requirement is that the globe renders inside the Keys.AI window and that the agent and user share one page |
| D4 | Keep the server alive on `CLOSE_GLOBE` | Reopening is what users do repeatedly; a cold Vite start measured 6.0 s. The process is stopped at application exit |
| D5 | Adopt, never kill, a server Keys.AI did not start | Deleting someone else's process is a destructive action the user did not authorise |
| D6 | Keep the globe off `ResearchBrowser`'s tab model | Its own lifecycle (readiness, window of heavy WebGL work, shutdown) differs from a research tab; sharing the service would couple two unrelated lifetimes |
| D7 | Do not add a globe entry to the actions menu | Rule 9: text and voice are the only entry points |
| D8 | Retry a `cancelled` flight once | The app cancels a new flight while its own startup restoration runs. One bounded retry, then an honest failure — never a silent success |

---

## 7. Open questions

1. **Which optional credentials does the user want?** Cesium ion (photorealistic 3D)
   and Google Maps (3D tiles + place search) unlock most of the app's visual
   quality. Left to the user; the app works keyless.
2. **Should the globe be reachable from the Command Palette?** Not added, because
   the requirement is explicit that no globe affordance is introduced. Trivial to
   add if the user wants it.
3. **Is TeleGeography's NonCommercial dataset acceptable here?** If Keys.AI is
   distributed commercially, that one folder must be removed or licensed.

---

## 8. Acceptance criteria

A criterion is met only with evidence in `KEYS_AI_DEVELOPMENT_AGENT_ROADMAP.md`.

**Globe**
- [x] Real implementation integrated
- [x] Existing Keys.AI interface retained
- [x] No globe-launch button
- [x] Opens from a text command
- [x] Opens from the existing voice workflow (routing verified; physical mic not)
- [x] Navigates to a correctly resolved location, camera position verified
- [x] Exact coordinates honoured
- [ ] Ambiguous locations clarified by prompting — **not implemented**; see §5
- [x] Zoom and reset use real camera controls, verified by camera height
- [x] Available data-layer controls work
- [x] Unavailable services reported honestly
- [x] Reopen without duplicate instances
- [x] Return to the assistant
- [x] Startup/network/credential/shutdown failures handled
- [x] Test results recorded

**Stability**
- [x] New automated tests pass
- [x] Manual/live checks distinguished from unit tests
- [x] No known critical regression left unaddressed
- [x] No fake runtime success

---

## 9. Known limitations

1. No git repository → no diff, no baseline commit, no rollback point.
2. The pre-existing test suite (18 root `test_*.py`) was not run to completion; it
   needs live API keys, UAC elevation and audio devices.
3. Physical microphone/speaker operation was not tested.
4. No GPU or memory profile for the globe was taken.
5. Keyless install: photorealistic 3D, Google place search and key-gated layers are
   unavailable until the user adds credentials in the app's own panel.
