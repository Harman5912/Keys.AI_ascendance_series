# Browser Embedding Candidates — AUDITED INVENTORY

Date: 2026-10-26
Scope: read only — no checkout, install, copy, or modification of upstream was performed.
Sources were fetched from public GitHub raw URLs only where necessary to confirm a detail.

## Upstream projects audited
- https://github.com/browser-use/browser-use
- https://github.com/smouj/agent-browser
- https://github.com/alibaba/qz-browser-agent
- https://github.com/firecrawl/firecrawl


## 1. browser-use / browser-use (Python, MIT)

Downloads: massive PyPI presence.
Verified from files:
- pyproject.toml
- README.md
- browser_use/__init__.py
- browser_use/agent/service.py
- browser_use/agent/views.py
- browser_use/agent/prompts.py
- browser_use/dom/serializer/serializer.py
- browser_use/dom/serializer/clickable_elements.py
- browser_use/browser/profile.py
- browser_use/browser/cloud/cloud.py
- browser_use/dom/views.py
- browser_use/browser/views.py
- browser_use/tools/service.py
- browser_use/llm/base.py


### What it is
A Python browser agent library. Its public API orbits around:
- Agent(task, llm, browser=...)
- a BaseChatModel protocol for LLM backends
- Tools / Controller action model
- DomService snapshot pipeline
- BrowserSession / BrowserProfile / browser-use-core binary

One concrete detail worth noting: its `BaseChatModel` is a `typing.Protocol`, so the library is built to accept any compatible async chat model, not only its own provider wrappers. That is the part most relevant if KEYS.AI wants local-model support.


### Architecture (as actually seen in code)
- Agent is the orchestrated loop: read browser state -> LLM decide next action -> apply action -> repeat.
- Browser state comes from DomService snapshots: simplified DOM tree, clickable-element detection, paint-order removal, bounding-box filtering, selector map.
- Browser operations go through BrowserSession, which wraps cdpx / cdp-use underneath.
- Profile build is its own layer with lots of Chromium CLI args, deterministic rendering args, headless/docker args, extension handling, persistent profile handling.
- Cloud mode exists but is a separate hosted product (BROWSER_USE_API_KEY), not on-device.


### Strengths for KEYS.AI
- Strong Python-first DOM simplification + clickable-element serialization with comparator logic visible in serializer.py and clickable_elements.py.
- Good sighted-agent observation model: screenshot + simplified DOM + interactive element detection.
- Explicit action model: navigate, click (by index, including coordinate-click support for certain models), input, scroll, evaluate, goto, wait, type, press, scroll, screenshot, get_text, get_attribute, etc.
- Agent loop already includes planning, loop detection, message compaction, judge, extraction schema, failure handling, action history.
- Good local-model story in README: OpenAI, Anthropic, Google, Groq, Ollama, and others are first-class; the Agent takes any BaseChatModel.
- Persistence and profile semantics are explicit.


### Weaknesses / mismatches for KEYS.AI
- It is a sighted agent loop first. Embedding it as a passive human-visible browser workspace means you largely discard its agent loop, prompt templates, and planner/judge machinery — or else you couple KEYS.AI tightly to its agent mental model.
- The visible browser is not a Qt/embedded panel model. It drives a separate browser process. If KEYS.AI wants “the same page the user sees inside the app,” this is not that.
- Python side is real, but the browser is still a separate Chromium/Playwright/CDP thing. The repository leans on browser-use-core binary wheels and cdpx/cdp-use.
- Telemetry, PostHog, cloud URLs, cloud product docs, and cloud auth paths are present. Not necessarily bad for local-only use, but relevant for contribution/distribution expectations and packaging.


### License
MIT.
- browser-use itself: MIT.
- It depends on many other projects with their own licenses.
- The README / docs mention a hosted cloud product and separate terms; the open-source library is MIT, but don’t treat the commercial cloud bits as MIT.


### Concrete reuseable modules
Good reuse candidates if you want a sighted DOM/observation layer:
- dom/serializer/: DOMTreeSerializer, ClickableElementDetector, PaintOrderRemover
- dom/views.py: DOM model types (DOMRect, EnhancedDOMTreeNode, SimplifiedNode, SerializedDOMState, DOMSelectorMap, NodeType, etc.)
- browser/ profile.py / session view machinery for CDP-driven browser state
- tools/ service.py for the action model

Less useful as-is for KEYS.AI:
- agent/service.py full Agent loop
- agent/prompts.py system-prompt machinery
- cloud/cloud.py (hosted product path)


