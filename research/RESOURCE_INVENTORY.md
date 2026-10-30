# Resource Inventory

Sources actually opened and inspected for this work. Each entry records what was
read, not merely linked. Where a claim could not be verified it says so.

Recorded: 2026-10-28.

---

## 1. Primary integration target

### God's Eye View — `bilawalsidhu/gods-eye-view`

| Field | Value |
|-------|-------|
| Canonical URL | https://github.com/bilawalsidhu/gods-eye-view |
| Version | **0.3.0** (`package.json` `"version": "0.3.0"`) |
| Licence (code) | **MIT**, `Copyright (c) 2026 Bilawal Sidhu` — verified in `LICENSE` |
| Licence (data/assets) | **Not MIT.** Each source keeps its own terms — see §2 |
| Node engine | `">=24.14.0 <25 \|\| >=26 <27"` — read from `package.json` |
| Host Node | **v26.5.0** → inside range (`globe/install.py::node_in_range`) |
| Dev server | `npm run dev` → Vite, default port `4173` (`build/vite.js:147`) |
| Dependencies | `cesium@^1.124.0`, `satellite.js`, `pbf`, `mapbox/vector-tile`, `hls.js`, `mapillary-js`, `mgrs`, `egm96-universal`, `@jtarrio/signals`, `@jtarrio/webrtlsdr`, `@meri-imperiumi/eccodes-wasm`; dev: `vite@^6`, `puppeteer`, `sharp`, `ws` |
| Installed | `npm ci` completed. Lockfile v3. Resolved: **cesium 1.138.0**, **vite 6.4.3**, **satellite.js 6.0.2**. Postinstall scripts were blocked by npm's allow-scripts policy, so Puppeteer's bundled Chromium is absent — not needed (Keys.AI supplies the browser) |
| Local copy | `integrations/gods_eye_view/` — source unmodified, **2206 files / 516 MB** excluding `node_modules` and `.gev-cache` |
| Commit | **Not recorded.** The clone's `.git` was removed when vendoring, so the copy cannot be tied to a hash. Identified instead by version + checksums below. Re-cloning upstream today would not prove what was vendored, so no hash is claimed |
| Checksums (SHA-256) | `package.json` `217282311f1b62e401b725c607eb027460308d70015893f233531356a6d22029`; `package-lock.json` `f94b3765f8490b93a1a7c02cb953710b085f8afa9869c90b931d0e753901bbf1`; `LICENSE` `b231bb38e2d4eab741643126087cbe9df2b58e2f2e5abf27ad613d05f52b01ca` |
| Intended use | Runnable local service; the globe Keys.AI hosts and drives |

**Files read directly from the checkout:**

| File | Why it was read |
|------|-----------------|
| `README.md` | Setup paths, first-run behaviour, keyless capabilities, keyboard shortcuts, voice options |
| `package.json` | Version, licence, engine range, dev server, dependency list, exported subpaths |
| `LICENSE` | MIT grant + copyright line |
| `DATA_SOURCES.md` | Per-source licence and attribution obligations |
| `src/app/tools.js` | **The integration contract**: `window.__godsEyeView` and `voiceCommands.runner` |
| `src/app/application.js` | Startup/cleanup phases, `getComponents()` |
| `src/app/startupChrome.js` | Loading-screen and first-run reveal logic |
| `src/voice/gevActions.js` | The real action runner; `fly_to_location`, `get_current_view_state` |
| `src/voice/actionSchemas.js` | Exact action names and argument schemas |
| `src/voice/layerManifest.js` | The 30 real layer ids used by the adapter |
| `src/agent/worldPacket.js` | Camera payload shape `{latitude, longitude, heightM}` |
| `src/locations.js` | `searchAndFlyTo` (keyless coordinates, `geo:` URI, bundled cities, then Google → Photon → Nominatim) |
| `src/share/viewCodec.js` | Share-link state encoding (evaluated as an alternative transport) |
| `src/app/globePanelRuntime.js` | MCP/panel embed mode (evaluated and rejected — see `docs/GLOBE_INTEGRATION.md` §2) |
| `server/mcp/stdio.js`, `server/mcp/server.js` | MCP surface — **data reads only**, no camera control |
| `server/standalone/vite.config.js`, `build/vite.js` | Port handling (`PORT` env, default 4173) |
| `scripts/setup-doctor.mjs` | The credential list the app recognises |

