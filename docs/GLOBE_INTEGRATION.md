# God's Eye View — Keys.AI integration

How the globe is wired into Keys.AI, what it can actually do, and what it cannot.
Everything below reflects code that exists and was exercised; anything untested is
called out as such.

---

## 1. What was integrated

The real **God's Eye View** application (`bilawalsidhu/gods-eye-view`, v0.3.0,
MIT), vendored unmodified at:

```
integrations/gods_eye_view/
```

It runs as its own local Vite service on loopback and is rendered inside
Keys.AI's own Chromium surface (QtWebEngine — the same engine the Research
Browser uses). The agent and the user act on **one** page; there is no second
hidden globe.

**No globe button exists.** `ui.py` has no globe entry in the header, the actions
menu, or the command palette. The workspace is created by
`MainWindow._open_globe_workspace`, which is called only from the `globe` tool.

---

## 2. Why this approach

Three candidate transports were examined in the repository's own source:

| Option | Verdict |
|--------|---------|
| **The app's action runner** — `window.__godsEyeView.voiceCommands.runner(name, args)`, published by `src/app/tools.js` and implemented by `src/voice/gevActions.js` | **Chosen.** It is the app's own voice-control path, already used by the app's own `installViews({run: (name, args) => voiceCommands.runner(name, args)})`. Real implementation, no vendor patching |
| MCP server (`server/mcp/`) | Data reads only; no camera or action control |
| Share-link URL rewriting (`src/share/viewCodec.js`) | Encodes camera state, but applying it reloads the page and resets the scene |

The prompt's rule "do not generate and execute arbitrary JavaScript from an AI
model when a fixed set of validated globe actions can accomplish the task" is
enforced structurally: the action must be in `globe/service.py::ALLOWED_ACTIONS`,
and the arguments are JSON-encoded numbers, booleans and strings.

---

## 3. Runtime shape

```
  voice ─┐
         ├─► Gemini Live tool call ──► TOOL_HANDLERS["globe"] ─► globe/tools.py
  text ──┘                                                          │
                                     deterministic utterance guard │
                                     (globe/intents.try_parse)     │
                                                                   ▼
                                                        globe/service.py
                                        ┌──────────────────────┴───────────────────┐
                                        ▼                                          ▼
                              GlobeServer (Node)                     GlobeService (page)
                       npm run dev --port 4173 --strictPort      QWebEngineView in the
                       readiness: HTTP 200 + app marker           centre view; commands via
                       adopted if already running                 runJavaScript → runner
```

### Files

| File | Responsibility |
|------|----------------|
| `globe/__init__.py` | `get_service()`, version, upstream URL |
| `globe/install.py` | Locate the checkout; validate manifest, `node_modules`, Node range |
| `globe/service.py` | Server lifecycle, readiness, JS bridge, command methods, `execute()` |
| `globe/intents.py` | Utterance → validated `GlobeCommand`; layer vocabulary; coordinate parsing |
| `globe/tools.py` | The agent-facing tool `globe(parameters, ui, speak)` and `handle_utterance` |
| `globe/workspace_ui.py` | `GlobeWorkspace` — status strip + `QWebEngineView` |
| `core/tool_declarations.py` | `globe` tool schema (`action`, `location`, `latitude`, …) |
| `core/tool_registry.py` | `TOOL_HANDLERS["globe"]` |
| `main.py` | Tool dispatch, `_route_globe_utterance`, shutdown flag |
| `ui.py` | `_open_globe_workspace`, `_show_hud_view` return path, shutdown hook |

---

## 4. Command interface

Logical actions (`globe/intents.py`) mapped onto real app actions:

| Logical action | App action sent | Verified |
|----------------|-----------------|----------|
| `OPEN_GLOBE` | — (server + view + readiness) | yes |
| `CLOSE_GLOBE` | — (stop page, return to HUD) | yes |
| `NAVIGATE_TO_LOCATION` | `fly_to_location` with `query`, or `latitude`+`longitude` | yes |
| `SEARCH_GLOBE` | `fly_to_location` with `query` | yes |
| `ZOOM_IN` / `ZOOM_OUT` | `adjust_camera_zoom` `{direction, amount}` | yes |
| `RESET_GLOBE` | `zoom_to_globe` | yes |
| `TOGGLE_DATA_LAYER` | `set_layer_visibility` `{layerId, enabled}` | yes |
| `GET_GLOBE_STATUS` | `get_current_view_state` | yes |

`ALLOWED_ACTIONS` also admits `show_data_layers_menu`, `track_entity` and
`stop_tracking` — real actions of the app, exposed for future use and not yet
driven by a logical command. Anything else is refused **before** it reaches the
page: `Refused unknown globe action: run_arbitrary_js` (verified).

### How a result is obtained