### Dependencies of note
From pyproject.toml, browser-use depends on a large stack including:
- browser-use-core (platform-specific binary wheels)
- cdp-use==1.4.5
- browser-use-sdk>=3.10.0,<4
- playwright-ish/cdp-ish connection paths
- LLM SDKs: openai, anthropic, google-genai/google-api-python-client, groq, ollama, litellm, etc.
- pydantic, httpx, requests, aiohttp, rich, click, python-docx, pypdf, reportlab, pillow, markdownify, mcp, posthog, psutil, screeninfo, pyobjc, etc.

So bringing it in is not “just one library”; it brings a fairly heavy dependency tree and platform-specific binary requirements.


## 2. smouj/agent-browser (TypeScript/Next.js, MIT)

Verified from files:
- README.md
- package.json
- src/app/page.tsx
- src/app/api/browser/sessions/route.ts
- src/app/api/browser/sessions/[id]/route.ts
- src/app/api/browser/sessions/[id]/action/route.ts
- src/app/api/browser/sessions/[id]/vision/route.ts
- src/lib/browser/engine.ts

### What it is
A Next.js 16 + Playwright + Prisma + TypeScript platform that wraps Playwright browser instances behind a REST + real-time API and a web dashboard.

### Architecture
- BrowserEngine singleton manages Playwright browser instances and session map.
- createSession launches a Playwright browser/context/page and stores an ActiveSession.
- REST routes expose sessions CRUD, action execution, and vision capture.
- Vision capture includes screenshot + simplified DOM + accessibility tree + interactive element detection.
- Frontend is a dark dashboard with session list, live preview, action log.


### Strengths
- Clean HTTP+JSON design: very easy to call from Python backend if KEYS.AI ever wants that direction.
- Real session model, action log, and vision endpoint.
- Multi-browser via Playwright (chromium/firefox/webkit).

### Weaknesses for KEYS.AI
- This is a Node/Next.js service, not a Python library.
- Embedding it means running a separate Node service, or embedding Playwright in a JS/TS environment. KEYS.AI is PyQt6 + Python. That is a real mismatch unless you deliberately add a sidecar.
- The dashboard is a web app, not a Qt panel component; reusing its UI in a PyQt app would be a rewrite anyway.
- It is oriented more toward “agent handoff via API” than “in-app live workspace with shared view”.

### License
MIT.

### Concrete reuseable modules
- Vision capture idea and simplified-DOM + a11y tree + interactive elements: good conceptual reference.
- Action executor shape and session model: good API design reference.
- Actual code reuse is limited for a Python app unless KEYS.AI adds a Node sidecar on purpose.


## 3. alibaba/qz-browser-agent (Chrome extension + Node CLI/MCP, Apache-2.0)

Verified from files:
- README.md

I could not authenticate to GitHub code search, so I verified repository shape from README only; deeper file-level source inspection for the extension itself was not completed in this audit.

### What it is
A Chrome extension that runs a browser agent inside your local Chrome side panel, plus a Node CLI/MCP bridge (`npx qz-browser-agent`) that lets other agents hand tasks to qz.

### Strengths
- Strong alignment with “real browser you are already signed into”, visible side panel, human+agent shared control, save-run-as-skill, parallel task/subtask model.
- Very close philosophically to the KEYS.AI goal: research workspace plus reuse of gathered evidence.
- Apache-2.0 license.

### Weaknesses / mismatches for KEYS.AI
- It is a Chrome extension + Node CLI, not a Python module.
- Its browser is the user’s Chrome. That is excellent for a browser-extension product; for KEYS.AI’s in-app workspace model, that is a different embedding target.
- Visible UI is Chrome side panel, not a PyQt overlay.
- Direct Python embedding would mean either:
  - calling it as an external CLI/MCP service, or
  - adapting extension-side JS concepts into the app.

### License
Apache-2.0.

### Concrete reuseable ideas
- Task/subtask parallelism model.
- Skill reuse concept.
- “visible side panel where human and agent share the same page” UX pattern.
- CLI/MCP delegation pattern for handing web tasks off to a real browser.


## 4. firecrawl/firecrawl (API-first scraper/crawler, AGPLv3)

Verified from files:
- README.md
- LICENSE

### What it is
A web data API: search, scrape, crawl, map, batch scrape, interact, parse documents. Open-source repo, but its license is AGPLv3 and it also has a hosted service.

### Strengths
- Excellent fit for “research collection, citations, source extraction, batch page extraction” as a backend capability if you want a remote scrape/search pipeline.
- Interact endpoint is relevant: scrape then click/scroll/type/wait then extract.
- Document parsing (PDF/DOCX) is relevant to evidence reuse in documents/coding workflows.