**Not done:** `npm run doctor` and `npm test` were **not** run inside the vendored
copy. `npm ci` reported success and the app boots and serves, which is the
evidence relied on. The repository's own test suite has not been executed here.

---

## 2. Data-source licences carried by the globe

Summarised from `DATA_SOURCES.md`; the vendor file remains authoritative. Keys.AI
does not strip or alter the app's in-app attribution line.

| Source | Used for | Terms | Key needed |
|--------|----------|-------|------------|
| Esri World Imagery | Default keyless satellite basemap | Esri Master Agreement; attribution required | No |
| OpenStreetMap / Nominatim | Map + place data, geocoding | ODbL 1.0, © OpenStreetMap contributors | No |
| Photon (komoot) | Fallback geocoder | see provider terms | No |
| **TeleGeography submarine cables** | Cable layer | **CC BY-NC-SA — NonCommercial** | No |
| OpenSky Network | Live flights | Non-commercial research/education | No |
| adsb.lol | Flights, military, traces | ODbL 1.0 | No |
| AISStream.io | Vessels | Free/beta, no formal ToS | Optional |
| CelesTrak | Satellite TLEs | US-gov-origin, citation requested | No |
| USGS | Earthquakes | U.S. public domain | No |
| NASA GIBS / CMR | Recent imagery | U.S. public domain | No |
| NOAA GFS / nowCOAST / NHC | Weather, radar, lightning, cyclones | U.S. public domain | No |
| ECMWF Open Data | Wind model | CC BY 4.0 + ECMWF terms | No |
| NIFC WFIGS | Fire perimeters | U.S. public domain | No |
| Mapillary / KartaView / Panoramax | Street level | CC BY-SA 4.0 (per picture) | No |
| The Space Devs Launch Library 2 | Launches | Terms allow reuse with added value; 15 calls/h unauthenticated | Optional |
| Google Map Tiles + Places | Photorealistic 3D, Google place search | Proprietary, billed | **Yes** |
| Cesium ion | World terrain, photorealistic 3D | Free tier for eligible non-commercial use | **Yes** |
| OpenAI / Gemini | GEV's own voice agent | Provider terms | Optional — **not used by Keys.AI** |

**Action item for commercial distribution:** the TeleGeography cable dataset is
NonCommercial. Commercial use requires removing that folder or licensing it from
TeleGeography.

---

## 3. Keys.AI files inspected (no external provenance)

Internal modules read to ground the integration: `main.py`, `ui.py`,
`core/tool_declarations.py`, `core/tool_registry.py`, `core/llm_client.py`,
`core/model_catalog.py`, `core/research_browser/{__init__,service,tools,workspace_ui}.py`,
`core/research_step.py`, `actions/crown_code.py`, `personality/`, `brain/`,
`universal_agent/`.

The prompt's suggested visual-asset catalogue (React Bits, Magic UI, Motion,
Three.js examples, LottieFiles, Lucide, Poly Haven, ambientCG, Unsplash, Pexels,
Google Fonts) was **not** used. The task required one specific integration rather
than new UI construction, so fetching decorative assets or icon packs would have
added dependencies with no requirement behind them.

---

## 4. Things checked and rejected

| Option | Why rejected |
|--------|--------------|
| Patch the vendored `src/main.js` to expose our own bridge | Unnecessary: the app already publishes `window.__godsEyeView.voiceCommands.runner`. Adding a second bridge would fork the vendor source for no gain |
| Drive the app through its MCP server | `server/mcp/server.js` exposes data reads; there is no camera/action control surface there |
| Navigate by rewriting the share-link URL | Encodes camera and layers, but re-applying it means a page reload, which resets the scene and interrupts the user. The runner moves the camera in place |
| Inline-embed panel mode (`globePanelRuntime.js`) | Designed for a host site talking JSON-RPC to the MCP server across a security boundary Keys.AI does not have. Orders of magnitude more moving parts than a local view |
| A second Ollama instance / new model endpoint | `core/model_catalog.py` and `core/llm_client.py` already own model routing; the globe needs no LLM at all |
| Building a new globe renderer | The requirement is to use the real implementation |
