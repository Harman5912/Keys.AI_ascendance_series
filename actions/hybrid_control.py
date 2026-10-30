"""
hybrid_control — tool wrapper around the hybrid automation controller.

Routes every desktop action through the priority chain:
  1. Windows UI Automation (pywinauto)   2. Native APIs (Playwright/CDP)
  3. Computer Vision + OCR                4. Mouse/Keyboard (pyautogui)

actions:
  status          — list backends and their availability
  windows         — list open top-level windows
  focus           — bring a window to the foreground (title)
  find            — locate an element and report where it is
  click           — click an element (by description) or at x/y
  type            — type text into an element / at coordinates / focused field
  hotkey          — press a key combination, e.g. 'ctrl+c'
  scroll          — scroll the mouse wheel (direction, amount)
  describe_screen — capture + AI vision/OCR summary of what's on screen
  ocr             — extract text from the screen
  screenshot      — save a screenshot to disk
  elements        — list every interactive component (buttons, fields, menus) of a
                    window; each gets an index for direct click/type/read access
  read            — read the text/value of an element (by description)
  view            — capture the screen to an image file and return its path
"""

from automation import get_controller


def _params(parameters: dict | None) -> dict:
    return parameters or {}


def hybrid_control(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = _params(parameters)
    action = (params.get("action") or "").strip().lower()

    def log(msg: str) -> None:
        print(f"[HybridControl] {msg}")
        if player is not None and hasattr(player, "write_log"):
            try:
                player.write_log(f"SYS: {msg[:150]}")
            except Exception:
                pass

    controller = get_controller(log=log)

    if not action:
        return "No action specified for hybrid_control."

    try:
        if action == "status":
            return controller.status().as_str()

        if action in ("windows", "list_windows"):
            return controller.list_windows().as_str()

        if action in ("focus", "focus_window"):
            return controller.focus_window(params.get("title", "")).as_str()

        if action in ("find", "find_element"):
            return controller.find(
                params.get("description", ""),
                control_type=params.get("control_type", ""),
                window_title=params.get("window", ""),
            ).as_str()

        if action in ("click", "click_element"):
            return controller.click(
                params.get("description", ""),
                control_type=params.get("control_type", ""),
                window_title=params.get("window", ""),
                x=_opt_int(params.get("x")),
                y=_opt_int(params.get("y")),
            ).as_str()

        if action in ("type", "type_text"):
            return controller.type_text(
                params.get("text", ""),
                description=params.get("description", ""),
                control_type=params.get("control_type", ""),
                window_title=params.get("window", ""),
                x=_opt_int(params.get("x")),
                y=_opt_int(params.get("y")),
            ).as_str()

        if action in ("hotkey", "keys"):
            return controller.hotkey(params.get("keys", "")).as_str()

        if action in ("scroll",):
            return controller.scroll(
                params.get("direction", "down"),
                int(params.get("amount", 3) or 3),
            ).as_str()

        if action in ("describe", "describe_screen", "what_on_screen"):
            return controller.describe_screen().as_str()

        if action in ("ocr", "read_screen"):
            return controller.ocr().as_str()

        if action in ("screenshot", "capture", "view", "capture_screen"):
            return _save_screenshot(controller, params.get("path"))

        if action in ("elements", "components", "list_elements"):
            return controller.list_elements(params.get("window", "")).as_str()

        if action in ("read", "read_element", "get_text"):
            return controller.read(
                params.get("description", ""),
                control_type=params.get("control_type", ""),
                window_title=params.get("window", ""),
            ).as_str()

        # ── computer-use engine actions (discovery / window ops / motion) ──
        from automation import get_engine
        engine = get_engine(log=log)

        if action in ("app_info", "app", "appinfo", "application"):
            return engine.app_info(params.get("target", params.get("title", ""))).as_str()

        if action in ("active_app", "active", "foreground_app"):
            return engine.active_app().as_str()

        if action in ("windows_detail", "windows_full", "all_windows"):
            return engine.discover(limit=int(params.get("limit", 60) or 60)).as_str()

        if action in ("window_op", "window_control"):
            return engine.window_op(
                params.get("target", params.get("title", "")),
                params.get("op", "focus"),
                x=int(params.get("x", 0) or 0),
                y=int(params.get("y", 0) or 0),
                width=int(params.get("width", 0) or 0),
                height=int(params.get("height", 0) or 0),
            ).as_str()

        if action in ("drag", "drag_element"):
            return engine.drag(
                src_desc=params.get("source_description", params.get("src", "")),
                dst_desc=params.get("target_description", params.get("dst", "")),
                src_xy=_opt_xy(params.get("source_xy", params.get("from_xy"))),
                dst_xy=_opt_xy(params.get("target_xy", params.get("to_xy"))),
                window=params.get("window", ""),
            ).as_str()

        if action in ("move", "move_smooth", "smooth_move"):
            return engine.move_smooth(
                int(params.get("x", 0) or 0), int(params.get("y", 0) or 0)).as_str()

        if action in ("verify", "verify_action"):
            return engine.wait_for(
                params.get("kind", "element"),
                params.get("target", ""),
                timeout=float(params.get("timeout", 10) or 10),
            ).as_str()

        if action in ("wait", "wait_until"):
            return engine.wait_for(
                params.get("kind", "open"),
                params.get("target", ""),
                timeout=float(params.get("timeout", 10) or 10),
            ).as_str()

        if action in ("state", "screen_state", "observe"):
            return engine.observe().as_str()

        if action in ("changed", "change"):
            return engine.changed().as_str()

        if action in ("context", "world_state"):
            return engine.context().as_str()

        if action in ("elevation", "privilege", "admin"):
            return engine.elevation().as_str()

        if action in ("telemetry", "debug"):
            return engine.telemetry_dump(limit=int(params.get("limit", 20) or 20)).as_str()

        return (
            f"Unknown hybrid_control action: '{action}'. Valid: status, windows, "
            "focus, find, click, type, hotkey, scroll, describe_screen, ocr, screenshot, "
            "elements, read, view, app_info, active_app, windows_detail, window_op, "
            "drag, move, verify, wait, state, changed, context, elevation, telemetry."
        )

    except Exception as e:
        print(f"[HybridControl] ❌ {action}: {e}")
        return f"hybrid_control '{action}' failed: {e}"


def _opt_int(v):
    if v in (None, "", "None"):
        return None
    try:
        return int(v)
    except Exception:
        return None


def _opt_xy(v):
    """Parse "x,y" (or [x, y]) into a tuple, else None."""
    if v in (None, "", "None"):
        return None
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        try:
            return (int(v[0]), int(v[1]))
        except Exception:
            return None
    parts = str(v).replace("(", "").replace(")", "").replace(",", " ").split()
    if len(parts) >= 2:
        try:
            return (int(parts[0]), int(parts[1]))
        except Exception:
            return None
    return None


def _save_screenshot(controller, save_path=None) -> str:
    img = controller.capture()
    if img is None:
        return "Could not capture the screen."
    try:
        from pathlib import Path
        path = Path(save_path).expanduser() if save_path else Path.home() / "Desktop" / "keysai_screen.png"
        if not path.suffix:
            path = path.with_suffix(".png")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(img)
        return f"Screenshot saved: {path}"
    except Exception as e:
        return f"Could not save screenshot: {e}"
