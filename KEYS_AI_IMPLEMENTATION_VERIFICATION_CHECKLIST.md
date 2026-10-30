# Keys.AI Implementation Verification Checklist

**Purpose:** Use this checklist after DeepSeek 4.1 Flash has worked on the Keys.AI development-agent upgrade. Bring this file, the requested evidence, and (when possible) the relevant project files back for an independent audit.

**Important:** This is a verification instrument, not evidence that the work has already been completed. A checked box without supporting evidence is not a pass.

## How to record results

Use one of these statuses for every item:

- `PASS` — behaviour was tested and evidence supports the acceptance criterion.
- `FAIL` — tested and did not meet the requirement.
- `BLOCKED` — could not be tested because of a named external/environmental blocker.
- `NOT TESTED` — no valid test evidence yet.
- `N/A` — genuinely not applicable; explain why.

For every `PASS`, record **evidence**: file path and code location, exact command and output, test name, screenshot/video, log excerpt, resource URL, or observed runtime behaviour. “The AI says it works” is not evidence by itself.

Record a date, tested commit/hash (if Git is available), operating system, app version, and relevant runtime versions before auditing.

---

# A. Evidence package and baseline

- [ ] A1. The exact Keys.AI project/workspace being audited is identified.
- [ ] A2. Current branch and commit/hash are recorded, if Git is used.
- [ ] A3. Existing uncommitted user changes were preserved; no unexplained destructive changes occurred.
- [ ] A4. Operating system, Python version, Node.js/package manager versions (if relevant), UI framework, and runtime are recorded.
- [ ] A5. Baseline startup/build/test results from before implementation are available, or the absence of a baseline is explicitly noted.
- [ ] A6. Final startup/build/test results are available.
- [ ] A7. DeepSeek's final report distinguishes completed, partial, blocked, failed, and untested work.
- [ ] A8. Secrets, tokens, passwords, private keys, and sensitive user data are removed from shared logs/reports.

**Evidence to collect:** audit report, final report, Git status/diff, commands and test logs, app screenshots, package manifests and lockfiles.

# B. Repository and architecture audit

- [ ] B1. The real application entry points and startup flow were identified.
- [ ] B2. The existing UI framework and navigation/workspace mechanism were identified from code.
- [ ] B3. The Python/backend and frontend/service boundaries were documented accurately.
- [ ] B4. The current development-agent planning, tool-calling, code-writing, and execution paths were traced to real files/functions.
- [ ] B5. Existing voice, speech recognition, browser research, filesystem, shell, logging, cancellation, and test facilities were inventoried.
- [ ] B6. Existing functionality was reused where possible; duplicate or disconnected systems were not added without justification.
- [ ] B7. Dependency/version constraints were checked against actual manifests and lockfiles.
- [ ] B8. The project still starts, and important pre-existing workflows still work.
- [ ] B9. The architecture/audit documentation reflects the actual code rather than assumptions.

**Evidence:** `docs/DEVELOPMENT_AGENT_ARCHITECTURE.md` or equivalent, real file paths, startup logs, before/after diff, tests.

# C. Requirements gathering and task planning

- [ ] C1. The agent extracts requirements already given by the user before asking follow-up questions.
- [ ] C2. It inspects the repository to discover answers that can be established from code/configuration.
- [ ] C3. It asks focused questions only for missing information that materially affects the result.
- [ ] C4. It records confirmed requirements, assumptions, open questions, acceptance criteria, and constraints.
- [ ] C5. It creates an ordered task plan with dependencies and meaningful subtasks.
- [ ] C6. Each task has an ID, outcome, dependencies, affected files/modules, tests, status, and evidence.
- [ ] C7. Task statuses accurately distinguish `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`, and `VERIFIED` (or documented equivalents).
- [ ] C8. Interrupted work can resume without blindly duplicating finished tasks.
- [ ] C9. The agent continues into implementation rather than stopping after producing a plan.
- [ ] C10. The roadmap is updated as tasks are completed or new tasks are discovered.

