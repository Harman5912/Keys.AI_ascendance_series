"""AI tool handlers for Agent Control Mode.

    agent_control — the full control tool: take/release control of any app,
                    inspect, find, click, type, press, hotkey, scroll, drag,
                    move mouse, select/copy/paste, switch window/tab, open
                    apps, wait/verify, history, humour, confirm.

    agent_settings — change humour / dark humour / professional mode /
                     retry limit / confirmation / overlay settings without
                     touching the AI provider.

Every argument is validated before execution (unknown actions and bad values
return an honest error — never a fake success). High-impact actions pause for
confirmation. ControlStopped (ESC / STOP) always wins.
"""

from __future__ import annotations

from typing import Optional

from agent_control.app_control import (
    AppControlEngine, ControlStopped, get_control_engine,
)
from agent_control.settings import get_settings, settings_summary


def _params(parameters: dict | None) -> dict:
    return parameters or {}


def _int(v, default=None):
    if v in (None, "", "None"):
        return default
    try:
        return int(v)
    except Exception:
        return default


def _float(v, default=None):
    if v in (None, "", "None"):
        return default
    try:
        return float(v)
    except Exception:
        return default


def _bool(v, default=False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _xy(value) -> Optional[tuple]:
    if value in (None, "", "None"):
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return (int(value[0]), int(value[1]))
        except Exception:
            return None
    s = str(value).replace("(", "").replace(")", "").replace(",", " ").split()
    if len(s) >= 2:
        try:
            return (int(s[0]), int(s[1]))
        except Exception:
            return None
    return None


def _finish(res) -> str:
    """Render an ActionResult into a user-facing string (+ optional humour)."""
    if res is None:
        return "Done."
    msg = getattr(res, "message", str(res)) or "Done."
    if isinstance(res, object) and hasattr(res, "data"):
        humour = (res.data or {}).get("humour")
        if humour and humour not in msg:
            msg = f"{msg} ({humour})"
    return msg


def agent_control(parameters: dict, player=None, speak=None) -> str:
    params = _params(parameters)
    action = (params.get("action") or "").strip().lower()
    if not action:
        return ("No action specified for agent_control. Valid: status, "
                "take_control, release, pause, resume, stop, takeover, apps, "
                "active_app, inspect, elements, find, click, double_click, "
                "right_click, type, press, hotkey, scroll, drag, move, select, "
                "copy, paste, switch_window, switch_tab, open_app, wait, verify, "
                "history, history_clear, humour, confirm.")

    engine = get_control_engine(player=player)
    try:
        # ── session control ─────────────────────────────────────────────
        if action in ("status", "state", "control_status"):
            return _finish(engine.status())

        if action in ("take_control", "control"):
            return _finish(engine.take_control(params.get("app") or None))

        if action in ("release", "release_control", "hand_back"):
            return _finish(engine.release_control())

        if action in ("pause", "pause_control"):
            return _finish(engine.pause(why=params.get("why", "paused by request")))

        if action in ("resume", "continue_task"):
            return _finish(engine.resume())

        if action in ("stop", "emergency_stop", "abort"):
            return _finish(engine.stop())

        if action in ("takeover", "user_takeover", "give_control"):
            return _finish(engine.user_takeover())

        # ── perception ──────────────────────────────────────────────────
        if action in ("apps", "list_apps", "applications", "windows"):
            return _finish(engine.core().discover(limit=_int(params.get("limit"), 60)))

        if action in ("active_app", "active_window", "foreground_app"):
            return _finish(engine.detect_active_window())

        if action in ("inspect", "inspect_screen", "describe"):
            return _finish(engine.inspect_screen(deep=_bool(params.get("deep"), False)))

        if action in ("elements", "components", "accessibility", "inspect_accessibility"):
            return _finish(engine.inspect_accessibility(params.get("window", "")))

        if action in ("find", "find_element", "locate"):
            return _finish(engine.find_element(params.get("description", ""),
                                               params.get("window", "")))

        # ── interaction ─────────────────────────────────────────────────
        if action in ("click", "click_element"):
            return _finish(_with_confirm(
                engine, params, "click",
                lambda: engine.click(
                    description=params.get("description", ""),
                    x=_int(params.get("x")), y=_int(params.get("y")),
                    button=(params.get("button") or "left").lower(),
                    clicks=_int(params.get("clicks"), 1))))

        if action in ("double_click",):
            return _finish(engine.double_click(params.get("description", ""),
                                               _int(params.get("x")),
                                               _int(params.get("y"))))

        if action in ("right_click",):
            return _finish(engine.right_click(params.get("description", ""),
                                              _int(params.get("x")),
                                              _int(params.get("y"))))

        if action in ("type", "type_text"):
            text = params.get("text", "")
            if not text:
                return "Provide text to type."
            return _finish(engine.type(
                text, description=params.get("description", ""),
                x=_int(params.get("x")), y=_int(params.get("y")),
                private=_bool(params.get("private"), False)))

        if action in ("press", "press_key", "key"):
            key = params.get("key", "")
            if not key:
                return "Provide a key name, e.g. 'enter', 'esc', 'tab', 'f5'."
            return _finish(engine.press_key(key))

        if action in ("hotkey", "shortcut", "keys"):
            keys = params.get("keys", "")
            if not keys:
                return "Provide a key combination, e.g. 'ctrl+s'."
            return _finish(engine.hotkey(keys))

        if action in ("scroll",):
            return _finish(engine.scroll(
                direction=(params.get("direction") or "down"),
                amount=_int(params.get("amount"), 3),
                target=params.get("target", "")))

        if action in ("drag", "drag_element"):
            return _finish(engine.drag(
                source=params.get("source_description", params.get("src", "")),
                destination=params.get("target_description", params.get("dst", "")),
                source_xy=_xy(params.get("source_xy", params.get("from_xy"))),
                destination_xy=_xy(params.get("target_xy", params.get("to_xy")))))

        if action in ("move", "move_mouse", "mouse"):
            x, y = _int(params.get("x")), _int(params.get("y"))
            xy = _xy(params.get("xy"))
            if xy:
                x, y = xy
            if x is None or y is None:
                return "Provide x and y coordinates (or xy='x,y')."
            return _finish(engine.move_mouse(x, y))

        if action in ("select", "select_text"):
            return _finish(engine.select_text(all_text=_bool(params.get("all"), True)))

        if action in ("copy",):
            return _finish(engine.copy())

        if action in ("paste",):
            return _finish(engine.paste())

        if action in ("switch_window", "focus_window"):
            target = params.get("target") or params.get("title") or params.get("app")
            if not target:
                return "Provide the window title to switch to."
            return _finish(engine.switch_window(target))

        if action in ("switch_tab", "tab"):
            return _finish(engine.switch_tab(
                direction=(params.get("direction") or "next").lower(),
                index=_int(params.get("index")),
                browser=params.get("browser", "")))

        if action in ("open_app", "open_application", "launch"):
            name = params.get("app") or params.get("app_name") or params.get("name")
            if not name:
                return "Provide the application name to open."
            return _finish(engine.open_application(name))

        # ── waiting / verification ──────────────────────────────────────
        if action in ("wait", "wait_for", "wait_until"):
            kind = (params.get("kind") or "element").lower()
            target = params.get("target", "") or params.get("description", "")
            timeout = _float(params.get("timeout"))
            if kind == "element":
                return _finish(engine.wait_for_element(target, timeout=timeout))
            return _finish(engine.verify_action(kind, target, timeout=timeout))

        if action in ("verify", "verify_action", "check"):
            kind = (params.get("kind") or "element").lower()
            target = params.get("target", "") or params.get("description", "")
            return _finish(engine.verify_action(kind, target,
                                                timeout=_float(params.get("timeout"))))

        # ── history / humour / confirm ──────────────────────────────────
        if action in ("history", "log", "control_history"):
            return _finish(engine.history_log(_int(params.get("limit"), 24)))

        if action in ("history_clear", "clear_history"):
            return _finish(engine.clear_history())

        if action in ("humour", "joke", "comment"):
            event = (params.get("event") or "generic").lower()
            c = engine.humour_comment(event, params.get("app", ""))
            return c or ("Humour is OFF or professional mode is on — no "
                         "comment generated.")

        if action in ("confirm", "confirm_action"):
            result = engine.confirm_high_impact(
                action=params.get("action", ""),
                description=params.get("description", ""),
                prompt=params.get("prompt", ""),
                timeout=_float(params.get("timeout"), 60.0))
            if result == "confirm":
                return "Confirmed — the action was approved."
            if result == "takeover":
                return _finish(engine.user_takeover())
            return ("Confirmation was not given, so the action was NOT "
                    "performed.")

        return ("Unknown agent_control action: '" + action + "'. Valid: status, "
                "take_control, release, pause, resume, stop, takeover, apps, "
                "active_app, inspect, elements, find, click, double_click, "
                "right_click, type, press, hotkey, scroll, drag, move, select, "
                "copy, paste, switch_window, switch_tab, open_app, wait, verify, "
                "history, history_clear, humour, confirm.")

    except ControlStopped:
        return ("Automation stopped immediately (ESC / STOP pressed) — queued "
                "actions were cancelled and control was released.")
    except Exception as e:
        print(f"[AgentControl] ERROR {action}: {e}")
        return f"agent_control '{action}' failed: {e}"


def _with_confirm(engine: AppControlEngine, params: dict, action: str,
                  fn) -> str:
    """Gate high-impact interactions behind user confirmation."""
    description = params.get("description", "")
    if engine.gate.needs_confirmation(action, description):
        result = engine.confirm_high_impact(
            action=action, description=description,
            prompt=(f"Keys.ai is ready to {action}"
                    + (f" '{description}'" if description else "")
                    + ". Confirm to continue."),
            timeout=_float(params.get("confirm_timeout"), 60.0))
        if result == "takeover":
            return _finish(engine.user_takeover())
        if result != "confirm":
            return ("Cancelled — I did NOT perform the action since you "
                    "didn't confirm it. Say 'confirm' or ask again to proceed.")
    return _finish(fn())


def agent_settings(parameters: dict, player=None, speak=None) -> str:
    params = _params(parameters)
    action = (params.get("action") or "get").strip().lower()
    settings = get_settings()

    if action in ("get", "show", "status", "view"):
        return settings_summary(settings)

    if action in ("set", "update", "change", "configure"):
        applied, rejected = [], []
        mapping = {
            "humour_level": params.get("humour_level"),
            "dark_humour": params.get("dark_humour"),
            "professional_mode": params.get("professional_mode"),
            "retry_limit": params.get("retry_limit"),
            "confirm_high_impact": params.get("confirm_high_impact"),
            "overlay_enabled": params.get("overlay_enabled"),
            "max_wait_timeout": params.get("max_wait_timeout"),
        }
        for key, value in mapping.items():
            if value is None:
                continue
            if settings.set(key, value):
                applied.append(f"{key}={value}")
            else:
                rejected.append(f"{key}={value}")
        if not applied and not rejected:
            return ("Provide at least one setting: humour_level (OFF|LOW|MEDIUM|"
                    "HIGH), dark_humour, professional_mode, retry_limit, "
                    "confirm_high_impact, overlay_enabled, max_wait_timeout.")
        msg = "Settings updated: " + ", ".join(applied) if applied else "No settings changed."
        if rejected:
            msg += " Rejected (invalid values): " + ", ".join(rejected)
        return msg + "\nNow: " + settings_summary(settings)

    if action in ("reset", "defaults", "default"):
        for key, value in {
            "humour_level": "MEDIUM", "dark_humour": False,
            "professional_mode": False, "retry_limit": 3,
            "confirm_high_impact": True, "overlay_enabled": True,
            "max_wait_timeout": 30.0,
        }.items():
            settings.set(key, value)
        return "Settings reset to defaults.\n" + settings_summary(settings)

    return f"Unknown agent_settings action '{action}'. Valid: get, set, reset."
