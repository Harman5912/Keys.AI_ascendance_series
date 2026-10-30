# AUDIT.md — Keys.AI & Crown Code Architectural Audit

Date: 2026-10-29
Branch: `crown-code-v2`
Author: Harman Sadhwani / Antigravity Lead Engineer

---

## 1. System Overview & Entry Points

Keys.AI is an autonomous desktop-control agent and coding environment for Windows, written in Python with a Tkinter user interface and integrating the Node.js Crown Code coding agent.

### Primary Entry Points
- `main.py`: Application lifecycle orchestrator, background process manager, wake-word/hotkey hooks, and model preloading.
- `ui.py`: Main Tkinter graphical user interface, HUD, mini-overlay, model selection dropdown, activity logs, and chat controls.
- `actions/crown_code.py`: Crown Code Terminal Agent invocation entry point (`crown_code()`) managing build jobs, clarifications, and status checks.
- `core/crown_bridge.py`: Bridge initiating headless Node.js processes for Crown Code terminal agent tasks.
- `c:\Users\harma\Desktop\PROJECTS\Crown CODE\dist-headless\headless.js`: Node.js headless worker executing agent tasks.

---

## 2. Call Graph Architecture (UI -> Crown Code -> Local LLM)

```text
+--------------------------------------------------------------+
|                    Keys.AI UI (Tkinter)                      |
|                  ui.py / mini_overlay.py                     |
+--------------------------------------------------------------+
                               |
                               | Calls crown_code tool / job queries
                               v
+--------------------------------------------------------------+
|                   actions/crown_code.py                      |
|            - analyse_brief / brief_spec                      |
|            - crown_jobs (Background Job Manager)            |
|            - ResearchHarvester / BlueprintEngine             |
+--------------------------------------------------------------+
                               |
                               | Spawns headless subagent runner
                               v
+--------------------------------------------------------------+
|                    core/crown_bridge.py                      |
|           Runs: node dist-headless/headless.js               |
+--------------------------------------------------------------+
                               |
                               | HTTP JSON-RPC / REST
                               v
+--------------------------------------------------------------+
|               Local Model Server (Ollama)                    |
|          qwen3:8b / qwen3-coder:30b / qwen2.5-coder          |
+--------------------------------------------------------------+
```

---

## 3. The UI Contract (Callbacks, State & Events Consumed by UI)

The Keys.AI UI is **frozen** and interacts strictly with Crown Code through these entry points:

| Consumer Location | Crown Code Module / Function | Purpose / Signature | Frequency & Threading |
|---|---|---|---|
| `ui.py:2740` | `core.crown_bridge.load_config()` | Reads current Crown Code model and policy configuration | On settings tab open; UI main thread |
| `ui.py:2750` | `core.crown_bridge.list_models()` | Retrieves local Ollama models for dropdown population | On model picker click; background worker |
| `ui.py:2775` | `core.crown_bridge.save_config(cfg)` | Persists selected model & active options | On user selection change; UI main thread |
| `ui.py:3515` | `core.crown_bridge.pick_model(name)` | Sets default model in Crown config | On settings save; UI main thread |
| `main.py:1550` | `core.crown_bridge.sync_local_models()` | Syncs available models between Ollama and config | On application launch; background thread |
| `actions/crown_code.py:836` | `crown_code(parameters)` | Main execution entry for coding jobs, clarifications, job status | Triggered by user prompt; worker thread |
| `actions/crown_code.py:64` | `crown_jobs.get_build_history()` | Displays active and past builds | Status / check calls |

---

## 4. Test Suite Audit & Baseline Findings
- Existing test file `test_crown_code.py` passes end-to-end against local `qwen3:8b` via Ollama (`PASS B`, `PASS C`, `PASS D`, `PASS E`).
- Regression tests in `qa_artifacts/regression_tests` reference `PyQt6.QtWebEngineWidgets` which is not installed in the active Python 3.12 venv, isolating them from the main Tkinter application flow.
- A baseline of 15 golden traces has been recorded under `tests/golden_traces/` capturing all discrete response shapes of `crown_code()`.
- 15 baseline deterministic UI screens were captured at 100%, 125%, and 150% scaling under `tests/ui_regression/baseline/` with SHA-256 manifests.
