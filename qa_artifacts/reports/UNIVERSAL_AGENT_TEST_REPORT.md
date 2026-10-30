# Universal Project Agent — implementation, test matrix and honesty report

Environment: Windows, Python 3.12, PyQt6 (offscreen for UI tests), Playwright
Chromium available. No GPU/ComfyUI, no cloud provider credentials, and the
workspace is **not a git repository**, so no commit-level baseline diff exists.

User guide: `UNIVERSAL_PROJECT_AGENT.md`.

---

## A. Repository impact

### Added — feature

| File | Purpose |
|---|---|
| `universal_agent/__init__.py` | Shared service accessor |
| `universal_agent/models.py` | Task dict, statuses, transition table, JSON persistence, audit log, recovery classification |
| `universal_agent/security.py` | Workspace containment, filename sanitising, unique paths, input limits, approval policy, secret redaction, audit formatting |
| `universal_agent/intake.py` | Request classification, clarification questions, defaults/assumptions, project brief |
| `universal_agent/planner.py` | Deterministic step plans per intent, optional model refinement with validation of worker names |
| `universal_agent/validation.py` | Reopens docx/pdf/pptx/xlsx/json/csv/py/html/text/image artifacts, reports real structure |
| `universal_agent/service.py` | Orchestration: create/answer/start/resume/approve/cancel, step execution, timeout guard, bounded repair, validation gate, artifact registry, events, reports |
| `universal_agent/studio_ui.py` | The Project Agent overlay (plan, activity, questions, approval, artifacts, brief) |
| `universal_agent/workers/__init__.py` | Worker context/registry and the app's real completion/search/fetch defaults |
| `universal_agent/workers/research.py` | Search → fetch → evidence register → cited report, now including GitHub inspection |
| `universal_agent/workers/software.py` | Delegates builds to Crown Code, scans the project, registers real files |
| `universal_agent/workers/documents.py` | Word/PDF/PowerPoint/Excel via the existing Office builders |
| `universal_agent/workers/data.py` | CSV/XLSX profiling, aggregates, workbook + chart + analysis report |
| `universal_agent/workers/images.py` | Pillow inspect/resize/crop/rotate/convert; generation through the local image backend |
| `universal_agent/workers/browser.py` | Read-only Playwright navigation, screenshot, download, audit |
| `universal_agent/tools/__init__.py` | Tools package marker |
| `universal_agent/tools/github.py` | Public GitHub REST inspection: metadata, license, README, source files, releases |

### Added — tests

`qa_artifacts/regression_tests/`: `test_universal_agent_core.py`,
`test_universal_agent_workers.py`, `test_universal_agent_ui.py`,
`test_ua_research_github.py`, `test_ua_software.py`, `test_ua_documents.py`,
`test_ua_data.py`, `test_ua_images.py`, `test_ua_browser.py`,
`test_ua_providers.py`, `test_ua_security.py`, `test_ua_integration.py`.

### Added — documentation

`UNIVERSAL_PROJECT_AGENT.md`, this report, and the raw suite log
`qa_artifacts/reports/universal_agent_full_suite.log`.

### Modified

| File | Change | Why |
|---|---|---|
| `ui.py` | `_open_project_agent` overlay launcher, left-panel button, shutdown of overlay + task cancellation | Integration through the existing window, panel and overlay pattern |
| `brain/providers/openai_compat.py` | Endpoint selection no longer posts to a bare `/v1` base | A user-configured `llm_url` such as `http://host:1234/v1` (LM Studio/vLLM) used to 404 |

No file was deleted or renamed. No dependency was added: everything used is
already in `requirements.txt` (`PyQt6`, `Pillow`, `requests`, `openpyxl`,
`python-docx`, `python-pptx`, `pypdf`, `playwright`, `beautifulsoup4`).

### Defects found by the new tests and fixed

1. `workers/images.py` — a single resize dimension (`width` or `height`) was
   discarded and the image was silently halved instead.
