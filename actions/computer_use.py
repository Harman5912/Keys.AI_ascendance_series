"""
computer_use — the Keys.ai computer-use engine tool.

Exposes the deep Windows computer-use capabilities to Gemini while keeping the
cheapest-reliable-method hierarchy INSIDE the engine:

    state            — cheap current desktop state (active app, cursor, motion)
    changed          — did anything relevant change since the last observation?
    discover         — enumerate running applications (HWND/PID/process)
    app_info         — full metadata about one app/window (incl. privilege)
    active_app       — the currently focused application
    window           — focus | minimize | maximize | restore | close | move |
                       resize (by app name or HWND)
    find / click / type — element-level, UIA-first, with verification
    drag             — source -> target with re-acquisition before release
    move             — smooth mouse trajectory
    scroll           — wheel scroll at a position / element
    wait             — state-based wait (window/element/process states)
    wait_stable      — wait until an animated region settles, then interact
    motion           — cheap local motion detection (frame differencing)
    context          — maintained world state ("I am in VS Code", ...)
    set_context      — record a world-state fact
    adapter          — vscode | terminal | explorer deep operations
    elevation        — privilege state of Keys.ai
    elevate          — request admin mode via UAC (legitimate elevation)
    telemetry        — debug/performance records for the last actions
"""

from automation import get_engine


def _params(parameters: dict | None) -> dict:
    return parameters or {}


def _xy(value) -> tuple | None:
    if value in (None, ""):
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return (int(value[0]), int(value[1]))
    s = str(value).replace("(", "").replace(")", "").replace(",", " ").split()
    if len(s) >= 2:
        try:
            return (int(s[0]), int(s[1]))
        except Exception:
            return None
    return None


def _int(value, default=0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def computer_use(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = _params(parameters)
    action = (params.get("action") or "").strip().lower()

    def log(msg: str) -> None:
        print(f"[ComputerUse] {msg}")
        if player is not None and hasattr(player, "write_log"):
            try:
                player.write_log(f"SYS: {msg[:150]}")
            except Exception:
                pass

    engine = get_engine(log=log)

    if not action:
        return "No action specified for computer_use."

    try:
        # ── state & change detection (spec 20-21) ─────────────────────────
        if action in ("state", "observe", "screen_state"):
            return engine.observe().as_str()

        if action in ("changed", "change", "did_screen_change"):
            return engine.changed().as_str()

        # ── application discovery (spec 5) ────────────────────────────────
        if action in ("discover", "apps", "list_apps", "applications"):
            return engine.discover(limit=_int(params.get("limit"), 60)).as_str()

        if action in ("app_info", "app", "appinfo"):
            return engine.app_info(params.get("target", params.get("name", ""))).as_str()

        if action in ("active_app", "active", "foreground"):
            return engine.active_app().as_str()

        # ── window manager (spec 6) ───────────────────────────────────────
        if action in ("window", "window_op"):
            return engine.window_op(
                params.get("target", ""),
                params.get("op", "focus"),
                x=_int(params.get("x")),
                y=_int(params.get("y")),
                width=_int(params.get("width")),
                height=_int(params.get("height")),
            ).as_str()

        # ── element interaction (spec 4, 27) ──────────────────────────────
        if action in ("find", "locate"):
            return engine.find(params.get("description", ""),
                               params.get("window", "")).as_str()

        if action in ("click", "click_element"):
            xy = _xy(params.get("xy"))
            return engine.click(
                description=params.get("description", ""),
                window=params.get("window", ""),
                x=xy[0] if xy else _int(params.get("x"), None) if params.get("x") is not None else None,
                y=xy[1] if xy else _int(params.get("y"), None) if params.get("y") is not None else None,
                button=params.get("button", "left"),
                verify_screen=bool(params.get("verify", False)),
            ).as_str()

        if action in ("type", "type_text"):
            xy = _xy(params.get("xy"))
            return engine.type(
                params.get("text", ""),
                description=params.get("description", ""),
                window=params.get("window", ""),
                x=xy[0] if xy else None,
                y=xy[1] if xy else None,
            ).as_str()

        # ── trajectory / drag / scroll (spec 15-19) ──────────────────────
        if action in ("drag", "drag_element"):
            return engine.drag(
                src_desc=params.get("source_description", params.get("src", "")),
                dst_desc=params.get("target_description", params.get("dst", "")),
                src_xy=_xy(params.get("source_xy", params.get("from_xy"))),
                dst_xy=_xy(params.get("target_xy", params.get("to_xy"))),
                window=params.get("window", ""),
            ).as_str()

        if action in ("move", "move_smooth", "mouse_move"):
            xy = _xy(params.get("xy"))
            x = xy[0] if xy else _int(params.get("x"), 0)
            y = xy[1] if xy else _int(params.get("y"), 0)
            return engine.move_smooth(x, y).as_str()

        if action in ("scroll", "scroll_to"):
            return engine.scroll_to(
                target=params.get("target", ""),
                window=params.get("window", ""),
                direction=params.get("direction", "down"),
                amount=_int(params.get("amount"), 3),
            ).as_str()

        # ── temporal / state-based waiting (spec 8, 24) ───────────────────
        if action in ("wait", "wait_for"):
            return engine.wait_for(params.get("kind", "open"),
                                   params.get("target", ""),
                                   timeout=float(params.get("timeout", 10))).as_str()

        if action in ("wait_stable", "wait_settle"):
            region = _xy(params.get("region"))
            if region is None and params.get("region"):
                parts = str(params.get("region")).replace(",", " ").split()
                if len(parts) == 4:
                    try:
                        region = tuple(int(p) for p in parts)
                    except Exception:
                        region = None
            return engine.wait_stable(region, timeout=float(params.get("timeout", 6))).as_str()

        if action in ("motion", "motion_analysis", "motion_regions"):
            return engine.motion_analysis().as_str()

        # ── world state (spec 26) ─────────────────────────────────────────
        if action in ("context", "world_state", "memory_state"):
            return engine.context().as_str()

        if action in ("set_context", "remember"):
            return engine.set_context(params.get("key", ""), params.get("value", "")).as_str()

        # ── app adapters (spec 7-9) ───────────────────────────────────────
        if action in ("adapter", "vscode", "terminal", "explorer"):
            app = params.get("app", "")
            if action in ("vscode", "terminal", "explorer"):
                app = action
            return engine.adapter_op(
                app=app or params.get("target", ""),
                op=params.get("op", ""),
                path=params.get("path", ""),
                text=params.get("text", ""),
                command=params.get("command", ""),
                timeout=float(params.get("timeout", 10)),
            ).as_str()

        # ── elevation / observability (spec 10-11, 44-45) ─────────────────
        if action in ("elevation", "privilege", "admin_status"):
            return engine.elevation().as_str()

        if action in ("elevate", "run_as_admin", "request_admin"):
            return engine.elevate().as_str()

        if action in ("telemetry", "debug", "trace"):
            return engine.telemetry_dump(limit=_int(params.get("limit"), 20)).as_str()

        return (
            "Unknown computer_use action: '" + action + "'. Valid: state, changed, "
            "discover, app_info, active_app, window, find, click, type, drag, move, "
            "scroll, wait, wait_stable, motion, context, set_context, adapter, "
            "elevation, elevate, telemetry."
        )

    except Exception as e:
        print(f"[ComputerUse] ERROR {action}: {e}")
        return f"computer_use '{action}' failed: {e}"
