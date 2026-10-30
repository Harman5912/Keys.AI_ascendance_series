# Keys.AI development agent — architecture

What the agent actually is, as inspected in this repository. Section 6 lists what
this task changed and, equally important, what it deliberately did not.

---

## 1. Entry points

| Layer | File | Role |
|-------|------|------|
| Process entry | `main.py` (1450 lines) | Gemini Live session, voice I/O, tool dispatch, phone WebSocket bridge (port 8000) |
| UI | `ui.py` (6723 lines) | PyQt6 HUD; `KeysAIUI` is the thread-safe wrapper the engine talks to |
| Push-to-talk overlay | `mini_overlay.py` | Same engine, F5 |
| CLI coding run | `python -m core.engine.cli "<description>" --yes` | Engine-only path |

`main.py` forces `CREATE_NO_WINDOW` on every subprocess and reconfigures
stdout/stderr to UTF-8. Both are load-bearing and were left alone.

---

## 2. Tool routing

```
Gemini Live session
  └─ tool_call ──► main.py::_execute_tool
                     ├─ inline tools needing session state
                     │   (save_memory, screen_process, web_search, system_status,
                     │    shutdown_keysai, recall_memory, undo, manage_monitor, globe)
                     └─ TOOL_HANDLERS[name](parameters, ui, speak)   ← lazy import
                          └─ on failure: PluginDispatch.try_plugin(...)
```

* `core/tool_declarations.py` — the schema list shown to the model (39 tools).
* `core/tool_registry.py` — `TOOL_HANDLERS`, each entry a zero-cost lazy loader, so
  importing the registry loads no heavy dependency.
* Handlers run through `run_in_executor`, i.e. **off the GUI thread**. Anything
  touching Qt must hop back via `MainWindow.run_on_gui_thread`.

---

## 3. The coding agent

`actions/crown_code.py` is the single coding agent. `dev_agent` is a retired alias
that routes here, so the old builder cannot run alongside the new one.

| Concern | Implementation |
|---------|----------------|
| Requirement gathering | Returns `NEED REQUIREMENTS` + questions and builds nothing until answered; `clarify` action lists missing slots; `confirmed=true` records assumptions |
| Planning | Job phases streamed as `DevEvent`s to the Live Coding console (PLANNING, RESEARCH, CODING, TERMINAL, TEST, DEBUG, BUILD, DONE, ERROR) |
| Execution | Real shell in an embedded terminal, reading real stdout and exit codes |
| Repair | Reads failures and iterates; destructive commands (`rm -rf`, `git reset --hard`) require the user while safe/install commands auto-approve |
| Verification | `_verify_project_tests(workspace)` plus project-type-specific launch checks |
| Backgrounding | Returns a job id immediately; `action=status` reports phase/percent/ETA |
| Classification | `classify_task`, `infer_kind` choose site / app / bridge paths |

Supporting modules: `core/engine/` (orchestrator, events, terminal, cli),
`core/app_specs.py`, `core/build_recipes.py`, `core/app_builder.py`,
`core/app_checks.py`, `core/repo_index.py`, `actions/repo_tool.py`.

---

## 4. Research, browsing and assets

`core/research_browser/` is a real Chromium workspace (QtWebEngine) that the user
and the agent share — the agent's actions run JavaScript on the page that is on
screen, so what the agent sees and what the user sees cannot drift apart.

| Module | Role |
|--------|------|
| `service.py` | Tabs, navigation, `wait_for_load`, `run_js`, `page_text`, `click_element`, `fill_input`, screenshots, downloads |
| `tools.py` | Agent-facing actions; every one marshals onto the Qt thread |
| `library.py`, `collector.py` | Source and asset records with URL, licence status, attribution |
| `workspace_ui.py` | `BrowserWorkspace` — the visible surface |
| `paths.py`, `urls.py` | Workspace layout and URL handling |

`core/research_step.py` is the build-time research stage. It opens pages for the
research question, reads their text, captures real screenshots and page images
into the task workspace, and writes a cited report. Assets keep a
`license_status` that defaults to `unknown` unless the caller supplies a
verifiable one — the agent cannot accidentally mark an uncleared image as safe.

---

## 5. Model routing

`core/model_catalog.py` is the single provider registry — `gemini`, `nvidia`,
`anthropic`, `openrouter`, `openai`, `ollama` — each with its model list, base
URL, docs URL and key field. `ollama` points at `http://localhost:11434`.