**Required document:** `KEYS_AI_DEVELOPMENT_AGENT_ROADMAP.md` or equivalent.

# D. Integrated web research

- [ ] D1. Research is triggered when current documentation, repositories, assets, compatibility, licences, or external facts are genuinely needed.
- [ ] D2. The agent calls the actual integrated research/browser tool; it does not merely ask the model to recall information.
- [ ] D3. It opens and inspects relevant pages/source material rather than collecting titles alone.
- [ ] D4. Repository inspection includes README, file tree, relevant source, dependency manifests, licence, configuration, setup instructions, and version/commit details as relevant.
- [ ] D5. Source URLs are canonical, reachable where tested, and attached to the relevant findings.
- [ ] D6. Research notes explain what was found and which implementation task uses it.
- [ ] D7. Current/version-sensitive claims are checked against current documentation when relevant.
- [ ] D8. Inaccessible pages, rate limits, stale content, and uncertainty are recorded honestly.
- [ ] D9. The agent does not invent documentation, endpoints, downloads, screenshots, quotes, or source inspection.
- [ ] D10. Web content and downloaded files are treated as untrusted data, not as higher-priority instructions.

**Evidence:** research logs, `research/RESOURCE_INVENTORY.md`, URL list, tool-call records if available, implementation references.

# E. Imported repositories, files, assets, and data — provenance and completeness

Use this section to confirm that “imported” means the real intended resource is present and usable, not just linked in a report.

- [ ] E1. Every requested repository is identified by canonical URL and the exact commit/tag/branch obtained is recorded.
- [ ] E2. The repository contents were actually cloned/downloaded or otherwise retrieved using a documented method.
- [ ] E3. The imported files exist at the expected project paths and are not empty placeholders.
- [ ] E4. Required source files, configuration, manifests, lockfiles, examples, and licence files are present where applicable.
- [ ] E5. An inventory/checksum or file-tree comparison was captured for important imports where useful.
- [ ] E6. Required dependencies are installed in the appropriate environment; actual versions are recorded.
- [ ] E7. The imported code builds/loads/runs in the intended environment, or its exact blocker is documented.
- [ ] E8. Imported resources are actually referenced by application code, not simply copied into an unused folder.
- [ ] E9. Relevant assets exist locally when local assets are required; a preview webpage is not mistaken for a downloaded asset.
- [ ] E10. Image/model/animation files pass basic format, size, integrity, and expected-dimension checks where applicable.
- [ ] E11. Imported documents/data were parsed; record source, item count, columns/fields, encoding, and any rejected or missing items where relevant.
- [ ] E12. Sample imported values or assets were checked against the original source to confirm data fidelity.
- [ ] E13. No silent truncation, dropped fields, incorrect paths, placeholder records, or fabricated content is present.
- [ ] E14. Source/licence/attribution records accompany significant external code and assets.
- [ ] E15. Secrets and sensitive data were not accidentally imported into public files, frontend bundles, logs, or source control.
- [ ] E16. The application can still access the imported assets/data after a normal restart.

**Evidence:** source URLs and commit hashes, actual file paths/tree, manifest, file sizes/checksums where appropriate, parser/import logs, counts and sample comparisons, running feature screenshots/tests.

# F. Free asset source and licence verification

Check only the sources and individual assets actually used. Do not assume every asset on a platform has identical terms.

