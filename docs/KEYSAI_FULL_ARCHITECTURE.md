# KEYS.AI — COMPLETE ARCHITECTURE, WORKFLOW & SYSTEM DOCUMENTATION

> ACENDENCE VII [GEN I] — A premium AI desktop assistant combining live voice, screen vision, computer control, autonomous coding, document creation, messaging, web research, memory and personalization.

---

## 1. SYSTEM OVERVIEW

Keys.ai is a PyQt6 desktop application (main.py + ui.py) that hosts an async Gemini Live voice session, a tool dispatch registry, a Crown Code autonomous coding engine, a Universal Project Agent, a Research Browser (Chromium), an Image Studio (ComfyUI), a 3D Globe (Node service), a God's-Eye camera, system monitoring, long-term memory, and plugin modules.

Entry point: `main.py` -> `KeysAILive` (engine) + `ui.py` -> `KeysAIUI` (Qt window). Background services started at launch: voice pipeline, wake-word listener, echo guard, session logger, plugin loader, monitor threads.

---

## 2. DIRECTORY STRUCTURE (TOP LEVEL)

- `main.py` (1515 lines) — KeysAILive engine: audio I/O queues, Gemini Live session, tool dispatch, session resumption, echo guard, wake word, background monitoring.
- `ui.py` (6023 lines) — KeysAIUI Qt main window: chat, controls, preview, terminal, browser, image studio, settings.
- `actions/` — 39 action modules (file, email, messages, computer control, weather, youtube, crown_code, feature_demo, etc.).
- `core/` — 50+ core modules: tool_registry, tool_declarations, tool_exec, tool_rescue, llm_client, config_store, memory, echo, audio_devices, avatar, camera_preview, app_builder, app_checks, app_specs, blueprint_engine, build_recipes, design_system, doc_builder, office_builder, office_xlsx, powerbi_prompt, gemini_ladder, model_catalog, model_probe, persona, plugin_loader, repo_index, research_*, security, crown_bridge, crown_jobs, agent_coordinator, agent_permissions, confirm, confirm_ui, firebase_client, health_check, ast_verifier, repair_loop, features_knowledge, image_studio/, research_browser/, site_studio/.
- `crown_code/` — autonomous coding engine (engine/legacy_engine.py, v2_engine.py, interface.py, ui_adapter.py, checkpoints.py, events.py, loop_detector.py).
- `universal_agent/` — Project Agent: intake.py, models.py, planner.py, security.py, validation.py, workers/, service.py.
- `agent_control/` — computer control subsystem (app_control, action_log, ...).
- `agent_permissions.py`, `agent_coordinator.py` — permission gates.
- `automation/`, `brain/`, `plugins/`, `skills/`, `language/`, `personality/`, `memory/`, `sessions/`, `config/`, `data/`, `templates/`, `examples/`, `tests/`, `qa_artifacts/`, `docs/`, `builds/`, `dist/`, `desktop/`, `dashboard/`, `portfolio/`, `crown_sites/`, `crown_sites_multi/`, `keys-website/`, `globe/`, `integrations/`, `research/`, `scripts/`, `whatsapp/`, `workspace/`, `audit_output/`, `keys_Creations/`.

---

## 3. BOOT SEQUENCE

1. `python main.py` -> loads config, secrets, persona, memory.
2. Qt application created; `KeysAIUI` constructed.
3. Engine `KeysAILive` started on async loop.
4. Gemini Live session opened (model from config, default gemini-2.5-flash-native-audio).
5. Tool declarations registered from `core/tool_declarations.py`.
6. Tool handlers lazily bound via `core/tool_registry.py`.
7. Plugins loaded from `plugins/`.
8. Background monitors started (CPU/RAM/process).
9. Wake-word detector armed (optional).
10. UI shows HUD; ready for voice/text input.

---

## 4. VOICE & AUDIO PIPELINE

- Input: PyAudio capture -> async queue -> Gemini Live (audio in).
- Output: Gemini Live (audio out) -> async queue -> PyAudio playback.
- Echo guard (`core/echo.py`): prevents AI hearing itself (mic mute during TTS).
- Wake word detection: listens for "Hey Keys" / configured phrase.
- Session resumption: resumption handles stored; reconnect on drop.
- Session logger: summarizes conversation at end.

---

## 5. TOOL DISPATCH SYSTEM

- `core/tool_registry.py` maps 40+ tool names -> handler functions.
- `core/tool_declarations.py` holds Gemini function schemas (single source of truth).
- Inline tools handled directly by main.py (need session/UI state): save_memory, screen_process, close_camera, web_search, system_status, shutdown_keysai, recall_memory, undo, manage_monitor.
- Regular tools loaded lazily from actions/ or core/.
- `core/tool_exec.py` executes tool calls with retry/rescue (`tool_rescue.py`).
- Agent control: permission gates via `agent_permissions.py`; action log `agent_control/action_log.py`.