2. `workers/images.py` — "remove the background"/"blur" requests fell through to
   a plain *inspection* of the unchanged file; they now report the operation as
   unsupported and list what is supported.
3. `workers/research.py` — a repository-only request failed with "No search
   results" although the repository itself was inspectable.
4. `workers/browser.py` — opening a direct file URL produced a cryptic
   Playwright "Download is starting" error and lost the file; it is now saved
   and audited.
5. `service.py` — an approval decision arriving while the request was being
   emitted found no wake-up event and the task waited out the full 5-minute
   timeout; the event is now registered before the request is announced.
6. `service.py` — `report_text()` did not state the outcome or per-artifact
   validation status.
7. `workers/software.py` — a cancelled task could still start a build.
8. `brain/providers/openai_compat.py` — a base URL that already ends in `/v1`
   (the catalogue's OpenAI/OpenRouter/NVIDIA URLs, and LM Studio/vLLM setups)
   was posted to verbatim, i.e. to `/v1` instead of `/v1/chat/completions`.
   Found while writing the provider tests; existing provider tests still pass.

---

## B. Feature map

| Requested capability | Implementation | Interface | Validation | Tests |
|---|---|---|---|---|
| Requirements interview | `intake.analyse` | overlay QUESTIONS tab, `service.answer` | required vs optional, assumptions recorded | A (Intake, Service) |
| Planning with acceptance criteria | `planner.build_plan` | plan list, BRIEF tab | deterministic spec + model plan filtered to known workers | A (Planner) |
| Task state, pause, resume, persistence | `models`, `service` | RECENT TASKS, RESUME | transition table, reload from disk | A, J |
| Research with evidence | `workers/research.py` | ARTIFACTS / report | every finding carries a citation; sources table | B |
| GitHub repository inspection | `tools/github.py` | research step | API facts only; license/release/date reported | B |
| Software construction/repair | `workers/software.py` → Crown Code | workspace files | file scan + artifact re-open; tests/build results come from Crown Code | C |
| Document creation/reading | `workers/documents.py`, `actions/_file_readers.py`, `validation` | artifacts | reopened with docx/pptx/openpyxl/pypdf | D |
| Spreadsheet analysis | `workers/data.py` | artifacts | values recomputed in tests; workbook reopened | E |
| Image operations | `workers/images.py` (Pillow) | artifacts | output re-decoded, dimensions checked | F |
| Image generation | `workers/images.py` → `core.image_studio` | artifacts | produced file decoded; backend state reported | F (mocked/injected backend only) |
| Browser inspection | `workers/browser.py` (Playwright) | artifacts + audit | HTTP status, rendered text, screenshot, download checks | G (real Chromium, local server) |
| Provider/model compatibility | `brain/providers`, `core/llm_client` | AI Settings (existing) | scripted HTTP responses; failure classification | H |
| Permissions, secrets, recovery | `security`, `service` | approval box, audit log | path resolution, approval gate, redaction, bounded repair | I |
| UI integration and regression | `ui.py`, `studio_ui.py` | Project Agent overlay | real launcher + real MainWindow subprocess smoke | J |

---

## C. Test matrix

### Counts by group (primary assignment; 328 total, all executed)

| Group | Scenarios | Files |
|---|---|---|
| A — requirements, planning, task state | 44 | `test_universal_agent_core.py` (State 10, Intake 13, Planner 8, Service 13) |
| B — research, GitHub, evidence | 29 | `test_universal_agent_workers.py::TestResearch` (8), `test_ua_research_github.py` (21) |
| C — software construction/repair | 26 | `test_ua_software.py` |
| D — documents and artifacts | 30 | `TestDocuments` (6), `test_ua_documents.py` (24) |
| E — spreadsheets and analytics | 38 | `TestData` (9), `test_ua_data.py` (29) |
| F — images and media | 38 | `TestImages` (10), `test_ua_images.py` (28) |
| G — browser automation | 27 | `TestBrowser` (4), `test_ua_browser.py` (23) |
| H — providers and models | 28 | `test_ua_providers.py` |
| I — security and recovery | 37 | core `TestSecurity` (10), `test_ua_security.py` (27) |
| J — integration and regression | 31 | core `TestService` (13), `test_ua_integration.py` (28), `test_universal_agent_ui.py` (3) |

Every group exceeds the 20-scenario floor. A scenario is one test method; most
contain several assertions. No scenario is counted twice.

### Execution status

| Status | Count | Notes |
|---|---|---|
| Passed | 327 | Run on this machine, in this workspace, against the real modules |
| Skipped | 1 | `test_ua_security.py::test_symlink_escape_is_refused` — symlink creation needs a privilege this user lacks on Windows |
| Failed | 0 | — |
| Not run | 0 in this matrix | See §E for capability tests that cannot be exercised here |

### How each group was executed

| Group | Real | Mocked / controlled |
|---|---|---|
| A | Service, state files, planner | Workers replaced by deterministic fakes |
| B | Report/citation code, GitHub parser | GitHub HTTP via injected reader; search/fetch fixtures |
| C | Worker, workspace scan, validators | Builder injected (Crown Code needs a local model + minutes) |
| D | Office builders, parsers, validators | Cover-image fetch disabled for speed |
| E | openpyxl/csv, real workbooks and CSVs | — |
| F | Pillow on real PNG/JPEG/WebP | Generation backend injected |
| G | Playwright + Chromium against a local HTTP server | Third-party sites not contacted |
| H | Provider classes, request building, error handling | HTTP replaced by scripted responses; no cloud call |
| I | Path, redaction, approval, repair, resume | Worker fakes |
| J | Real `MainWindow` launcher, real overlay, real window subprocess | Service/temp dirs patched |

### Commands and results

```
python -m pytest qa_artifacts/regression_tests -q
    -> 684 passed, 1 skipped, 32 subtests passed in 258.02s   exit 0
       (log: qa_artifacts/reports/universal_agent_full_suite.log)

python -m pytest qa_artifacts/regression_tests/test_ua_*.py \
                 qa_artifacts/regression_tests/test_universal_agent_*.py -q
    -> 327 passed, 1 skipped, 7 subtests passed in 58.24s     exit 0

python -m py_compile universal_agent/*.py universal_agent/workers/*.py \
                    universal_agent/tools/*.py ui.py main.py
    -> exit 0
```

The full-directory run includes the repository's pre-existing suites (image
studio, site builder, Crown jobs, Office builder, providers, security,
messaging, permissions). No pre-existing test was modified, disabled or
weakened, and none failed.