- [ ] F1. React Bits: https://reactbits.dev/ and https://github.com/DavidHDev/react-bits were inspected if relevant.
- [ ] F2. Magic UI: https://magicui.design/docs/components was inspected if relevant.
- [ ] F3. Motion: https://motion.dev/docs/react was inspected if relevant.
- [ ] F4. Three.js examples: https://threejs.org/examples/ and https://github.com/mrdoob/three.js were inspected if relevant.
- [ ] F5. LottieFiles: https://lottiefiles.com/free-animations/en and its relevant licence terms were checked if relevant.
- [ ] F6. Lucide: https://lucide.dev/ and https://github.com/lucide-icons/lucide were checked if relevant.
- [ ] F7. Poly Haven: https://polyhaven.com/ and/or ambientCG: https://ambientcg.com/ were checked if relevant.
- [ ] F8. Unsplash: https://unsplash.com/ and https://unsplash.com/license were checked for any used images.
- [ ] F9. Pexels: https://www.pexels.com/ and https://www.pexels.com/license/ were checked for any used assets.
- [ ] F10. Google Fonts: https://fonts.google.com/ was checked if fonts were added.
- [ ] F11. Each imported asset has an identifiable source, licence/usage note, and required attribution.
- [ ] F12. Assets load correctly in the app; there are no broken links or unintended runtime-only dependencies.
- [ ] F13. No premium, restricted, or incompatible asset is represented as freely reusable without evidence.

**Evidence:** asset manifest, filenames, licences, attribution, rendered UI, network/runtime checks.

# G. Multi-page and multi-UI project building

- [ ] G1. The agent identifies the actual required pages/workspaces and user journeys before building.
- [ ] G2. Page hierarchy, navigation, shared components, design tokens, and state/data flow are documented where needed.
- [ ] G3. The selected framework fits the existing application and requirements.
- [ ] G4. The frontend and backend are connected to real logic where required.
- [ ] G5. Forms validate and submit real data.
- [ ] G6. Search, upload, export, filters, navigation, selectors, and other visible controls perform their advertised actions.
- [ ] G7. Loading, error, empty, success, and cancellation states behave correctly.
- [ ] G8. Responsive layouts, keyboard use, and accessibility were checked where relevant.
- [ ] G9. Visual assets, screenshots, and reference styles are used lawfully and correctly.
- [ ] G10. No major feature is represented by fake data or a mock-only UI unless explicitly agreed and labelled.
- [ ] G11. No unexplained placeholder buttons, broken images, console errors, or failing requests remain.
- [ ] G12. The application still respects its normal launch, navigation, and shutdown behaviour.

**Evidence:** per-page screenshots, UI test output, browser console/network evidence, test cases for controls, related source paths.

# H. Existing local models and routing

- [ ] H1. Existing model/provider configuration was inspected rather than rebuilt without cause.
- [ ] H2. Model names/identifiers and local/cloud status were confirmed from runtime configuration.
- [ ] H3. DeepSeek 4.1 Flash is used for the intended engineering tasks if it is actually configured and available.
- [ ] H4. Other local models are selected only for capabilities they support.
- [ ] H5. Model requests use the established provider/router interface.
- [ ] H6. A real request/response test confirms the intended model ran.
- [ ] H7. Unavailable models, service failures, timeouts, and invalid model identifiers produce useful errors.
- [ ] H8. The system does not silently switch to a paid/cloud provider against user settings.
- [ ] H9. Vision, embeddings, image generation, or other specialised capabilities are only used when compatible models/tools are actually available.
- [ ] H10. Cancellation, retries, and provider switching do not corrupt ongoing tasks.
- [ ] H11. Keys and sensitive prompts are not exposed in logs or frontend bundles.
- [ ] H12. Claims of “local inference” are supported by evidence of the actual local provider invocation.

**Evidence:** configuration with secrets redacted, provider logs, model IDs, request/response test, local-service status.

# I. God's Eye View repository integration

**Official source:** https://github.com/bilawalsidhu/gods-eye-view

Useful source documents to verify against the actual current repository:
- README: https://github.com/bilawalsidhu/gods-eye-view/blob/main/README.md
- Package manifest: https://github.com/bilawalsidhu/gods-eye-view/blob/main/package.json
- Contributor instructions: https://github.com/bilawalsidhu/gods-eye-view/blob/main/CONTRIBUTING.md
- Data sources: https://github.com/bilawalsidhu/gods-eye-view/blob/main/DATA_SOURCES.md
- Security: https://github.com/bilawalsidhu/gods-eye-view/blob/main/SECURITY.md