Tool categories: web search, browser control, screen process, computer control, file operations, document creation (Word/Excel/PPT), messaging, email, WhatsApp, system monitor, weather, youtube, flight finder, game updater, open app, settings, crown code, feature demo, research browser, globe, image studio, memory, undo, monitor, repo inspect, skills.

---

## 6. SCREEN & VISION

- `actions/screen_processor.py` + `core/camera_preview.py`: capture screen, OCR (Tesseract), vision analysis via Gemini.
- `screen_process` inline tool: analyze current screen.
- Screenshots saved to workspace; used by Crown Code design references.

---

## 7. COMPUTER CONTROL

- `actions/computer_control.py`, `hybrid_control.py`, `computer_use.py`, `editor_control.py`, `browser_control.py`.
- `agent_control/app_control.py`: init control system with bridge + player; ESC emergency stop.
- UI automation via pywinauto / Playwright; keyboard/mouse via pyautogui (where available).
- Window management, app launching (`open_app.py`).

---

## 8. CROWN CODE — AUTONOMOUS CODING AGENT

- `crown_code/engine/`:
  - `interface.py`: engine interface.
  - `legacy_engine.py`: original engine.
  - `v2_engine.py`: new engine (default; `CROWN_ENGINE=legacy` runs legacy).
  - `ui_adapter.py`: emits events UI consumes (chat, diff, approval, progress).
  - `checkpoints.py`: shadow git checkpoints.
  - `events.py`: event definitions.
  - `loop_detector.py`: detects repeated errors / oscillating diffs.
- Adapter ensures UI sees identical events regardless of engine.
- Crown Bridge (`core/crown_bridge.py`, `crown_jobs.py`): job queue, status.
- Used by feature_demo, app_builder, document builders.

---

## 9. UNIVERSAL PROJECT AGENT

- `universal_agent/`: intake (classify, questions, defaults), models (state machine, persistence), planner (deterministic + model refine), security (paths, redaction, audit), validation (artifact checks), workers (research, software, documents, data, images, browser), service (orchestration).
- States: DISCOVERED -> CLARIFICATION -> CONFIRMED -> PLANNED -> IMPLEMENTED -> TESTED; plus BLOCKED/REJECTED, WAITING_FOR_USER, WAITING_FOR_APPROVAL, RUNNING, VALIDATING, REPAIRING, COMPLETED, FAILED, CANCELLED.
- Task persistence under tasks/ dir; audit log audit.jsonl.
- Approval flow for destructive steps.
- Repair loop: MAX_REPAIRS=1.

---

## 10. MEMORY & PERSONALIZATION

- Long-term memory: JSON files under `memory/` + `core` memory functions.
- `recall_memory`, `save_memory` inline tools.
- Session memory: conversation summary for context.
- `config_store.py`: encrypted secrets (api_keys.json, secrets.enc).
- Persona system: `personality/`, `persona.py`.

---

## 11. PLUGINS

- `core/plugin_loader.py` loads `plugins/*.py`.
- Plugins register tools dynamically.
- Plugin registry initialized at startup.

---

## 12. RESEARCH BROWSER

- `core/research_browser/`: BrowserService (QtWebEngine Chromium), urls.py, paths.py, tools.py, collector.py, integration.py, library.py, assets.py, workspace_ui.py.
- Tabs, navigation, search (default Google now), screenshots, source/asset collection, add to project.
- Shared page between agent and user (no hidden browser).
- Used as preview surface for built sites (`_on_cr_preview`).

---

## 13. IMAGE STUDIO

- `core/image_studio/`: local ComfyUI-based generation.
- Studio UI panel; generation jobs; model management.

---

## 14. GLOBE (GOD'S EYE VIEW)

- `globe/`: Node service (local) hosting photorealistic 3D globe.
- Tools: open/close/navigate/search/zoom/reset/layer/status.
- `core` globe service manager.

---

## 15. DOCUMENT / OFFICE BUILDERS

- `core/doc_builder.py`, `office_builder.py`, `office_xlsx.py`: Word, Excel, PowerPoint generation.
- `actions/file_processor.py`, `file_controller.py`: file ops.
- Templates in `templates/`.

---

## 16. APP BUILDER / SITE STUDIO

- `core/app_builder.py`, `app_specs.py`, `app_checks.py`, `blueprint_engine.py`, `build_recipes.py`, `design_system.py`, `design_check.py`, `design_research.py`, `brief_spec.py`, `ast_verifier.py`, `repair_loop.py`.
- `core/site_studio/`: web app builder.
- `core/research_harvester.py`, `research_step.py`: research for builds.

---

## 17. MESSAGING & COMMUNICATION

- `actions/send_message.py`, `send_email.py`, `make_call.py`, `whatsapp_control.py`, `whatsapp_takeover.py`, `google_account.py`.
- WhatsApp, Gmail, SMS integration.