---

## D. Build and launch

| Check | Command | Result |
|---|---|---|
| All project modules compile | `python -m py_compile …` | exit 0 |
| Tests collect | `pytest --collect-only` | 328 UA scenarios collected |
| Real main window starts off-screen | subprocess: `ui._ensure_gui_imports(); ui.MainWindow('icon.png'); show(); QTimer 1.2s; quit()` | prints `MAINWINDOW_OK` then `EXITED_CLEANLY`, exit 0 |
| Overlay opens through the real launcher | `MainWindow._open_project_agent` on a window stub | real `ProjectAgentOverlay` created, visible, correctly sized |
| Overlay is reachable from the UI | left-panel button wired to `_open_project_agent` | asserted in `test_ua_integration.py` |
| Shutdown path | `KeysAIUI._shutdown_image_studio` | overlay stopped, tasks cancelled, studio service shut down |

Prerequisites for a manual launch: the app's normal environment (the same one
that runs `python main.py`). No new environment variable is required.

---

## E. Blocked / not exercised here

| Blocked item | Why | What is verified instead |
|---|---|---|
| Real ComfyUI image generation | No ComfyUI server or GPU model installed in this environment | Worker handling of a real produced file, an unavailable backend, an auth error, a timeout and an unreadable file |
| Real Crown Code software build | Needs the local coding model and minutes of generation | Worker contract, workspace containment, file registration, validator verdicts; Crown Code itself is covered by its own pre-existing tests |
| Cloud provider round-trips | No credentials are configured for this run, and secrets must not be fabricated | Request shape, auth header, 401/timeout/rate-limit classification, fallback rotation (scripted HTTP) |
| Symlink escape | Windows symlink creation needs a privilege this user lacks | Parent-traversal and absolute-path escapes (same guard), skipped with the real reason |
| End-to-end voice/chat session | Requires microphone, camera and a display | Provider construction, tool registry, MainWindow construction, overlay interaction |