### Weaknesses / mismatches for KEYS.AI
- AGPLv3 is the decisive issue for KEYS.AI’s likely distribution model. If KEYS.AI is a desktop app and you incorporate AGPLv3 code in a way that triggers network-interaction obligations, that can force source-disclosure requirements. Even if you only use the API, the project itself is AGPLv3 and any local self-hosted usage still has to be evaluated carefully against how KEYS.AI ships.
- Firecrawl is remote-API-first. The repo is not an in-app browser embedding toolkit; it is a web data backend.
- It does not give you “same page the user sees inside the app.”

### License
AGPLv3.

### Concrete reuseable ideas
- If you decide a remote research backend is acceptable, its scrape/interact/search/document-parse surface is a strong fit for the research-collection part of the goal.
- Not the right anchor for an interactive in-app browser workspace.


## Comparative read on “same page the user sees”

- KEYS.AI already has core/research_browser/service.py using QWebEnginePage (QtWebEngine). The important property there is shared visibility: the human and the agent operate on the same visible page.
- browser-use drives a separate browser and is sighted-agent oriented.
- agent-browser drives a separate browser and is a REST/Node service.
- qz-browser-agent drives the user’s Chrome via extension.
- firecrawl is a web-data backend.

So for “embed a real interactive browser workspace in KEYS.AI” with minimal disruption to the existing app, the closest existing architectural match is KEYS.AI’s own QtWebEngine host, not any of these four upstream browser projects.


## Architecture recommendation direction

Do not adopt any of the four as a wholesale browser host for KEYS.AI. They solve overlapping but different problems.

A stronger split:

### 1) In-app browser host
Keep the QtWebEngine workspace as KEYS.AI’s shared visible browser. This preserves:
- same page for human and agent
- overlay workspace pattern already used by AI Image Studio and Project Agent
- minimal disruption to existing app

### 2) Observation + interaction layer
From browser-use, borrow ideas and possibly isolated modules for:
- simplified DOM serialization
- clickable element detection
- selector map / index-based element targeting
- screenshot-to-LLM sizing
- action naming conventions
but only as a KEYS.AI observation model around the existing Qt page, not as a separate agent loop.

### 3) Research collection / extraction backend
If a remote/web-scale scrape/search/document-parse backend is acceptable on licensing and architecture grounds, firecrawl’s surface is a strong fit for the collection/citation part.
If AGPLv3 exposure is not acceptable, this option should be dropped or replaced with a non-copyleft backend before any integration.

### 4) Agent delegation pattern
From qz-browser-agent, borrow:
- visible shared workspace UX concept
- skill reuse pattern
- delegation/cli/mcp-style “hand a web task to a real browser” model
adapted to KEYS.AI’s own in-app workspace, not copied as an extension.

### 5) Sidecar/API option
If KEYS.AI ever wants a browser-as-service rather than an embedded panel, agent-browser is a decent API design reference, but it would be a separate Node service, not a Python component.


## License summary

- browser-use: MIT
- agent-browser: MIT
- qz-browser-agent: Apache-2.0
- firecrawl: AGPLv3

Only firecrawl is currently a red flag for KEYS.AI if KEYS.AI is shipped/distributed in a way that could trigger AGPL obligations, or if KEYS.AI’s owners want to avoid AGPL exposure entirely.

### Distribution model read from this repo (before legal decision)

From the audit artifacts in the repo itself, KEYS.AI is a local PyQt6 desktop application (`main.py`, `ui.py`, `mini_overlay.py`), with AI features delivered through model providers rather than through a KEYS.AI-hosted public network service. The repo artifacts also reference PyInstaller packaging (`keysai.spec`) and desktop artifact generation, which suggests distribution is or may be desktop distribution, not a pure SaaS backend.

That matters for this decision:
- If KEYS.AI stays primarily a local desktop app and does not become a network service that users interact with over a network, the AGPLv3 “network use triggers source disclosure” pressure is more about the boundary question than about browser-use/agent-browser/qz, all of which are permissive.
- If KEYS.AI ever ships a networked KEYS.AI service component, firecrawl becomes a much bigger licensing question and should not be adopted without a concrete legal read.
- Even for local-only distribution, AGPLv3 is still the right caution flag for firecrawl specifically, because copying AGPLv3 code into KEYS.AI or depending on AGPLv3 code is not the same as just using a permissive library.

### License verification method

