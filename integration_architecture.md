# Browser-Based R&D Workspace — Concrete Integration Architecture

Date: 2026-10-26
Status: audit + draft architecture only. No upstream code touched yet.
Scope: how KEYS.AI could embed a real, interactive browser research workspace without
replacing the existing PyQt6 app.

This doc sketches component boundaries and reuse/adaptation decisions. It is not a build
plan and not a commitment to integrate any specific upstream project as-is.


## 1. Core decision

Keep the in-app QtWebEngine browser as KEYS.AI’s primary browser host.

Why:
- `core/research_browser/service.py` already uses `QWebEnginePage`.
- That gives KEYS.AI the property the request cares about most: the human and the agent
  operate on the same visible page.
- The overlay workspace pattern is already used by AI Image Studio and the Project Agent.
- Replacing that with a separate external browser would be a larger architectural change
  than the request implies.


## 2. What each upstream project is actually good for

browser-use (Python, MIT)
- Best fit for: observation model and DOM-simplification ideas, and possibly isolated type/serializer modules.
- Not a fit for: replacing the Qt browser host, or adopting the full agent loop wholesale.
- Key reuseable concepts seen in source:
  - `BaseChatModel` protocol (`browser_use/llm/base.py`) as a clean local-provider contract.
  - DOM types and serializer pipeline (`browser_use/dom/views.py`, `dom/serializer/serializer.py`, `dom/serializer/clickable_elements.py`).
  - Action model shapes (`browser_use/tools/views.py`, `browser_use/tools/service.py`).
  - Browser state summary shape (`browser_use/browser/views.py`).
- Important coupling visible in source:
  - `browser_use/__init__.py` patches `asyncio.base_subprocess.BaseSubprocessTransport.__del__`.
  - `browser_use/agent/service.py` is deeply wired: `bubus.EventBus`, message manager, judge, filesystem, telemetry, cloud auth, skills.
  - `browser_use/tools/service.py` imports from browser events, DOM service, filesystem, tool registry.
  - `browser_use/dom/views.py` imports from `cdp_use.cdp.*`.
  - So any reuse needs to be selective, not “copy one folder and it works.”

agent-browser (TypeScript/Next.js, MIT)
- Best fit for: API design reference if KEYS.AI ever wants a browser-as-service sidecar.
- Not a fit for: direct Python embedding.
- Not adopted here unless KEYS.AI deliberately adds a Node sidecar.

qz-browser-agent (Chrome extension + Node CLI/MCP, Apache-2.0)
- Best fit for: UX/concept patterns, not code.
- Patterns worth borrowing:
  - shared visible workspace where human and agent both see the page
  - task/subtask parallelism
  - save-run-as-skill reuse
  - CLI/MCP-style delegation of a web task to a real browser
- Not a fit for: direct Python embedding or Qt UI reuse.

firecrawl (API-first scraper/crawler, AGPLv3)
- Best fit for: research-collection/citation/document-parse surface if KEYS.AI already decided a remote backend is acceptable.
- Not a fit for: in-app browser embedding.
- Decision needed before any use: license against KEYS.AI shipping model.


## 3. Recommended component boundaries

### Component A — In-app browser host (KEEP / EXTEND)
Owner: `core/research_browser`
Responsibility:
- Tab lifecycle, navigation, downloads, permissions, shared visible page.
- agent-accessible browser operations through JS on the same page.
- workspace overlay attachment the way AI Image Studio already does similar overlays.

What this component should gain, if anything:
- better structured observation APIs for an agent to consume,
- clearer tab/state capture for pause/resume and evidence capture,
- tighter integration with the research-collection layer below.

What this component should NOT become:
- a full sighted agent loop borrowed from browser-use.

### Component B — Browser observation / interaction model (ADAPT, possibly borrow ideas or types)
Owner: new or extended module inside `core.research_browser` or a dedicated subpackage.
Responsibility:
- turn the live Qt page into a structured observation the agent can reason about:
  - simplified DOM representation,
  - clickable/semantic element detection,
  - element selector/identifier scheme,
  - screenshots sized for model consumption,
  - page text and structure extraction with source linkage.
- expose a KEYS.AI action model for browser operations.

Reuse strategy:
- Borrow concepts and possibly isolated types/algorithms from browser-use’s DOM serializer and clickable-element logic.
- Adapt, not copy wholesale, because browser-use’s modules are not cleanly decoupled from its CDP/bubus/cloud/agent stack.