- [ ] I1. The exact repository branch/tag/commit integrated is recorded.
- [ ] I2. The actual repository was retrieved and its code inspected; a screenshot or external link alone was not treated as integration.
- [ ] I3. README, package manifest, supported runtime, dependencies, setup steps, and relevant data-source/licence notes were checked against current source files.
- [ ] I4. The globe code is present in an appropriate location without overwriting unrelated Keys.AI code.
- [ ] I5. Its dependencies and runtime are compatible with the host app, or isolated in a documented separate environment.
- [ ] I6. The real globe application starts and renders a functioning interactive 3D Earth.
- [ ] I7. The globe opens in the existing Keys.AI application/workspace using the compatible integration architecture.
- [ ] I8. **No new globe-launch button, toolbar item, or separate globe-specific microphone button was added.**
- [ ] I9. The normal Keys.AI assistant remains available and works before and after globe use.
- [ ] I10. Repeated open commands reuse the managed instance or otherwise avoid unmanaged duplicate windows/processes.
- [ ] I11. Service readiness is checked before navigation; loading/error state is handled correctly.
- [ ] I12. The globe can close/return to the normal workspace without requiring a full app restart.
- [ ] I13. Startup, shutdown, port conflicts, service failure, network loss, and app restart are handled.
- [ ] I14. External provider credentials, data freshness, quotas, and licence limitations are documented accurately.

**Evidence:** real commit hash, file tree, dependency/build logs, runtime screenshot, process/log evidence, test results.

# J. Globe commands, voice commands, and location precision

- [ ] J1. Text command “open globe” opens the actual integrated globe.
- [ ] J2. A clear “open GRO” utterance/recognised transcript is routed as a globe alias without making ordinary unrelated words trigger it.
- [ ] J3. A supported live voice command opens the globe using the existing Keys.AI microphone and speech-recognition path.
- [ ] J4. “Show me the Earth” works.
- [ ] J5. “Show India” navigates to a suitable India-scale view.
- [ ] J6. “Zoom into Kanpur, Uttar Pradesh, India” resolves the correct Kanpur and navigates to it.
- [ ] J7. “Show New Delhi” resolves the intended city rather than a similarly named location elsewhere.
- [ ] J8. A named landmark (for example, the Eiffel Tower) resolves to the real geographic position.
- [ ] J9. Explicit latitude/longitude coordinates are validated and used without silently changing the destination.
- [ ] J10. “Zoom out” and “show the whole Earth” trigger the real camera controls.
- [ ] J11. “Reset globe” resets the actual view.
- [ ] J12. “Close globe” returns to the regular Keys.AI workspace.
- [ ] J13. Conversational references such as “zoom into the place we discussed” use context only when the target is unambiguous.
- [ ] J14. Ambiguous place names prompt a concise clarification instead of a guessed destination.
- [ ] J15. Failed geocoding/search returns a truthful error and does not claim success.
- [ ] J16. Navigation acknowledgement is based on the globe's action result or verifiable camera state, not merely command dispatch.
- [ ] J17. Voice-recognition errors can be distinguished from intent-routing and globe-execution errors.
- [ ] J18. The agent does not claim real microphone testing based solely on text-command tests.

**Evidence:** test utterances/transcripts, geocoding source and returned coordinates, camera state/logs, runtime screenshots, separate text and voice test outcomes.

# K. Globe layers and real data

- [ ] K1. Each advertised layer is confirmed to exist and be supported by the integrated repository/version.
- [ ] K2. Aircraft layer controls map to actual globe behaviour when configured.
- [ ] K3. Ship/vessel layer controls map to actual behaviour when configured.
- [ ] K4. Satellite layer controls map to actual behaviour when configured.
- [ ] K5. Earthquake layer controls map to actual behaviour when configured.
- [ ] K6. Weather and camera feeds are tested only when supported and configured.
- [ ] K7. Disabled/missing credentials and unavailable providers cause clear status/errors.
- [ ] K8. No fabricated live-data feed is presented as real.
- [ ] K9. Data source, freshness, limitations, and simulated/estimated status are disclosed when known and relevant.
- [ ] K10. Each layer can be toggled without duplicating or corrupting state.