`runJavaScript` cannot await a promise, so the injected script starts the action
and stores the settled outcome in `window.__keysaiGlobeSlots[token]`. The Python
side polls that slot — keyed by a per-call token, so a slow earlier flight can
never be read as the answer to a later one. On timeout the call fails; it never
reports success it did not observe.

---

## 5. Readiness

Two explicit gates, because they fail separately:

1. **Server** — `http://127.0.0.1:<port>/` must answer `200` *and* contain a
   God's Eye View marker. A port that answers with something else is not adopted.
2. **Page** — `loadFinished` must fire (the app serves hundreds of ES modules),
   and only then must `window.__godsEyeView.voiceCommands.runner` exist. The
   runner appears only once the scene, data manager and controls are live.

Treating an HTTP 200 as readiness is exactly the mistake the requirements warn
about; here it is a reachable state that produces a clear failure message rather
than a silent no-op.

---

## 6. Location resolution

* **Explicit coordinates win.** `26.4499, 80.3319` and `geo:39.7392,-104.9903` are
  parsed and handed over as `latitude`/`longitude`. They are never geocoded. A
  pair is only believed when the text contains exactly two in-range numbers, and
  `0,0` is rejected as a parse accident.
* **Names go to the app's own search**, unchanged and complete. The app resolves
  coordinates, `geo:` URIs and its bundled cities with no network, then falls back
  to Google (if configured) → Photon → Nominatim.
* **The app's label is reported back.** "The globe flew to New Delhi, Delhi,
  India." is the app's own resolution, not a Keys.AI guess.
* **Failure is failure.** If the geocoder cannot resolve a name, the result is
  reported as a failure; Keys.AI never substitutes a generic camera position.

**Measured:**

| Request | Camera after | Distance from target |
|---------|--------------|----------------------|
| `Kanpur, Uttar Pradesh, India` | 26.459, 80.321 | ≈ 2 km (city framing) |
| Explicit `48.8584, 2.2945` (Eiffel Tower) | 48.8566, 2.2945 | 0.2 km |
| `New Delhi, India` | resolved; label "New Delhi, Delhi, India" | — |

---

## 7. Configuration

### Nothing to configure for the default path

The app runs keyless: Esri satellite imagery, keyless terrain, flights, military
traffic, satellites, earthquakes, public cameras, radio and launches all work
without credentials. Verified in the console:

```
[Init] Google 3D Tiles unavailable, using the keyless globe:
       Error: Google 3D tokens are not offered
```

### Optional credentials

Add them in the **app's own** panel (`POWER UP → Provider Settings`), which writes
them to the app's own `.env`. Keys.AI never receives or logs them.

| Credential | Unlocks |
|------------|---------|
| Cesium ion token | World terrain, photorealistic 3D (eligible personal/non-commercial) |
| Google Maps API key | Photorealistic 3D tiles via the metered route, Google place search |
| AISStream key | Live vessels |
| FIRMS map key | NASA fire detections |
| TomTom key | Traffic |

Keys.AI does **not** use the app's own OpenAI/Gemini voice. Voice control stays
with Keys.AI's existing pipeline.

### Environment overrides

| Variable | Effect |
|----------|--------|
| `KEYS_GLOBE_DIR` | Use a different God's Eye View checkout |
| `PORT` | Set by Keys.AI per launch; forces the app onto a specific port |

---

## 8. Lifecycle and shutdown

* **One server per process.** A second `ensure()` finds the answering port and
  adopts it — no duplicate Vite process.
* **Ownership is respected.** A server Keys.AI started is killed on exit
  (`taskkill /T /F` on Windows). A server it adopted is **not** — that process
  belongs to someone else.
* **Adoption across sessions.** An orphaned server from a previous run is reused,
  which also survives a crashed Keys.AI without leaving a dead globe.
* **Port conflicts.** `--strictPort` plus a scan of `4173–4199`, so a busy port
  moves the app rather than half-starting it.
* **Exit.** `KeysAIUI` calls `globe.get_service().shutdown()`, which sends the
  page to `about:blank` (letting Chromium tear it down normally) and then stops
  an owned server.
* **`CLOSE_GLOBE` keeps the server running** so reopening is instant (cold start
  measured 6.0 s). The process still ends at application exit.

**Measured** (`GlobeServer` lifecycle probe):

```
cold start : True | pid 8332 | owned True | port 4173
reuse      : True | adopted True
adopted stop harmless : True
owner stop kills it   : True
restart after stop    : True | port 4173 | owned True
stopped again         : True
```

---

## 9. Known limitation: WebGL

Cesium needs WebGL, and its camera animations advance on `requestAnimationFrame`.
Chromium drives that only for a page that is actually being painted. Consequences:

