# Keys.ai — Installation & Pre-configuration

One command bootstraps a brand-new machine (or a fresh checkout) into a
working, pre-configured setup. It follows the "ensure state" pattern used by
configuration-management tools (Ansible/Salt): **create what's missing, never
touch what exists.**

## Quick start

**Windows** — double-click `install.bat`, or:

```bat
python install.py
```

**Linux / macOS** (headless-safe parts only — the agent itself is Windows):

```bash
python3 install.py
```

That single command:

| Step | What happens |
|------|--------------|
| 1 | Checks Python ≥ 3.10 |
| 2 | Creates `.venv` (the project's consistent runtime) |
| 3 | Installs `requirements.txt` — **`uv` when available** (fast, modern dependency management), pip fallback |
| 4 | Installs **Playwright Chromium** (WhatsApp Web + dashboard) |
| 5 | Installs `pyaudiowpatch` (receptionist *hearing*) and prints **VB-CABLE** guidance (receptionist *speaking*) |
| 6 | **Scaffolds missing configs**: `api_keys.json` template, `call_rules.json` defaults, `agent_control.json`, empty `brain.json` / `personality.json` / `entities.json` / `session_state.json` / `window_state.json`, `certs/` |
| 7 | Runs the **doctor self-check** and prints next steps |

### Flags

```text
--doctor           only run the self-check (no changes)
--no-venv          install into the current interpreter instead of .venv
--skip-deps        don't reinstall Python dependencies
--skip-playwright  don't reinstall Playwright browsers
--skip-scaffold    don't touch the config directory
--test             run the unit test suite after installing
--quiet            reduced output
```

Examples:

```bat
python install.py --doctor          :: health check anytime
python install.py --test            :: full install + run all tests
```

## First-run pre-configuration (what a new user gets)

- **Gemini API key** — `config/api_keys.json` is created as an empty template;
  the app shows its setup overlay on first launch and saves your key.
- **WhatsApp** — sign in to the WhatsApp **desktop app** (or link WhatsApp Web
  once); Keys.ai drives the desktop app for messaging, with WhatsApp Web as
  the automatic fallback for reading chats.
- **Google-verified contacts** (message gate) — follow `FIREBASE_SETUP.md`,
  then say *"sign in with Google"*. `send_message` can be gated on verified
  contacts when `require_verified=true`.

## Dependency management

- `requirements.txt` is the single source of truth.
- `uv` is preferred when present (`uv pip install`), with automatic fallback to
  `python -m pip install`.
- Everything installs **into `.venv`**, so the system Python stays untouched.

## Containerization (the honest version)

Keys.ai is a **Windows-native desktop-automation agent**: PyQt6 GUI, pywinauto /
pywin32 desktop control, WASAPI loopback audio, WhatsApp Desktop automation.
Windows containers have **no interactive desktop session**, so the agent cannot
*execute* inside a container, and Linux containers cannot run Windows software
at all.

What the included `Dockerfile` + `docker-compose.windows.yml` DO give you
(Docker Desktop → *Switch to Windows containers*):

1. **Reproducible build** — a pinned Windows Server Core + Python 3.12 image
   installs the exact deps + Playwright Chromium and runs PyInstaller, so the
   packaged `dist\KeysAI.exe` is bit-for-bit repeatable (consistent runtime for
   packaging and CI):

   ```bat
   docker-compose -f docker-compose.windows.yml build
   ```

2. **Runtime asset image** — the `runtime` stage bundles the exe, the Playwright
   browsers (`PLAYWRIGHT_BROWSERS_PATH=C:\ms-playwright`) and a config volume,
   ready to `docker cp` onto any Windows host that has a desktop session:

   ```bat
   docker build --target runtime --tag keysai/runtime .
   ```

The executable itself always runs on a real Windows desktop (or a Windows VM
with an RDP session) — that is the boundary, and it is a hard one.
