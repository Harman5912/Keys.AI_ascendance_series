# Browser + Visual Research + Universal Asset Integration — Status

## What shipped
- Real Chromium workspace (`core/research_browser/*`) rendered through QtWebEngine inside the existing home screen, controlled by the same service the agent uses.
- Tab system, navigation toolbar, loading state, address/search bar, back/forward/reload/stop, new/close/duplicate tab, zoom, find, copy URL, open externally, screenshot (viewport, full-page, element), image discovery/download with signature + dimension + size validation, research source/evidence records, asset library, and project/desktop/web/image-studio integration helpers.
- `research_browser` tool wired into the agent tool interface.
- UI entry point added to `ui.py` alongside the existing Project Agent / Image Studio controls; existing home screen, voice, monitor, activity log, and command input left intact.
- QA: browser test groups A–E implemented and running; acceptance workflows wired; paper compatibility tests written for document/web/desktop/Android artifact integration where the runtime library is present.

## Current verification state
- `test_browser_acceptance.py` + related browser suites: **126 passed** in ~19s (ran twice; stable).
- Companion suites `test_provider_fallback.py`, `test_image_studio.py`, `test_universal_agent_core.py`, `test_universal_agent_workers.py`, `test_universal_agent_ui.py`: **134 passed, 15 subtests passed** in ~34s.
- Targeted smoke run `test_image_studio_ui.py`, `test_browser_ui.py`, `test_browser_workspace.py`, `test_browser_security.py`: **79 passed** in ~16s.
- Full matrix run previously observed: stable end-to-end pass before pauses/timeouts.

## Known runtime noise
- Console warnings like:
  - `Release of profile requested but WebEnginePage still not deleted. Expect troubles !`
  appear during browser teardown. They are teardown noise, not test failures; the suite still passes. They are on the cleanup follow-up list below.

## What is done vs what still needs a pass
1. ✅ Real browser exists and is controllable by the agent.
2. ✅ Agent and visible browser share the same session/tab model.
3. ✅ Screenshots are captured from the real page and saved/verifiable.
4. ✅ Image download + validation + provenance store implemented.
5. ✅ Research source/evidence records and library persistence implemented.
6. ✅ Project integration helpers exist and are exercised in tests where deps allow.
7. ⚠️ Document/web/desktop/Android artifact integration has paper tests, but some end-to-end integration cases still depend on the environment actually having the target framework/library to launch or reopen. Those are recorded as blocked/skipped where the runtime is absent.
8. ⚠️ The 100-scenario browser/asset target is largely covered by the existing browser suites; the final reconciliation pass should inventorize exactly which test IDs map to the directive's Group A–E lists and flag any gaps explicitly.

## Immediate next verification before calling this done
1. Re-run the full browser + companion suites one more time cleanly and capture the summary line.
2. Explicitly compare the executed test IDs against the directive's 5×20 scenario list and the 6 acceptance tests; note any skipped/blocked items with the reason.
3. If the teardown warning matters to the user, decide whether to keep the shared Chromium profile (current behavior) or switch to per-task profiles; the code has the shared-profile path selected and the per-tab profile path removed to avoid cross-instance collisions.
4. Optionally run a real-public-source acceptance flow if network access is available in the environment; otherwise mark those acceptance cases as environment-blocked with the exact prerequisite.

If you want, I can run one consolidated verification pass now and then produce a final gap list against the directive's acceptance/scenario lists.
