"""
Canonical tool registry for Keys.ai - ACENDENCE VII [GEN I].

Single source of truth mapping Gemini tool names to handler functions.

Every heavy dependency (pyautogui, playwright, cv2, numpy, genai, ...) is
imported LAZILY inside each handler, so importing this module costs nothing
and the first call to a tool pays its own import cost. Startup never loads
the automation stack.

Special tools handled inline by the engine (main.py) because they need
session/UI state beyond (parameters, ui, speak):
    save_memory, screen_process, close_camera, web_search,
    system_status, shutdown_keysai, recall_memory, undo, manage_monitor
"""

import importlib


def _load(module: str, fn: str):
    """Return a zero-cost loader for a named function (import on call)."""
    def _get():
        return getattr(importlib.import_module(module), fn)
    return _get


# name -> callable(parameters, ui, speak) -> str
# Each handler returns the final user-facing string (fallback included),
# preserving the exact behavior of the old main.py dispatch chain.
TOOL_HANDLERS: dict = {
    "open_app": (lambda p, ui, s: _load("actions.open_app", "open_app")()(
        parameters=p, response=None, player=ui)
        or f"Opened {p.get('app_name')}."),

    "weather_report": (lambda p, ui, s: _load("actions.weather_report", "weather_action")()(
        parameters=p, player=ui) or "Weather delivered."),

    "browser_control": (lambda p, ui, s: _load("actions.browser_control", "browser_control")()(
        parameters=p, player=ui) or "Done."),

    "file_controller": (lambda p, ui, s: _load("actions.file_controller", "file_controller")()(
        parameters=p, player=ui) or "Done."),

    "send_message": (lambda p, ui, s: _load("actions.send_message", "send_message")()(
        parameters=p, response=None, player=ui, session_memory=None)
        or f"Message sent to {p.get('receiver')}."),

    "google_account": (lambda p, ui, s: _load("actions.google_account", "google_account")()(
        parameters=p, response=None, player=ui) or "Google account action done."),

    "send_email": (lambda p, ui, s: _load("actions.send_email", "send_email")()(
        parameters=p, response=None, player=ui) or "Email sent."),

    "suggest_inbox_tasks": (lambda p, ui, s: _load("actions.suggest_inbox_tasks", "suggest_inbox_tasks")()(
        parameters=p, response=None, player=ui, session_memory=None) or "No task suggestions."),

    "ai_settings": (lambda p, ui, s: _load("actions.ai_settings", "ai_settings")()(
        parameters=p, response=None, player=ui) or "AI settings updated."),

    "reminder": (lambda p, ui, s: _load("actions.reminder", "reminder")()(
        parameters=p, response=None, player=ui) or "Reminder set."),

    "youtube_video": (lambda p, ui, s: _load("actions.youtube_video", "youtube_video")()(
        parameters=p, response=None, player=ui) or "Done."),

    "computer_settings": (lambda p, ui, s: _load("actions.computer_settings", "computer_settings")()(
        parameters=p, response=None, player=ui) or "Done."),

    "desktop_control": (lambda p, ui, s: _load("actions.desktop", "desktop_control")()(
        parameters=p, player=ui) or "Done."),

    "code_helper": (lambda p, ui, s: _load("actions.code_helper", "code_helper")()(
        parameters=p, player=ui, speak=s) or "Done."),

    "crown_code": (lambda p, ui, s: _load("actions.crown_code", "crown_code")()(
        parameters=p, player=ui, speak=s) or "Done."),

    # Dev Agent is retired: its execution path now routes to Crown Code so the
    # old coding agent can never run alongside the new one.
    "dev_agent": (lambda p, ui, s: _load("actions.crown_code", "crown_code")()(
        parameters=p, player=ui, speak=s) or "Done."),

    "file_processor": (lambda p, ui, s: _load("actions.file_processor", "file_processor")()(
        parameters=p, player=ui, speak=s) or "Done."),

    "computer_control": (lambda p, ui, s: _load("actions.computer_control", "computer_control")()(
        parameters=p, player=ui) or "Done."),

    "hybrid_control": (lambda p, ui, s: _load("actions.hybrid_control", "hybrid_control")()(
        parameters=p, response=None, player=ui) or "Done."),

    "computer_use": (lambda p, ui, s: _load("actions.computer_use", "computer_use")()(
        parameters=p, response=None, player=ui) or "Done."),

    "whatsapp_control": (lambda p, ui, s: _load("actions.whatsapp_control", "whatsapp_control")()(
        parameters=p, response=None, player=ui) or "Done."),

    "editor_control": (lambda p, ui, s: _load("actions.editor_control", "editor_control")()(
        parameters=p, response=None, player=ui) or "Done."),

    "game_updater": (lambda p, ui, s: _load("actions.game_updater", "game_updater")()(
        parameters=p, player=ui, speak=s) or "Done."),

    "flight_finder": (lambda p, ui, s: _load("actions.flight_finder", "flight_finder")()(
        parameters=p, player=ui) or "Done."),

    "agent_control": (lambda p, ui, s: _load("agent_control.tools", "agent_control")()(
        parameters=p, player=ui, speak=s) or "Done."),

    "agent_settings": (lambda p, ui, s: _load("agent_control.tools", "agent_settings")()(
        parameters=p, player=ui, speak=s) or "Done."),

    # Read-only code intelligence: inventory, symbols, imports and targeted
    # search over a project folder. Never writes, never executes project code.
    "repo_inspect": (lambda p, ui, s: _load("actions.repo_tool", "repo_inspect")()(
        parameters=p, player=ui) or "Done."),

    # Broad web search used as the creative-writing page's file I/O surface: it
    # is the only declared tool that can fetch live content from the internet, so
    # the page reuses it to keep the creative-writing loop from becoming read-only.
    "web_search": (lambda p, ui, s: _load("actions.web_search", "web_search")()(
        parameters=p, player=ui) or "Done."),

    # Real, visible Chromium workspace: navigation, observation, screenshots,
    # source/asset collection and integration into the current project. The
    # browser lives in the app process, so the agent acts on the page the user
    # is looking at.
    "research_browser": (lambda p, ui, s: _load(
        "core.research_browser.tools", "execute")()(parameters=p, player=ui, speak=s)
        or "Done."),

    # God's Eye View — the real globe application, run as a local service and
    # hosted in Keys.AI's own Chromium workspace. Text and voice commands are
    # the only entry point; there is no globe button in the UI.
    "globe": (lambda p, ui, s: _load("globe.tools", "globe")()(
        parameters=p, ui=ui, speak=s)
        or "The globe did not report a result."),

    # Inline-only tools: handled by main.py because they need session/UI state
    # beyond (parameters, ui, speak). They are still declared to the model, but
    # they are not dispatched through the lazy-load registry.
    "close_camera": (lambda p, ui, s: None or "Done."),
    "manage_monitor": (lambda p, ui, s: None or "Done."),
    "recall_memory": (lambda p, ui, s: None or "Done."),
    "save_memory": (lambda p, ui, s: None or "Done."),
    "screen_process": (lambda p, ui, s: None or "Done."),
    "shutdown_keysai": (lambda p, ui, s: None or "Done."),
    "system_status": (lambda p, ui, s: None or "Done."),
    "undo": (lambda p, ui, s: None or "Done."),

    # The skill layer: list, inspect, choose and run capabilities that are
    # declared in the skills/ package. Each skill delegates to a tool that is
    # already registered above, so this adds routing, not a second engine.
    "skills": (lambda p, ui, s: _load("skills.tools", "skills")()(
        parameters=p, ui=ui, speak=s) or "Done."),

    # "Demo" — performs each capability live instead of describing it.
    "feature_demo": (lambda p, ui, s: _load("actions.feature_demo", "feature_demo")()(
        parameters=p, player=ui, speak=s) or "Done."),

}


class PluginDispatch:
    """Chainable fallback: serves plugin tools after the core registry.

    main.py installs a discovered PluginRegistry into `set_plugin_fallback()`
    at startup; the engine's `else` branch then consults it, so a drop-in
    plugins/*.py file becomes a callable tool without touching the core.
    Replaces None clears the fallback.
    """

    _fallback = None

    @classmethod
    def set_plugin_fallback(cls, registry) -> None:
        cls._fallback = registry

    @classmethod
    def try_plugin(cls, name: str, parameters: dict, ui, speak=None):
        """Return the plugin's result string, or None when `name` is not a
        (valid, enabled) plugin tool."""
        reg = cls._fallback
        if reg is None or not hasattr(reg, "has") or not reg.has(name):
            return None
        return reg.run(name, parameters, player=ui, session_memory=None)