---

## 18. SYSTEM MONITORING & MONITORS

- `actions/system_monitor.py`, `background_monitor.py`, `proactive.py`, `suggest_inbox_tasks.py`, `reminder.py`.
- Background topics checked daily; alerts.

---

## 19. CONFIGURATION

- `config/`: settings JSON, api_keys, secrets.enc.
- `core/config_store.py`: load/update.
- `core/api_config.py`, `model_catalog.py`, `gemini_ladder.py`: model selection.
- Environment: `PYTHONUTF8=1`, venv `.venv`.

---

## 20. TESTING

- `tests/`, `qa_artifacts/regression_tests/`: universal_agent tests, crown engine tests, ui tests.
- Run: `python -m pytest qa_artifacts/regression_tests/...`.

---

## 21. DATA FLOW (HIGH LEVEL)

User (voice/text) -> Gemini Live -> tool call -> tool_registry -> handler (actions/core) -> result -> Gemini -> voice/text response + UI updates.

Crown Code path: user request -> crown_code engine -> plan -> execute steps (research, build, verify) -> UI adapter events -> chat/diff/approval/progress.

Universal Agent path: create task -> intake questions -> plan -> run steps (workers) -> validate artifacts -> repair if needed -> complete.

Research Browser path: open tab -> navigate (Google default) -> collect sources/assets -> add to project.

---

## 22. SECURITY

- Least-privilege DB accounts, parameterized queries (where DB used).
- Secrets redacted in logs/events (`security.redact_secrets`).
- Path traversal protection (`security.resolve_within`).
- Audit log for approvals/cancellations/completions.
- Permission gates for destructive/external actions.
- Echo guard prevents self-listening.

---

## 23. KEY ENTRY POINTS FOR AI

- Start app: `python main.py`.
- Run tests: `python -m pytest qa_artifacts/regression_tests/test_universal_agent_core.py -v`.
- Config: `config/` + `core/config_store.py`.
- Tool list: `core/tool_declarations.py`.
- Add tool: declare in tool_declarations.py + register in tool_registry.py + implement in actions/ or core/.
- Research browser default search: `core/research_browser/paths.py` (google).
- Crown engine selection: `CROWN_ENGINE` env var.

---

## 24. END-TO-END REQUEST LIFECYCLE (EXAMPLE: "Build a portfolio website")

1. User speaks/types request.
2. Gemini Live receives, decides to call tool (e.g., crown_code or feature_demo or universal agent).
3. Tool handler invoked via registry.
4. If Crown Code: engine plans (research -> build -> verify), runs steps, emits UI events (chat, diff, approval, progress).
5. Research step opens Research Browser, navigates (Google), collects sources/assets.
6. Build step generates site into workspace (crown_sites/...).
7. Preview step opens site in Research Browser (`_on_cr_preview`).
8. Verification: tests/checks run; artifacts validated.
9. Result reported to user via chat + UI.

---

## 25. MODULE DEPENDENCY GRAPH (SIMPLIFIED)

main.py -> ui.py, tool_registry, tool_declarations, echo, audio, memory, plugins, crown_bridge, universal_agent (lazy).
ui.py -> research_browser, image_studio, crown_code ui_adapter, agent_control.
tool_registry -> actions/*, core/* (lazy imports).
universal_agent -> intake, models, planner, security, validation, workers, service.
crown_code -> engine (legacy/v2), ui_adapter, checkpoints, loop_detector.
research_browser -> service, urls, paths, tools, collector, integration, library, assets, workspace_ui.

---

## 26. FILES & ARTIFACTS PRODUCED

- Workspaces: `keys_Creations/`, `workspace/`, `crown_sites/`, `crown_sites_multi/`, `portfolio/`.
- Documents: Word/Excel/PPT under creation workspaces.
- Logs: `sessions/`, audit logs.
- Memory: `memory/`.
- Config: `config/`.

---

## 27. OPERATIONAL COMMANDS

- Run app: `python main.py`
- Run universal agent tests: `python -m pytest qa_artifacts/regression_tests/test_universal_agent_core.py -v`
- Run crown engine tests: `python -m pytest qa_artifacts/regression_tests/test_crown_engine_v2.py -v`
- Run workers tests: `python -m pytest qa_artifacts/regression_tests/test_universal_agent_workers.py -v`
- Run ui tests: `python -m pytest qa_artifacts/regression_tests/test_universal_agent_ui.py -v`

---

## 28. KNOWN LIMITATIONS / NOTES

- UI frozen rule: do not change layout/colors/fonts/assets/copy of existing screens (AGENTS.md R1).
- Legacy engine must remain runnable (`CROWN_ENGINE=legacy`).
- Research browser default search now Google (changed).
- Preview of built sites uses Research Browser (shared Chromium), not a separate web view.

---

END OF DOCUMENT
