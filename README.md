# Keys.ai - Autonomous AI Desktop Assistant

**ACENDENCE VII [GEN I]** - A premium AI assistant with voice, screen understanding, computer control, and autonomous coding capabilities.

---

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Core Components](#core-components)
4. [Tool System](#tool-system)
5. [Voice & Audio Pipeline](#voice--audio-pipeline)
6. [Screen & Vision System](#screen--vision-system)
7. [Computer Control](#computer-control)
8. [Crown Code - Autonomous Coding Agent](#crown-code---autonomous-coding-agent)
9. [Memory & Personalization](#memory--personalization)
10. [Plugin System](#plugin-system)
11. [Installation & Configuration](#installation--configuration)
12. [Development](#development)
13. [Project Structure](#project-structure)

---

## Overview

Keys.ai is a comprehensive AI desktop assistant that combines:

- **Live Voice Interaction** - Gemini 2.5 Flash Native Audio for real-time voice conversations
- **Screen Understanding** - Computer vision + OCR to see and analyze what's on screen
- **Computer Control** - UI Automation, keyboard/mouse control, window management
- **Autonomous Coding** - Crown Code agent that builds, fixes, and verifies software
- **File Operations** - Document creation (Word, Excel, PowerPoint), file management
- **Messaging** - WhatsApp, email, SMS integration
- **Web Research** - Browser automation, web search, research modes
- **Personal Memory** - Remembers user preferences, facts, and context

### Key Capabilities

| Capability | Description |
|------------|-------------|
| Voice Assistant | Real-time conversational AI with Gemini Live API |
| Screen Vision | See screen content, read text via OCR, analyze images |
| Desktop Automation | Control windows, type, click, run applications |
| Code Generation | Build complete applications, websites, dashboards |
| Document Creation | Create Word, Excel, PowerPoint files |
| Messaging | WhatsApp messages, Gmail, SMS |
| Web Research | Search, browse, capture screenshots and data |
| System Monitoring | CPU, RAM, GPU, temperature monitoring |
| Personal Memory | Long-term memory of user preferences and facts |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Keys.ai Application                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                     User Interface (Qt)                      │ │
│  │  - Main window, chat panel, voice controls                  │ │
│  │  - Screen capture preview, agent control overlay            │ │
│  │  - Settings, image studio, research browser                 │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                              │                                    │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    KeysAI Live Engine (main.py)              │ │
│  │  - Async audio pipeline (input/output queues)               │ │
│  │  - Gemini Live session management                           │ │
│  │  - Tool dispatch system                                     │ │
│  │  - Wake word detection                                      │ │
│  │  - Echo guard (prevent self-listening)                     │ │
│  │  - Session resumption                                      │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                              │                                    │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Tool Registry (core/tool_registry.py)     │ │
│  │  40+ tools registered, lazy-loaded on first use             │ │
│  │  - Action tools (actions/*.py)                             │ │
│  │  - Core tools (core/*.py)                                  │ │
│  │  - Plugin tools (plugins/*.py)                             │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                              │                                    │
│  ┌──────────────┬──────────────┬──────────────┬────────────────┐ │
│  │   Voice/Audio│   Vision/OCR │  Computer    │   Crown Code   │ │
│  │   - Gemini   │   - OpenCV   │  Control    │   - Ollama     │ │
│  │   - Audio    │   - Tesseract│  - pywinauto │   - Node.js    │ │
│  │   - PyAudio  │   - Screen   │  - Playwright│   - Agent loop │ │
│  └──────────────┴──────────────┴──────────────┴────────────────┘ │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Memory & State                           │ │
│  │  - Long-term memory (JSON files)                           │ │
│  │  - Session memory (conversation summary)                   │ │
│  │  - Config store (encrypted secrets)                        │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. main.py - Application Entry Point

**Location:** `main.py` (1577 lines)

**Purpose:** The main application class `KeysAILive` that orchestrates everything.

**Key Responsibilities:**

- **Audio Pipeline Management**
  - Async input/output queues for audio streaming
  - Gemini Live API connection management
  - Voice activity detection integration

- **Tool Dispatch**
  - Receives tool calls from Gemini model
  - Routes to appropriate handler via `TOOL_HANDLERS`
  - Handles special inline tools (memory, screen, camera, etc.)

- **Session Management**
  - Resumption handles for reconnecting
  - Session logging for end-of-session summaries
  - Plugin registry initialization

- **System Integration**
  - Background monitoring (CPU, RAM, processes)
  - Proactive suggestions engine
  - Wake word detection
  - Echo guard (prevents AI from hearing itself)

**Key Classes:**
- `KeysAILive` - Main engine class
- `_ReconnectSignal` - Exception for voluntary reconnection

### 2. ui.py - User Interface

**Location:** `ui.py` (6800+ lines)

**Purpose:** Qt-based graphical interface for Keys.ai.

**Key Features:**
- Main chat window with message history
- Voice control buttons (microphone, settings)
- Screen capture preview panel
- Agent control overlay (gold border, status pill)
- Embedded terminal for Crown Code output
- Image generation studio panel
- Research browser integration
- Settings dialogs (AI providers, models, keys)

**Key Classes:**
- `KeysAIUI` - Main window class
- Various signal/slot connections for async communication

### 3. core/tool_registry.py - Tool Dispatch System

**Location:** `core/tool_registry.py`

**Purpose:** Central registry mapping Gemini tool names to handler functions.

**Architecture:**
- 40 tools registered
- Lazy loading - each tool imports on first use (fast startup)
- Two categories:
  1. **Regular tools** - Dispatched via registry, loaded from actions/ or core/
  2. **Inline tools** - Handled directly by main.py (need session/UI state)

**Inline Tools (handled by main.py):**
- `save_memory` - Save facts to long-term memory
- `screen_process` - Capture and analyze screen
- `close_camera` - Close camera view
- `web_search` - Web search (also available as regular tool)
- `system_status` - Get system metrics
- `shutdown_keysai` - Close the application
- `recall_memory` - Search long-term memory
- `undo` - Undo last action
- `manage_monitor` - Background monitoring control

### 4. core/tool_declarations.py - Gemini Tool Schemas

**Location:** `core/tool_declarations.py`

**Purpose:** Canonical definitions of all tools as Gemini function declarations.

**Contents:**
- `TOOL_DECLARATIONS` - List of tool definitions with name, description, parameters
- Used by main.py to register tools with Gemini Live API
- Single source of truth for tool schemas

---

## Tool System

### Action Tools (actions/*.py)

Each action module implements a specific capability. Tools are loaded lazily on first use.

| Tool | Module | Description |
|------|--------|-------------|
| `open_app` | actions/open_app.py | Opens applications on the computer |
| `web_search` | actions/web_search.py | Searches the web (DuckDuckGo, Google) |
| `system_status` | actions/system_monitor.py | CPU, RAM, GPU, temperature metrics |
| `weather_report` | actions/weather_report.py | Weather information |
| `send_message` | actions/send_message.py | WhatsApp, Telegram messaging |
| `google_account` | actions/google_account.py | Google sign-in, contacts, emails |
| `send_email` | actions/send_email.py | Send emails via Gmail |
| `suggest_inbox_tasks` | actions/suggest_inbox_tasks.py | Analyze inbox for action items |
| `ai_settings` | actions/ai_settings.py | Configure AI provider, model, keys |
| `reminder` | actions/reminder.py | Set timed reminders (Task Scheduler) |
| `youtube_video` | actions/youtube_video.py | Play, search, summarize YouTube |
| `computer_settings` | actions/computer_settings.py | Volume, brightness, windows, WiFi |
| `desktop_control` | actions/desktop.py | Desktop wallpaper, organization (unused) |
| `code_helper` | actions/code_helper.py | Write, edit, run code files |
| `crown_code` | actions/crown_code.py | Autonomous coding agent |
| `file_processor` | actions/file_processor.py | Create/edit any file type |
| `computer_control` | actions/computer_control.py | Keyboard, mouse, screen control |
| `hybrid_control` | actions/hybrid_control.py | Multi-method desktop automation |
| `computer_use` | actions/computer_use.py | Deep Windows automation |
| `whatsapp_control` | actions/whatsapp_control.py | WhatsApp desktop automation |
| `editor_control` | actions/editor_control.py | Open/edit files in VS Code, Office |
| `game_updater` | actions/game_updater.py | Steam/Epic Games updates |
| `flight_finder` | actions/flight_finder.py | Google Flights search |
| `agent_control` | agent_control/tools.py | Full agent control mode |
| `agent_settings` | agent_control/tools.py | Agent control settings |
| `repo_inspect` | actions/repo_tool.py | Code intelligence (read-only) |
| `feature_demo` | actions/feature_demo.py | Demonstrate all capabilities |

### Core Tools (core/*.py)

| Tool | Module | Description |
|------|--------|-------------|
| `browser_control` | core/browser_control.py | Chromium browser automation |
| `research_browser` | core/research_browser/ | Embedded Chromium workspace |
| `globe` | globe/tools.py | God's Eye View - live camera dashboard |
| `image_studio` | core/image_studio/ | AI image generation (ComfyUI) |

---

## Voice & Audio Pipeline

### Architecture

```
User Speech → Microphone → Audio Queue → Gemini Live → Text Response
                                            ↓
                                   Tool Calls → Execution → Response
                                            ↓
                                   TTS → Audio Queue → Speakers
```

### Components

**Audio Input:**
- PyAudio for microphone capture
- 16kHz sample rate, mono channel
- Chunked streaming to Gemini Live

**Audio Output:**
- Gemini Live TTS (text-to-speech)
- 24kHz sample rate for playback
- Async queue prevents blocking

**Gemini Live Session:**
- `LIVE_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"`
- Native audio modality (no transcription intermediate)
- Tool calling support
- Session resumption handles

**Voice Features:**
- Wake word detection (optional, local)
- Echo guard (prevents feedback loop)
- Barge-in (interrupt by voice, opt-in)
- Phone mic support (pauses PC mic when active)

---

## Screen & Vision System

### Screen Capture

**Tools:** `screen_process`, `computer_settings` (screenshot action)

**Capabilities:**
- Full screen capture
- Webcam capture
- Region-specific capture
- Automatic cooldown between captures

**Processing Pipeline:**
1. Capture screen/image via PyAutoGUI or OpenCV
2. Send to Gemini vision for analysis
3. Return text description/answer

### OCR (Optical Character Recognition)

**Location:** `core/vision.py`

**Used By:**
- Screen text reading
- Document analysis
- WhatsApp message verification

### Vision Tools

| Function | Description |
|----------|-------------|
| `vision_generate_text` | Send image to Gemini for analysis |
| `_capture_screen` | Capture screen to bytes |
| `_capture_camera` | Capture webcam to bytes |

---

## Computer Control

### Tiered Automation Approach

Keys.ai uses a tiered approach to computer control, choosing the most reliable method:

```
Tier 1: Windows UI Automation (pywinauto)
        - Most reliable for standard Windows apps
        - Can read control properties, not just screen

Tier 2: Native App APIs (Playwright/CDP)
        - For browsers and apps with automation support
        - DOM-level access, not pixel-based

Tier 3: Computer Vision + OCR
        - When no automation API available
        - Visual element detection

Tier 4: Mouse/Keyboard (pyautogui)
        - Last resort, pixel-coordinate based
        - Works everywhere but less reliable
```

### Computer Control Tools

| Tool | Method | Use Case |
|------|--------|----------|
| `computer_control` | PyAutoGUI + UIA | Direct keyboard/mouse, screen find |
| `hybrid_control` | UIA → Playwright → CV → PyAutoGUI | Automatic best-method selection |
| `computer_use` | UIA first, then CV, then coordinates | Deep Windows automation |
| `agent_control` | UIA + CV + visual overlay | Visible control with gold border |
| `editor_control` | App-specific (VS Code, Office) | Open/edit files in native apps |
| `computer_settings` | Multiple backends | Volume, brightness, windows, WiFi |

### Agent Control Mode

**Features:**
- Animated gold border around controlled application
- Watermark and status pill showing current action
- ESC/STOP always works immediately
- Genuine user input auto-pauses
- High-impact actions ask for confirmation

**Actions:**
- `take_control` - Start controlling an app
- `find` - Find element by description
- `click` - Click element
- `type` - Type text
- `hotkey` - Press key combination
- `scroll` - Scroll page/window
- `drag` - Drag and drop
- `wait` - Wait for condition
- `verify` - Verify action succeeded

---

## Crown Code - Autonomous Coding Agent

### Overview

Crown Code is the autonomous coding agent that can build, fix, and verify software projects. It's the primary tool for any coding task.

**Location:** `actions/crown_code.py` (1400+ lines)

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Crown Code Pipeline                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. REQUIREMENTS GATE                                       │
│     - Analyze brief for missing information                 │
│     - Ask user questions if needed (interactive UI)         │
│     - Refuse to build on assumptions                        │
│                                                              │
│  2. WORKSPACE SETUP                                         │
│     - Create project directory                              │
│     - Write brief.json with request details                 │
│                                                              │
│  3. BUILD TARGET DECISION                                   │
│     - App (recipe built offline)                            │
│     - Site (rendered page)                                  │
│     - Code (general agent)                                  │
│                                                              │
│  4. MODEL READINESS (if needed)                             │
│     - Check Ollama availability                             │
│     - Ensure model is pulled                                │
│                                                              │
│  5. EXECUTION (background job)                              │
│     ┌─────────────────────────────────────────────────────┐ │
│     │ SITE PATH:                                          │ │
│     │ - Plan → Render → Verify (fast, ~1 min)            │ │
│     │ - Or: Plan → Model write → Verify (custom)         │ │
│     ├─────────────────────────────────────────────────────┤ │
│     │ APP PATH:                                           │ │
│     │ - Recipe → Write → Compile → Test → Verify         │ │
│     ├─────────────────────────────────────────────────────┤ │
│     │ CODE PATH (full autonomous pipeline):               │ │
│     │ 1. Memory persistence (entity profiles)            │ │
│     │ 2. Browser research & asset harvesting              │ │
│     │ 3. Blueprint & master prompt synthesis              │ │
│     │ 4. Crown Code agent loop (write, run, fix)         │ │
│     └─────────────────────────────────────────────────────┘ │
│                                                              │
│  6. VERIFICATION                                            │
│     - Project tests (if any)                                │
│     - Design gate (UI quality checks)                       │
│     - Runtime checks (browser launch, broken images)        │
│                                                              │
│  7. COMPLETION                                              │
│     - Open artifact in browser/app                          │
│     - Report summary with file count, bytes, time           │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Build Paths

**1. Site Path (websites, portfolios, landing pages)**
- Uses `core/site_builder.py`
- Fast mode: Plan → Render → Verify (~1 minute)
- Custom mode: Also let model write bespoke design
- Renders from plan as guaranteed floor
- Verifies in real browser

**2. App Path (dashboards, desktop apps, recipes)**
- Uses `core/app_builder.py`
- Recipe-based: compile, seed, serve, self-test
- No model needed (fully offline)
- Verified: compiles, runs, endpoints respond

**3. Code Path (general coding, dashboards, tools)**
- Uses `core/crown_bridge.py` → Crown Code agent
- Local model (Ollama) or cloud
- Full agent loop: read, write, run, fix
- Repair passes for failing tests
- Design gate for UI projects

### Agent Loop (Crown Code Bridge)

```
┌─────────────────────────────────────────────────────────────┐
│                    CrownBridge (core/crown_bridge.py)        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Start Node.js headless agent (dist/headless.js)        │
│  2. Send task prompt to local LLM (Ollama)                 │
│  3. Agent iterates:                                        │
│     - Read files (ls, cat)                                 │
│     - Write/edit files (write_file, edit_file)             │
│     - Run commands (terminal)                              │
│     - Check results                                        │
│  4. Events streamed back:                                  │
│     - tool_start, tool_end                                │
│     - terminal_output, terminal_exit                      │
│     - progress updates                                     │
│  5. Bridge monitors:                                       │
│     - Wall-clock timeout                                   │
│     - Cancellation                                         │
│     - Tool usage tracking                                  │
│  6. Result: ok/fail + summary + files written              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Requirements System

Crown Code NEVER assumes requirements. Before building:

1. **Analyze brief** - Check for missing information
2. **Ask questions** - If questions exist and no confirmation:
   - Use `player.ask_decision()` for interactive questions
   - Generate smart defaults as options
3. **Collect answers** - Re-analyze with user's responses
4. **Proceed or refuse** - If still missing, return `refusal_text`

**Question Categories:**
- Data source (for dashboards)
- Metrics to display
- Chart types
- Tech stack
- Scope (single user vs multi-user)
- Subject (for websites/portfolios)
- Theme/aesthetic

### Verification

**Project Tests:**
- Run `pytest` if test files exist
- Repair pass: agent fixes failing tests
- Max 2 repair attempts

**Design Gate:**
- Check color contrast (WCAG AA)
- Check for lorem ipsum, TODOs in visible copy
- Check for broken images
- Check font sizes, spacing

**Runtime Check:**
- Launch built artifact
- Check for console errors
- Check for broken images

---

## Memory & Personalization

### Long-Term Memory

**Location:** `memory/memory_manager.py`, `memory/config_manager.py`

**Storage:** JSON files in user's data directory

**Features:**
- Save facts about user (name, preferences, projects, etc.)
- Search memory by keyword
- Auto-trim old entries
- Session summaries

**Categories:**
- `identity` - name, age, birthday, city, job
- `preferences` - food, color, music, hobbies
- `projects` - active projects, goals
- `relationships` - friends, family, colleagues
- `wishes` - future plans, travel dreams
- `notes` - habits, schedule, other

### Session Memory

**Purpose:** Track conversation turns for end-of-session summary

**Features:**
- In-memory log of conversation
- Summary generated at session end
- NOT persisted (fresh start each launch)

### Config Store

**Location:** `core/config_store.py`

**Features:**
- Load/save configuration
- Encrypted secrets storage (`config/secrets.enc`)
- API keys, voice settings, device config

---

## Plugin System

### Architecture

**Location:** `core/plugin_loader.py`

**Purpose:** Allow drop-in Python files in `plugins/` directory to add new tools.

**How It Works:**
1. At startup, `discover_plugins()` scans `plugins/` directory
2. Each `.py` file is loaded as a plugin module
3. Plugin must expose `has(name)` and `run(name, params, player, session_memory)`
4. `PluginDispatch.set_plugin_fallback()` registers the registry
5. When a tool isn't found in `TOOL_HANDLERS`, the plugin fallback is consulted

### Plugin Structure

```python
# plugins/my_tool.py

def has(name: str) -> bool:
    return name == "my_tool"

def run(name: str, parameters: dict, player, session_memory=None) -> str:
    if name != "my_tool":
        return None
    # Tool implementation
    return "Result"
```

---

## Installation & Configuration

### Prerequisites

- Python 3.12+
- Ollama (for local models)
- Git (for Crown Code)
- Various Python packages (see requirements.txt)

### Installation

1. **Clone/set up Crown Code:**
   ```
   git clone <crown-code-repo> Crown CODE
   ```

2. **Configure API keys:**
   - Edit `config/api_keys.json`
   - Add Gemini API key for voice
   - Add Ollama (local) or other providers

3. **Install Ollama models:**
   ```
   ollama pull qwen3:8b        # Primary coding model
   ollama pull qwen3-coder:30b # Heavy coding tasks
   ```

4. **Run:**
   ```
   python main.py
   ```

### Configuration Files

| File | Purpose |
|------|---------|
| `config/api_keys.json` | API keys for providers |
| `config/crown_code.json` | Crown Code settings (model, provider, timeout) |
| `config/brain.json` | Brain/SMART mode settings |
| `config/secrets.enc` | Encrypted sensitive data |

### Environment

- `CROWN_CODE_DIR` - Path to Crown Code checkout
- `OLLAMA_HOST` - Ollama server URL (default: http://localhost:11434)
- `CROWN_ENGINE` - "legacy" or "v2" for Crown Code engine

---

## Development

### Project Structure

```
keys-ai/
├── main.py                    # Application entry point
├── ui.py                      # Qt user interface
├── requirements.txt           # Python dependencies
├── install.py                 # Installation script
├── install.bat                # Windows installer
├── icon.png                   # App icon
├── keysai.spec                # PyInstaller spec
├── actions/                   # Action tools (40+ tools)
│   ├── crown_code.py          # Autonomous coding agent
│   ├── file_processor.py      # File creation/editing
│   ├── computer_control.py    # Keyboard/mouse control
│   ├── browser_control.py     # Browser automation
│   ├── send_message.py        # WhatsApp/Telegram
│   ├── google_account.py      # Google integration
│   ├── ... (30+ more action modules)
│   └── __init__.py
├── core/                      # Core libraries
│   ├── tool_registry.py       # Tool dispatch system
│   ├── tool_declarations.py   # Gemini tool schemas
│   ├── plugin_loader.py       # Plugin system
│   ├── crown_bridge.py        # Crown Code bridge
│   ├── brief_spec.py          # Requirements analysis
│   ├── site_builder.py        # Website builder
│   ├── app_builder.py         # App builder
│   ├── design_system.py       # Design tokens
│   ├── vision.py              # Computer vision
│   ├── llm_client.py          # LLM client
│   ├── memory/                # Memory system
│   ├── research_browser/      # Embedded browser
│   ├── image_studio/          # Image generation
│   └── ...
├── agent_control/             # Agent control module
│   ├── tools.py               # Agent control tools
│   ├── app_control.py         # App control utilities
│   └── ...
├── plugins/                   # User plugins (drop-in)
├── config/                    # Configuration files
│   ├── api_keys.json          # API keys
│   ├── crown_code.json        # Crown Code config
│   └── ...
├── memory/                    # Memory storage
│   ├── memory_manager.py      # Memory operations
│   └── ...
├── dashboard/                 # Dashboard web app
│   ├── server.py              # Dashboard server
│   └── static/
├── globe/                     # God's Eye View app
│   ├── tools.py               # Globe tool
│   └── ...
├── tests/                     # Test suite
├── qa_artifacts/              # QA tests and artifacts
├── docs/                      # Documentation
├── scripts/                   # Utility scripts
└── __pycache__/               # Python cache (git-ignored)
```

### Adding a New Tool

1. **Create action module:** `actions/my_tool.py`
   ```python
   def my_tool(parameters: dict, player, speak=None) -> str:
       # Implementation
       return "Result"
   ```

2. **Add to declarations:** `core/tool_declarations.py`
   ```python
   {'name': 'my_tool', 'description': '...', 'parameters': {...}}
   ```

3. **Add to registry:** `core/tool_registry.py`
   ```python
   "my_tool": (lambda p, ui, s: _load("actions.my_tool", "my_tool")()(p, ui, s) or "Done."),
   ```

### Testing

Run tests:
```bash
python -m pytest tests/ -v
python test_crown_flow.py      # Crown Code integration test
python test_crown_code.py      # Crown Code bridge test
```

### Crown Code Agent

The Crown Code agent runs as a separate Node.js process:

- **Location:** `Crown CODE/dist-headless/headless.js`
- **Communication:** JSON over stdin/stdout
- **Model:** Local Ollama or cloud API

---

## Project Structure (Detailed)

### Action Modules (actions/)

**Active Tools (in tool_registry):**
- `ai_settings.py` - AI provider/model/key management
- `background_monitor.py` - System monitoring background task
- `browser_control.py` - Web browser automation
- `code_helper.py` - Code writing/editing/running
- `computer_control.py` - Keyboard/mouse/screen control
- `computer_settings.py` - Volume, brightness, windows
- `computer_use.py` - Deep Windows automation
- `crown_code.py` - Autonomous coding agent (main)
- `editor_control.py` - VS Code/Office editing
- `file_controller.py` - File management
- `file_processor.py` - Document creation/editing
- `flight_finder.py` - Google Flights
- `google_account.py` - Google sign-in/contacts/emails
- `hybrid_control.py` - Multi-method automation
- `make_call.py` - Phone calls
- `open_app.py` - Application launcher
- `proactive.py` - Proactive suggestions
- `reminder.py` - Task Scheduler reminders
- `repo_tool.py` - Code repository inspection
- `screen_processor.py` - Screen/camera capture
- `send_email.py` - Gmail sending
- `send_message.py` - WhatsApp/Telegram
- `suggest_inbox_tasks.py` - Inbox task suggestions
- `system_monitor.py` - System metrics
- `weather_report.py` - Weather
- `web_search.py` - Web search
- `whatsapp_control.py` - WhatsApp automation
- `whatsapp_takeover.py` - WhatsApp desktop control
- `youtube_video.py` - YouTube control
- `feature_demo.py` - Capability demonstration

**Helper Modules:**
- `_extract_json_helpers.py` - JSON extraction utilities
- `_file_readers.py` - File reading utilities
- `_office_builder.py` - Office document building
- `_office_xlsx.py` - Excel building
- `_powerbi_prompt.py` - PowerBI prompts

**Unused/Removed:**
- `desktop.py` - Removed (not in tool_registry)
- `dev_agent.py` - Removed (deprecated, routes to crown_code)
- `live_code.py` - Removed (not in tool_registry)
- `call_rule.py` - Removed (not in tool_registry)
- `call_rules.py` - Removed (not in tool_registry)

### Core Modules (core/)

**Tool System:**
- `tool_registry.py` - Tool dispatch (40 tools)
- `tool_declarations.py` - Gemini tool schemas
- `plugin_loader.py` - Plugin discovery/loading

**Crown Code:**
- `crown_bridge.py` - Agent bridge (Node.js <-> Python)
- `crown_jobs.py` - Background job management
- `brief_spec.py` - Requirements analysis
- `blueprint_engine.py` - Blueprint generation
- `research_harvester.py` - Asset/research harvesting
- `build_recipes.py` - Build recipe detection

**Building:**
- `site_builder.py` - Website/page builder
- `app_builder.py` - Application builder
- `site_studio/` - Site rendering studio
- `site_checks.py` - Site verification
- `app_checks.py` - App verification
- `app_specs.py` - App specifications
- `game_builder.py` - Game builder
- `build_recipes.py` - Recipe definitions

**Design:**
- `design_system.py` - Design tokens, colors
- `design_check.py` - Design quality verification
- `design_research.py` - Color sampling from images

**AI/LLM:**
- `llm_client.py` - LLM client (Gemini, Ollama, etc.)
- `gemini_ladder.py` - Gemini API with fallbacks
- `model_catalog.py` - Provider/model management
- `api_config.py` - API key/config management
- `config_store.py` - Configuration storage
- `persona.py` - Persona/prompt management

**Vision:**
- `vision.py` - Computer vision, image analysis
- `camera_preview.py` - Camera preview

**Memory:**
- `memory/` - Memory storage and management
- `session_store.py` - Session data
- `secret_store.py` - Encrypted secrets

**Research:**
- `research_browser/` - Embedded Chromium
- `research_step.py` - Research workflow

**Other:**
- `audio_devices.py` - Audio device management
- `avatar.py` - Avatar system
- `avatar_mesh.py` - 3D avatar mesh
- `avatar_bridge.py` - Avatar communication
- `echo.py` - Echo guard
- `face_model.obj` - Face mesh model
- `confirm.py` - Confirmation gate
- `confirm_ui.py` - Confirmation UI
- `health_check.py` - Health checks
- `undo.py` - Undo system
- `wake_word.py` - Wake word detection
- `viseme.py` - Viseme (mouth shapes)
- `features_knowledge.py` - Feature documentation
- `doc_builder.py` - Document building
- `ast_verifier.py` - AST verification
- `persona.py` - Persona system
- `prompt.txt` - System prompt

### Agent Control (agent_control/)

- `tools.py` - Agent control tool implementation
- `app_control.py` - Application control utilities

### Dashboard (dashboard/)

- `server.py` - Dashboard web server
- `static/` - Static assets (HTML, CSS, JS)

### Memory (memory/)

- `memory_manager.py` - Memory CRUD operations
- `config_manager.py` - Memory config
- `memory/` - Memory data files

### Research Browser (core/research_browser/)

- `__init__.py` - Module exports
- `service.py` - Browser service
- `tools.py` - Research tools
- `collector.py` - Data collection
- `library.py` - Library management
- `assets.py` - Asset management
- `paths.py` - Path management
- `urls.py` - URL management
- `version.py` - Version info
- `workspace_ui.py` - Workspace UI

### Image Studio (core/image_studio/)

- `service.py` - Image generation service
- `studio_ui.py` - Studio UI panel
- `workflows.py` - Generation workflows
- `validation.py` - Output validation
- `prompt_enhancer.py` - Prompt enhancement
- `installer.py` - ComfyUI installation
- `comfy_client.py` - ComfyUI client
- `registry.py` - Service registry
- `settings.py` - Settings
- `downloads.py` - Download management

### Globe (globe/)

- `tools.py` - Globe tool implementation
- `server/` - Globe server
- Real-time camera dashboard

### Universal Agent (universal_agent/)

- `workers/` - Background workers
- `tools/` - Additional tools
- `service.py` - Service orchestration
- `planner.py` - Planning
- `intake.py` - Request intake

---

## Key Files Reference

### Entry Points
- `main.py` - Main application (KeysAILive engine)
- `ui.py` - Qt GUI

### Configuration
- `config/api_keys.json` - API keys (Gemini, etc.)
- `config/crown_code.json` - Crown Code settings
- `requirements.txt` - Python dependencies

### Tool Definitions
- `core/tool_declarations.py` - All tool schemas (single source of truth)
- `core/tool_registry.py` - Tool dispatch mapping

### Crown Code
- `actions/crown_code.py` - Main Crown Code entry point
- `core/crown_bridge.py` - Bridge to Node.js agent
- `core/brief_spec.py` - Requirements analysis
- `core/site_builder.py` - Website building
- `core/app_builder.py` - Application building

### Voice/Audio
- `main.py` (KeysAILive class) - Audio pipeline
- `core/echo.py` - Echo guard
- `core/wake_word.py` - Wake word detection
- `core/audio_devices.py` - Device management

### Vision
- `core/vision.py` - Vision analysis
- `actions/screen_processor.py` - Screen capture

### Memory
- `memory/memory_manager.py` - Memory operations
- `core/config_store.py` - Configuration

---

## License

See LICENSE file for details.

---

## Author

Harman Sadhwani - Lead AI Architect & Systems Engineer, Creator of Keys.ai