**Evidence:** per-layer test log, configured provider details with secrets redacted, timestamps/source metadata, screenshots of toggled states.

# L. Security and safe execution

- [ ] L1. Filesystem paths are validated and destructive operations are guarded.
- [ ] L2. External repository/install scripts are inspected before execution.
- [ ] L3. Web pages and downloaded resources cannot override trusted agent instructions.
- [ ] L4. Command execution follows existing permissions/approval safeguards.
- [ ] L5. Secrets do not appear in code, reports, logs, screenshots, or public frontend bundles.
- [ ] L6. Asset downloads are validated before use.
- [ ] L7. The agent records licence/attribution information for significant reused assets and code.
- [ ] L8. Network failures, untrusted input, and malformed tool results are handled safely.
- [ ] L9. User data is not sent to unapproved cloud models or services.

# M. Test and regression results

- [ ] M1. Syntax, lint, formatting, and type checks were run where applicable.
- [ ] M2. Unit tests were run.
- [ ] M3. Relevant integration tests were run.
- [ ] M4. Build/package/startup checks were run.
- [ ] M5. UI/end-to-end tests were run where tooling permits.
- [ ] M6. Research and import/asset workflows were tested with real resources.
- [ ] M7. Local model routing was tested against the real provider.
- [ ] M8. Globe command tests were run for text requests.
- [ ] M9. Voice-path tests were run separately when possible.
- [ ] M10. Location precision/ambiguity tests were run.
- [ ] M11. Error, cancellation, network-loss, and shutdown paths were tested where relevant.
- [ ] M12. Existing chat, voice, coding-agent, terminal, browser research, file handling, and navigation workflows were regression-tested.
- [ ] M13. Failures were corrected and affected tests rerun.
- [ ] M14. Test results distinguish pass, fail, blocked, and not tested.
- [ ] M15. No test is reported as passed without the command, test result, or equivalent evidence.

# N. Documentation and delivery

- [ ] N1. Roadmap statuses match actual completion and evidence.
- [ ] N2. Requirements and architecture documents reflect the implementation.
- [ ] N3. Globe integration documentation describes actual commands, architecture, setup, limitations, and troubleshooting.
- [ ] N4. Resource inventory contains real source URLs, versions/commits, licences, findings, and usage locations.
- [ ] N5. Asset manifest/attributions are complete for assets actually used.
- [ ] N6. Run/build/test instructions work in the target environment.
- [ ] N7. Remaining work, environmental blockers, and known defects are listed explicitly.
- [ ] N8. Final report includes changed files, tests run, test outcomes, and evidence.

---

# O. High-priority acceptance gate

Do not call the project “fully verified” unless every applicable high-priority gate below passes.

- [ ] O1. The actual Keys.AI project was inspected; audit is tied to a known revision or file set.
- [ ] O2. The application starts and the existing core assistant still works.
- [ ] O3. Existing local-model integration works through the real provider path.
- [ ] O4. Research uses real integrated tools and records actual sources.
- [ ] O5. Imported code/assets/data have verified provenance and are genuinely used by the application.
- [ ] O6. The actual God's Eye View repository has been integrated or a specific unresolved blocker is identified.
- [ ] O7. There is no new globe-launch button.
- [ ] O8. A text command opens the globe.
- [ ] O9. An existing voice command opens the globe in a live or appropriately documented voice-path test.
- [ ] O10. A location request navigates to the correct real location with evidence.
- [ ] O11. Failure/ambiguity handling does not claim false success.
- [ ] O12. Relevant tests pass, and all known failures/blockers are disclosed.

## Final scorecard

Fill this in at audit time.

- Applicable checklist items: ____
- PASS: ____
- FAIL: ____
- BLOCKED: ____
- NOT TESTED: ____
- N/A (with rationale): ____
- Critical failures: ____
- High-priority acceptance gates passed: ____ / 12
- Recommended status: `PASS` / `PASS WITH LIMITATIONS` / `FAIL` / `INSUFFICIENT EVIDENCE`