`core/llm_client.py` is the single text entry point:

```python
from core.llm_client import get_llm, complete
complete("code_helper", prompt, system=...)
```

It honours the per-task provider/model from `config/api_keys.json`, caches one
client per task, and raises on failure so a caller falls back to its own offline
path instead of receiving a plausible empty string.

`brain/providers/` supplies the provider objects; `brain/` also holds
intent/planning/reasoning/memory. `core/gemini_ladder.py` handles model fallback.

---

## 6. What this task added

Four new files and four small edits. Nothing existing was replaced.

### New

| File | Purpose |
|------|---------|
| `globe/__init__.py` | Package entry (`get_service()`) |
| `globe/install.py` | Checkout + Node-range validation |
| `globe/service.py` | Server lifecycle, readiness, JS bridge, command methods |
| `globe/intents.py` | Utterance → validated globe command |
| `globe/tools.py` | The `globe` tool and the utterance guard |
| `globe/workspace_ui.py` | `GlobeWorkspace` centre view |
| `integrations/gods_eye_view/` | The vendored app (unmodified source) |

### Edits

| File | Change | Size |
|------|--------|------|
| `core/tool_declarations.py` | Append the `globe` tool schema | +46 lines |
| `core/tool_registry.py` | Add the `globe` handler | +6 lines |
| `main.py` | `_globe_tool_called` flag, `globe` branch in `_execute_tool`, `_route_globe_utterance`, one call at `turn_complete` | ~+45 lines |
| `ui.py` | `_open_globe_workspace`, `_open_globe`, `_globe_ws` in the shutdown sweep, globe service shutdown | ~+55 lines |

### Deliberately not done

| Not done | Why |
|----------|-----|
| A second coding agent | `crown_code` is the agent; `dev_agent` already routes to it |
| A new browser | `core/research_browser` is a real, visible, agent-driven Chromium |
| A new model router or provider | `core/llm_client.py` + `core/model_catalog.py` own that |
| New Python dependencies | `PyQt6.QtWebEngineWidgets` is already required by the Research Browser |
| Changes to `requirements.txt` | The globe's packages are Node-side and isolated inside its own folder |
| A globe button or menu entry | Explicitly forbidden by the requirement |
| Patching the vendored app's source | Its own `voiceCommands.runner` surface is sufficient |

---

## 7. Threading contract

Two rules, both load-bearing:

1. **QtWebEngine is GUI-thread-only.** A page or profile touched from a worker
   thread aborts the process with no Python traceback. Every globe page operation
   is marshalled through `MainWindow.run_on_gui_thread`, exactly as
   `core/research_browser/tools.py` does.
2. **A wait on the GUI thread must pump the event loop.** Chromium's page work is
   driven by that loop. `time.sleep()` in a wait loop starves it and a loading
   page can stall indefinitely. `GlobeService._pump` runs a real `QEventLoop`;
   `GlobeWorkspace.wait_for_load` blocks on the page's own `loadFinished` signal
   rather than polling.

Finding (2) took three failed probe runs to isolate and is the reason readiness is
split into "document loaded" and "app published its runner".

---

## 8. Intent routing for the globe

Two independent routes, so an explicit request works even if the model answers in
words:

1. The `globe` tool, declared to Gemini Live — the normal voice and text path.
2. `globe/intents.try_parse` on the completed user turn — a deterministic guard.
   It returns `None` for anything that is not an explicit globe request, so
   ordinary conversation is untouched.

Vocabulary is validated against the app's own manifest: every layer alias in
`globe/intents.py::LAYER_ALIASES` maps to one of the 30 ids in
`src/voice/layerManifest.js`, and a regression test asserts it by reading that
file. Research and comparison wording is vetoed, so "Research the best 3D globe
libraries" goes to web research rather than opening the globe.

---

## 9. Verification discipline

The pieces that make a claim checkable:

* `ALLOWED_ACTIONS` — an unknown action is refused before reaching the page, and a
  live check asserts it.
* Two-phase readiness — a page that has answered HTTP 200 can still do nothing.
* Result envelopes preserve `globe_action` (what the app ran) alongside the
  logical `action`, so a report loses neither.
* `_describe_result` reports failure with the app's own error text and the install
  hint; there is no path that says "done" without a successful result.
* A `cancelled` flight is retried once and then reported as a failure — never
  silently treated as arrival.