* In a **normal desktop session** this is a non-issue.
* If the machine has no usable GPU path, Chromium reports no WebGL and the globe
  cannot render. Keys.AI detects this and says so instead of showing a blank page:

  > Start Keys.AI with
  > `QTWEBENGINE_CHROMIUM_FLAGS="--enable-unsafe-swiftshader"`
  > to fall back to software rendering.

* **A headless/offscreen session cannot fly the camera**, because nothing is
  painted. This is a property of the harness, not of the integration: the live
  probe opens a real window for exactly this reason.

---

## 10. Testing

| Suite | What it proves | How to run |
|-------|----------------|------------|
| `qa_artifacts/regression_tests/test_globe_integration.py` (21 tests) | Intent routing, coordinate rules, layer vocabulary against the app's real manifest, Node range, JS escaping, honest reporting | `python -m unittest qa_artifacts.regression_tests.test_globe_integration` |
| `qa_artifacts/regression_tests/globe_live_probe.py` (17 checks) | Server start/reuse, page readiness, camera actually moves, zoom, reset, coordinates, layers, refusal, and the real tool path | `python qa_artifacts/regression_tests/globe_live_probe.py` |
| `qa_artifacts/regression_tests/globe_page_diagnose.py` | Page console, WebGL, loader state — used when readiness fails | `python qa_artifacts/regression_tests/globe_page_diagnose.py [seconds]` |

Last recorded live run:

```
[PASS] local server serves the app — http://127.0.0.1:4173/
[PASS] QtWebEngine view is available
[PASS] globe page publishes its command runner
[PASS] reopening reuses the live page
[PASS] navigate to Kanpur accepted
[PASS] camera is actually near Kanpur — 2 km from 26.4499, 80.3319 (camera at 26.459, 80.321)
[PASS] zoom in reduced the camera range — 205 m -> 78 m
[PASS] reset returns to a full-Earth view — range 18000000 m
[PASS] explicit coordinates are honoured — 0.2 km from the Eiffel Tower
[PASS] layer toggle answers — ok=True
[PASS] unknown actions are refused — Refused unknown globe action: run_arbitrary_js
[PASS] tool path navigates and reports it — The globe flew to New Delhi, Delhi, India.
[PASS] tool path zooms out — Zoomed out on the globe.
[PASS] tool path reports status — The globe server is running on port 4173.
[PASS] the utterance guard reaches the globe — The globe is open at http://127.0.0.1:4173/.
[PASS] ordinary speech is left to the assistant — None
[PASS] tool path closes the globe — Closed the globe.
```

**Not covered:** physical microphone capture, and the pre-existing Keys.AI test
suite. Neither is claimed as passing.

---

## 11. Voice integration

No second microphone and no globe-specific voice service was added.

```
Microphone → existing Keys.AI speech recognition → existing intent/tool routing
           → `globe` tool → real globe action → real result
```

Two routes reach the tool:

1. **Model tool call** — the `globe` tool is declared with the full command
   vocabulary, so Gemini Live calls it from speech.
2. **Deterministic guard** — `main.py::_route_globe_utterance` runs
   `globe/intents.try_parse` on the completed user turn. If the utterance is an
   explicit globe request and the model did *not* call the tool this turn, the
   request still happens. A per-turn flag (`_globe_tool_called`) prevents the same
   command running twice.

The parser is deliberately conservative: research and comparison wording
("Research the best 3D globe libraries") never opens the globe, and "open GRO" is
accepted as an unambiguous speech-recognition alias while "grow" and "go" are not.

---

## 12. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "The God's Eye View checkout is missing" | `integrations/gods_eye_view` absent | Clone the repo there (or set `KEYS_GLOBE_DIR`) and run `npm ci` |
| "Node X is outside the supported range" | Node 25 or 27, or older than 24.14 | Install Node 24.14+ or 26.x. Keys.AI will not change your Node for you |
| "Dependencies are not installed" | `node_modules/vite` missing | `npm ci` inside the checkout |
| "did not finish loading in time" | Server unhealthy or port conflict | Check `.gev-logs/keysai-globe.log` |
| "never published its command runner", WebGL hint shown | No GPU/WebGL in this Chromium | Restart with `QTWEBENGINE_CHROMIUM_FLAGS="--enable-unsafe-swiftshader"` |
| "cancelled the move — another camera flight is already running" | Command sent during the app's startup restoration | Retried once automatically; ask again if it persists |
| Blank globe on a slow machine | First Vite start compiles on demand | Cold start measured 6.0 s; the workspace shows *loading …* until ready |
| Choppy globe | Software rendering, or the embedded view | Try the same URL in a hardware-accelerated browser to distinguish (the upstream project documents this) |

Logs: `.gev-logs/keysai-globe.log`. Last status: `config/globe_server.json`.
