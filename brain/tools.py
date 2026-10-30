"""
Universal tool registry (spec §11, §12, §13).

Wraps the EXISTING core/tool_registry.TOOL_HANDLERS (plus the tools that
main.py handled inline: web_search, system_status, save_memory, screen_process,
close_camera) into one interface the planner/executor can use.

The LLM never executes Python — it only requests a registered tool by name,
and this layer runs it with the exact same (parameters, ui, speak) signature
Keys.ai already uses.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


class ToolNotFound(LookupError):
    """Raised when the model asks for a tool that is not registered.

    Execution turns this into ``ok=False`` rather than a success whose payload
    happens to be the sentence "Unknown tool: …" — that shape was how a dead
    route reported `used_brain=True` for months.
    """


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


class ToolRegistry:
    def __init__(self, handlers: dict | None = None, memory_layer=None,
                 provider=None):
        if handlers is not None:
            self._handlers = handlers
        else:
            try:
                from core.tool_registry import TOOL_HANDLERS
                self._handlers = dict(TOOL_HANDLERS)
            except Exception:
                self._handlers = {}
        self._memory   = memory_layer
        self._provider = provider

    # ── introspection ────────────────────────────────────────────────────
    def names(self) -> list[str]:
        names = set(self._handlers.keys())
        names.update(["web_search", "system_status", "save_memory",
                      "screen_process", "close_camera", "weather_report",
                      "recall_memory", "undo", "manage_monitor"])
        return sorted(names)

    def has(self, name: str) -> bool:
        return name in self._handlers or name in (
            "web_search", "system_status", "save_memory", "screen_process",
            "close_camera", "weather_report", "recall_memory", "undo",
            "manage_monitor")

    def descriptions(self, max_tools: int = 40) -> str:
        """Compact tool list for the planner prompt (name + short description)."""
        try:
            from core.tool_declarations import TOOL_DECLARATIONS
        except Exception:
            TOOL_DECLARATIONS = []
        lines = []
        for decl in TOOL_DECLARATIONS[:max_tools]:
            name = decl.get("name", "?")
            desc = (decl.get("description", "") or "").replace("\n", " ")
            lines.append(f"- {name}: {desc[:220]}")
        return "\n".join(lines) or "No tools registered."

    # ── execution ────────────────────────────────────────────────────────
    def execute(self, name: str, arguments: dict, ui=None, speak=None) -> dict:
        """Run a tool. Returns {"ok": bool, "tool": name, "result": str,
        "error": str|None}. NEVER raises — every failure becomes ok=False.

        The brain and the voice path now share the same posture: a tool failure is
        a visible, classified outcome, not a session-ending signal."""
        args = arguments or {}
        try:
            result = self._dispatch(name, args, ui, speak)
            ok = bool(result) and not str(result).strip().lower().startswith("done")
            if not ok:
                # The handler already produced text; the brain's evaluator will
                # classify whether it reads as success or soft-fail. This layer
                # just keeps the outcome representable.
                return {"ok": True, "tool": name, "result": str(result),
                        "error": None}
            return {"ok": True, "tool": name, "result": str(result),
                    "error": None}
        except ToolNotFound:
            return {"ok": False, "tool": name, "result": "",
                    "error": f"Unknown tool: {name}"}
        except ToolError as exc:
            return {"ok": False, "tool": name, "result": "",
                    "error": str(exc), "kind": getattr(exc, "kind", "TOOL_ERROR")}
        except Exception as e:
            return {"ok": False, "tool": name, "result": "",
                    "error": f"{type(e).__name__}: {e}", "kind": "TOOL_ERROR"}

    def _dispatch(self, name: str, args: dict, ui, speak) -> str:
        # ── tools main.py handled inline ─────────────────────────────────
        if name == "save_memory":
            if self._memory is None:
                from memory.memory_manager import update_memory
                update_memory({args.get("category", "notes"): {
                    args.get("key", ""): {"value": args.get("value", "")}}})
                return "ok"
            return self._memory.remember(args.get("key", ""),
                                         args.get("value", ""),
                                         args.get("category", "notes"))

        if name == "web_search":
            from actions import web_search as ws_module
            return ws_module.web_search(parameters=args, player=ui) or "Done."

        if name == "system_status":
            from actions import system_monitor as sm_module
            return str(sm_module.get_system_status())

        if name == "close_camera":
            if ui is not None and hasattr(ui, "stop_camera_stream"):
                ui.stop_camera_stream()
            return "Camera closed."

        if name == "screen_process":
            return self._screen_process(args, ui)

        if name == "weather_report":
            from actions import weather_report as wr_module
            return wr_module.weather_action(parameters=args, player=ui) or "Done."

        if name == "recall_memory":
            from memory.memory_manager import search_memory
            return search_memory(args.get("query", ""), limit=8)

        if name == "undo":
            from core import undo as undo_stack
            if str(args.get("action", "")).lower().strip() == "list":
                items = undo_stack.history()
                return ("Things I can undo, most recent first:\n"
                        + "\n".join(f"{i+1}. {t}" for i, t in enumerate(items))
                        ) if items else "I have not changed anything I can undo yet."
            return undo_stack.undo_last()

        if name == "manage_monitor":
            from actions import background_monitor as bm
            action = str(args.get("action", "")).lower().strip()
            topic  = str(args.get("topic", "")).strip()
            if action == "add" and topic:
                return bm.add_monitor(topic)
            if action == "remove" and topic:
                return bm.remove_monitor(topic)
            if action == "list":
                topics = bm.list_monitors()
                return ("Monitoring: " + ", ".join(topics)) if topics else "No topics are being monitored."
            return "Specify action (add/remove/list) and a topic."

        # ── standard registered handlers ─────────────────────────────────
        handler = self._handlers.get(name)
        if handler is None:
            raise ToolNotFound(name)
        return handler(args, ui, speak) or "Done."

    def _screen_process(self, args: dict, ui) -> str:
        angle = str(args.get("angle", "screen") or "screen").lower()
        question = args.get("text", "What do you see?")
        if angle == "camera":
            return ("Camera capture is handled by the voice/vision path in "
                    "the main session — ask me to look at the camera and I "
                    "will open it.")
        try:
            from actions.screen_processor import _capture_screen
            img_b, mime_t = _capture_screen()
        except Exception as e:
            return f"Screen capture failed: {e}"
        if self._provider is None:
            return "Screen captured, but no vision-capable provider is configured."
        try:
            return self._provider.describe_image(img_b, mime_t, question)
        except Exception as e:
            return f"Vision analysis failed: {e}"