---

## F. Honesty report

**1. Implemented and verified**

* Intake questions, defaults, assumptions and the project brief.
* Task state machine, persistence, events, resume after restart, cancellation,
  bounded repair, artifact registry with SHA-256 and validation results.
* Approvals: approve, reject (fails the step and the task), timeout, audit, and
  no double-decision.
* Artifact validation that reopens docx/pdf/pptx/xlsx/json/csv/py/html/md/images.
* Research: search/fetch, evidence register, citation mapping, limitations,
  snippet labelling, conflict visibility (both claims quoted), GitHub API
  inspection (metadata, license, README, real source files, releases).
* Software worker contract and workspace containment (Crown Code delegation).
* Document, spreadsheet and image workers on real files.
* Read-only browser worker with screenshots, downloads and an audit trail.
* Provider resolution, request shape and error classification; existing chat
  provider path still builds.
* Security: traversal/absolute escape refusal, filename sanitising, no-overwrite,
  input size/type limits, secret redaction in events, errors and externally
  sourced report text.
* UI integration: launcher, overlay, questions, approvals, artifacts, brief,
  shutdown; the real main window starts and exits cleanly off-screen.

**2. Implemented but only partially verified**

* Model-assisted planning: the deterministic plan and the rejection of invented
  worker names are tested; a live model's plan quality is not.
* Image generation: the worker/back-end contract is tested; no diffusion model
  produced an image here.
* Software builds: the delegation and verification path is tested; no real Crown
  Code build was run in this session.
* Browser downloads: verified against a local server; a third-party site's
  download behaviour is untested.
* Research quality: citation integrity and evidence discipline are tested;
  factual accuracy of external pages is not something a test can establish.

**3. Blocked by environment**

Real ComfyUI generation (no GPU/backend), real cloud provider calls (no
credentials), real Crown Code build (local model + time), symlink test (Windows
privilege), voice/chat end-to-end (hardware + display).

**4. Not implemented**

* Skills as a separate versioned registry (procedures live in the planner and
  the workers).
* Per-worker model routing / model budgets.
* Browser write actions: form filling, sign-in, clicks, persistent auth, human
  takeover, pagination beyond page one.
* AI image editing (background removal, inpainting) and image-to-image.
* Research over local documents inside a research task.
* Claim clustering / contradiction resolution; the report shows both sides but
  does not adjudicate.
* OS-level isolation (VM/container) for generated code; containment is by path
  checks plus Crown Code's command policy.
* Spreadsheet formula evaluation, forecasting or statistical tests.
* PowerPoint→PDF conversion and visual (render) checks for overflow.

**5. Pre-existing failures detected**

None observed in `qa_artifacts/regression_tests` after the change: every
pre-existing test in that directory passes. A strict before/after comparison is
not available — the workspace is not a git working tree, so there is no commit
baseline, and no full-suite run was recorded before the new modules were added.
What limits the risk is the shape of the change: `ui.py` only gained new methods
plus one button, and the provider change is confined to `OpenAICompatProvider`'s
endpoint string.

**6. Unresolved issues**

* Test isolation on teardown: a task thread finishing as its temp directory is
  removed used to raise a harmless `FileNotFoundError`. The core test base now
  cancels and joins its services, and the warning is gone; the production code
  path is unchanged (a task save after app exit is already best-effort).
* The overlay's artifact "OPEN" uses the OS association; on a machine without a
  handler for a type, nothing happens (no error is surfaced).