**Scoring rule:** Do not let a high percentage conceal a critical failure. If the app cannot start, the imported globe is not real/usable, the required voice route is absent, the requested location is guessed rather than resolved, or important existing functionality is broken, do not label the overall result a full pass.

---

# P. Copy/paste prompt for the later independent audit

Use this prompt when the implementation is supposedly finished. Attach this checklist and provide the project archive/repository snapshot, DeepSeek's reports, test logs, screenshots, and relevant configuration files with all secrets removed.

> **Act as an independent software verification engineer. Audit the attached Keys.AI implementation against `KEYS_AI_IMPLEMENTATION_VERIFICATION_CHECKLIST.md` and the original engineering requirements. Do not trust DeepSeek's completion claims without evidence. Inspect the actual source files and available test evidence. If a repository/archive is available, examine its real code, dependency manifests, lockfiles, file tree, resource imports, asset manifests, and relevant implementation paths. Run safe, relevant tests if the environment permits. Do not make code changes until you have produced an evidence-based audit and clearly identified whether repair work is requested.**
>
> For every checklist item, return: **ID, status (PASS/FAIL/BLOCKED/NOT TESTED/N/A), evidence, exact file path or test/source reference, observed result, and required corrective action**. Identify whether data/assets/repositories were truly imported and used, or merely linked/documented. Verify resource provenance, licence notes, missing files, incorrect parsing, fabricated data, nonfunctional controls, untested paths, and model-routing claims.
>
> Pay special attention to the existing Keys.AI architecture, local-model routing, web research, multi-UI project building, source/asset acquisition, and the actual God's Eye View repository. Verify that no separate globe button was added; that text and existing voice commands can open the real globe; that “open GRO” is handled without false triggers; and that named locations and exact coordinates produce correct real camera navigation. Distinguish automated text tests from an actual voice-path test. Test data layers only when they exist and are configured. Check failure handling and the return path to the ordinary assistant.
>
> Never infer that an import is correct just because files exist: check that expected content is present, important data is complete and valid, assets can be loaded, code is referenced by the app, and runtime behaviour works. Never infer a successful test from generated output alone. Never mark an item PASS without direct evidence. If access to the runtime, browser, network, live microphone, or local model is unavailable, mark the relevant item NOT TESTED or BLOCKED and explain exactly what is needed.
>
> First deliver an overall verdict: `PASS`, `PASS WITH LIMITATIONS`, `FAIL`, or `INSUFFICIENT EVIDENCE`. Then deliver a summary of critical defects, a completed checklist with evidence, a list of incorrect/missing imports, failed tests, unmet requirements, and a prioritised repair plan (P0 critical, P1 high, P2 medium, P3 low). Include commands to reproduce failures and the smallest sensible fixes. Do not claim the application is fully verified if any critical acceptance gate remains untested or failed.

---

# Q. What to bring back for the audit

To let the independent reviewer check the actual implementation, provide as many of the following as your environment permits:

1. This checklist with any statuses or notes already filled in.
2. `KEYS_AI_DEVELOPMENT_AGENT_ROADMAP.md`.
3. The requirements and architecture documents.
4. `docs/GLOBE_INTEGRATION.md`.
5. `research/RESOURCE_INVENTORY.md` and the asset attribution manifest.
6. The project ZIP or relevant source folders, including manifests and lockfiles. Exclude secrets, credentials, private user data, and large generated/cache/build folders when appropriate.
7. Final build/test logs and the exact commands used.
8. Screenshots showing the real application, globe open, and target-location views.
9. Actual text-command test results and separate voice test results.
10. The integrated God's Eye View repository commit/hash and any patch/diff showing how Keys.AI invokes it.
11. Sanitised model-provider/runtime logs proving which model was invoked.
12. Known errors, blockers, and steps needed to reproduce them.

**Do not share API keys, access tokens, passwords, private keys, or other secrets.** Redact them before uploading configuration or logs.