The permissive licenses for browser-use, agent-browser, and qz-browser-agent were confirmed through their public datasheets: browser-use’s `pyproject.toml` declares `License :: OSI Approved :: MIT License`; agent-browser’s `package.json` declares `"license": "MIT"`; qz-browser-agent’s `README.md` states `Apache-2.0` explicitly. Firecrawl’s `README.md` contains a direct link to `https://github.com/firecrawl/firecrawl/blob/main/LICENSE`, and its license file was read from the repo and is AGPLv3.

GitHub code search is not authenticated in this environment, so these licenses were not found via repo search; they were read from the upstream metafiles where the projects publish them.


## Open questions / verification still needed before integration

### Answers to the open follow-up questions

#### 1. What is KEYS.AI’s distribution model, and does AGPLv3 matter?
Based on this repo, KEYS.AI looks like a local PyQt6 desktop application first, with model-backed AI features, not a KEYS.AI-hosted public network service. That is the safer end of the AGPLv3 question for firecrawl, but it does not make firecrawl free to copy into KEYS.AI. If KEYS.AI stays local-only and firecrawl is only called as a remote API, practical exposure is lower; if KEYS.AI is ever packaged as a networked service or modified AGPLv3 code is distributed, the AGPLv3 obligations become a real legal question and should be reviewed before any firecrawl dependency or local self-hosting.

#### 2. Embedded Qt workspace vs external browser service?
For KEYS.AI specifically, the best fit is to keep the embedded QtWebEngine workspace as the primary browser host. The repo already has `core/research_browser/service.py` with `QWebEnginePage`, and the key architectural property there is shared visibility: the human and the agent operate on the same visible page. browser-use, agent-browser, and qz-browser-agent all drive separate browsers, so none of them is a drop-in replacement for that model without a bigger change than the request implies.

#### 3. If borrowing browser-use modules, which ones are independent enough?
From the source actually read, the safer reuse targets are the more isolated pieces, not the full agent loop:
- `browser_use/llm/base.py`: `BaseChatModel` protocol — useful as the contract for plugging in local providers.
- `browser_use/dom/views.py`: DOM model types (`DOMRect`, `EnhancedDOMTreeNode`, `SimplifiedNode`, `SerializedDOMState`, `DOMSelectorMap`, `NodeType`, etc.).
- `browser_use/dom/serializer/serializer.py` and `clickable_elements.py`: DOM simplification, paint-order removal, bounding-box filtering, clickable-element detection.
- `browser_use/tools/service.py` and `browser_use/tools/views.py`: the action model and action execution plumbing.
- `browser_use/browser/views.py`: browser-state summary types (`BrowserStateSummary`, `TabInfo`, `PageInfo`).

Manually verified non-trivial coupling that argues against wholesale copy:
- `browser_use/__init__.py` patches `asyncio.base_subprocess.BaseSubprocessTransport.__del__`.
- `browser_use/agent/service.py` imports and uses `bubus.EventBus`, session/auth/cloud plumbing, message manager, telemetry, filesystem, judge, and skills paths.
- `browser_use/tools/service.py` imports from `browser_use.browser.events`, `browser_use.dom.service`, `browser_use.filesystem`, `browser_use.tools.registry`, etc.
- `browser_use/dom/views.py` imports directly from `cdp_use.cdp.*` types.

So the realistic reuse path is: borrow the DOM/observation concepts and types as adaptation material, not assume you can drop in a self-contained browser-use slice without importing half its dependency graph.

#### 4. Firecrawl AGPLv3 — what decision is needed?
Before any firecrawl use, decide whether KEYS.AI will ever be:
- a distributed desktop product that includes/links AGPLv3 code,
- a networked KEYS.AI service that users interact with,
- or only a local app that optionally calls an external firecrawl API.

If firecrawl is used only as a remote API and KEYS.AI itself does not incorporate AGPLv3 code, the question changes from “can we copy firecrawl?” to “is the remote-service integration acceptable under KEYS.AI’s policies and the firecrawl terms for the chosen usage path?” That is still worth confirming, but it is a different question than embedding AGPLv3 code.

#### 5. Local model support — direct calls vs delegating browser tasks?
For KEYS.AI’s existing pattern, the more natural choice is direct local model calls for browser observation/action decisions, using the same provider path the app already uses, not spinning up a separate agent process just to drive a browser. browser-use’s `BaseChatModel` protocol is the most relevant upstream artifact here if KEYS.AI wants a clean contract for that.

#### 6. Agent drives browser only, or human and agent share the same visible page?
For KEYS.AI, the strongest match is “human and agent share the same visible page,” because the repo already has that property in `core/research_browser/service.py`. That choice immediately downweights browser-use, agent-browser, and qz-browser-agent as browser hosts, and shifts them into “observation/interaction ideas and possibly isolated module reuse” instead.