### Component C — Research collection / evidence layer (EXTEND existing collector/library)
Owner: `core.research_browser.collector` / `core.research_browser.library`, plus document/coding reuse paths.
Responsibility:
- record research sources with URL, title, extracted text/snippet, timestamp, and which tab/action produced them.
- support collections: groups of evidence tied to a research task.
- support export/reuse into documents and coding workflows.

This is the part that maps to “research collections and direct reuse of gathered evidence in documents and coding workflows.”

### Component D — Browser task delegation / agent handoff (OPTIONAL, patterned on qz + browser-use action model)
Owner: actions layer or a new browser-task entrypoint.
Responsibility:
- let KEYS.AI (or a future external agent) hand a web task to the in-app browser workspace.
- expose structured browser actions rather than raw mouse coordinates where possible.
- optionally support save/reuse of successful browser task recipes as skills.

### Component E — Optional remote research backend (ONLY IF chosen and licensed)
Owner: external integration layer.
Responsibility:
- if KEYS.AI wants web-scale search/scrape/interact/document-parse, this is where that backend would sit.
- Firecrawl is the strongest functional fit seen in this audit, but AGPLv3 makes it a conditional choice, not a default one.

If AGPLv3 is not acceptable, replace this component with a non-copyleft backend before any integration.


## 4. “Reuse vs adaptation” verdict

Reuse as-is:
- browser-use full Agent loop: no, too coupled and wrong mental model for KEYS.AI’s workspace.
- agent-browser whole stack: no, wrong language/runtime.
- qz extension code: no, it is a Chrome extension + Node CLI, not a Python Qt module.
- firecrawl as an in-app browser component: no, wrong category entirely.

Adapt selectively:
- browser-use DOM/observation concepts and possibly isolated types/serializers: yes, with care.
- browser-use `BaseChatModel` protocol idea: yes, as a local-provider contract reference.
- qz visible-workspace, skill-reuse, delegation patterns: yes, conceptually.
- agent-browser REST/vision API shapes: yes, as design reference only.

Do not adopt yet:
- any upstream as the browser host,
- firecrawl without a license decision first,
- agent-browser unless KEYS.AI explicitly wants a Node sidecar.


## 5. “Same page the user sees” mapping

| Requirement | Best upstream match | KEYS.AI home if built this way |
|---|---|---|
| live website navigation | existing QtWebEngine workspace | `core/research_browser.service.BrowserService` |
| search | browser tools + optional backend | browser workspace search workflow + optional research backend |
| clicks | JS click on the visible page | `BrowserService.click_element` / adapted interaction layer |
| screenshots | same page screenshot | `BrowserService` screenshot path already exists in repo artifacts |
| source-linked text and image extraction | observation layer + collector | Component B + Component C |
| downloads | validated asset fetch path | existing browser download gating + asset validation |
| citations | research collection layer | Component C |
| research collections | collector/library | Component C |
| reuse in documents/coding | export/reuse bridge | Component C + document/coding worker paths |

So the existing `core/research_browser` module is the right spine; the missing parts are mostly the observation model, the research-collection semantics, and the reuse/export bridge.


## 6. Local model support decision

For KEYS.AI, the more natural local-model path is:
- KEYS.AI calls the local model directly for browser observation/action decisions,
- using the provider path the app already has,
- with the browser observation layer providing the page state.

That fits browser-use’s `BaseChatModel` protocol shape conceptually, but KEYS.AI does not need to import browser-use to do it; it just needs a clean local-provider contract in its own code if it does not already have one that fits.

If the alternative is “delegate browser tasks to an external agent process,” that becomes a different architecture (sidecar/MCP/CLI delegation), and the closest upstream patterns are qz’s CLI/MCP bridge and agent-browser’s API model, not browser-use’s embedded Python agent loop.


## 7. Concrete next integration checklist

1. Decide the host model: embedded Qt workspace (recommended) vs external browser service (bigger change).
2. Decide the local-model path: direct model calls vs external agent delegation.
3. Decide the research-backend path: optional remote backend yes/no, and if yes, license-clean first.
4. If borrowing from browser-use, pick only isolated modules/concepts and verify import coupling before copying anything.
5. If considering firecrawl, get a concrete legal read on AGPLv3 against KEYS.AI’s shipping model before any copy or dependency.
6. Define the observation contract: what the agent can ask the Qt page for, in what shape, with what timeouts.
7. Define the research-collection schema before building extraction flows, because citation/source linkage should be designed in, not bolted on.
8. Define the reuse/export bridge for documents/coding workflows, because that is the part that makes the workspace “research” rather than just “browser.”
