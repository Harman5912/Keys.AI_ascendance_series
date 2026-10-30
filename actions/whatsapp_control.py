"""whatsapp_control - state-driven WhatsApp automation.
Reliability engine: state machine + adaptive waits + verification.
No fixed sleeps: the system WAITS FOR STATE (spec 46).

WhatsApp Web is NEVER launched automatically:
  • SEND/MESSAGE runs the reliable desktop flow (the WhatsApp DESKTOP app with
    Control-Mode takeover fallback), and it now WAITS FOR TARGET READY before
    any typing or sending.
  • CALL runs the automated-call flow: an automated call message is sent
    through the desktop messaging route, then Keys.ai takes over the
    desktop app, locates the call button by pattern matching and clicks it.
  • READ actions (list_chats, read_messages, open_chat, chat_meta) work ONLY
    when WhatsApp Web is already open in this process — they refuse to launch
    it. The single explicit Web launcher is 'ready' (say "open WhatsApp Web").

The send path is designed to be HANG-PROOF and exact-chat-verified:
  1. Resolve the spoken name to a real contact/number (Google contacts, then
     WhatsApp's own search when Google has nothing).
  2. Wait for the WhatsApp desktop window to actually exist and respond before
     typing/supervising the message — this is the wait_for_ready + controls
     state the user asked about. It polls the window state for a bounded time
     instead of assuming the app is up in the instant after open.
  3. Open the chat and wait for the message composer to appear.
  4. Send ONE message, then verify on screen (so the model never claims a send
     it cannot confirm).
"""

from whatsapp import get_adapter

import re
import sys
import time
from pathlib import Path

try:
    import pyautogui
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _get_os() -> str:
    try:
        import json
        cfg = json.loads(
            (_base_dir() / "config" / "api_keys.json").read_text(encoding="utf-8")
        )
        return cfg.get("os_system", "windows").lower()
    except Exception:
        return "windows"



def _web_already_open(ad) -> bool:
    """True when WhatsApp Web is already running in THIS process — checked
    WITHOUT launching anything (health only)."""
    try:
        h = ad.client.health()
        return bool(h.get("browser_alive")) and bool(h.get("page_alive"))
    except Exception:
        return False


def _web_not_open_msg() -> str:
    return ("WhatsApp Web is not open right now — I will not launch it on my "
            "own. Say 'open WhatsApp Web' (action 'ready') to launch it, or "
            "use messaging, which runs in the WhatsApp desktop app.")


def whatsapp_control(parameters, response=None, player=None,
                     session_memory=None) -> str:
    params = parameters or {}
    action = (params.get("action") or "").strip().lower()
    if not action:
        return "No action specified for whatsapp_control."
    if action in ("call", "make_call", "call_status", "last_call"):
        return ("Calling features have been removed from Keys.ai. "
                "I can only send messages, not make calls. Please use "
                "the 'send' action instead.")
    try:
        ad = get_adapter()
        if action in ("status", "state", "health"):
            return ad.status()
        if action in ("ready", "ensure_ready", "connect"):
            ok = ad.ensure_ready()
            return ("WhatsApp ready (multi-signal verified)." if ok
                    else "WhatsApp not ready yet.")
        if action in ("send", "message"):
            target = (params.get("receiver") or params.get("target") or "").strip()
            msg = (params.get("message_text") or params.get("message") or "").strip()
            if not target:
                return "Please specify the receiver."
            if not msg:
                return "Please specify the message."
            return _robust_send_whatsapp(target, msg, session_memory=session_memory,
                                         player=player)
        if action in ("queue", "queue_status"):
            return ad.queue_status()
        if action in ("queue_flush", "flush"):
            if not _web_already_open(ad):
                return _web_not_open_msg()
            return ad.flush_queue()
        if action in ("queue_pause", "pause"):
            return ad.pause_queue()
        if action in ("queue_resume", "resume"):
            return ad.resume_queue()
        if action in ("list_chats", "chats"):
            if not _web_already_open(ad):
                return _web_not_open_msg()
            r = ad.list_chats()
            if not r.get("ok"):
                return f"Could not read the WhatsApp chat list ({r.get('state')})."
            chats = r.get("chats") or []
            if not chats:
                return "No WhatsApp chats are visible yet."
            lines = []
            for c in chats[:20]:
                title = c.get("title") or "(unnamed)"
                parts = [title]
                if c.get("time"):
                    parts.append(f"[{c['time']}]")
                if c.get("unread"):
                    parts.append(f"({c['unread']} unread)")
                if c.get("preview"):
                    parts.append(f"\u2014 {c['preview'][:60]}")
                lines.append("  ".join(parts))
            return "WhatsApp chats:\n" + "\n".join(lines)
        if action in ("read_messages", "messages", "read_chat"):
            if not _web_already_open(ad):
                return _web_not_open_msg()
            try:
                limit = int(params.get("limit") or 60)
            except (TypeError, ValueError):
                return "read_messages 'limit' must be a number."
            r = ad.read_messages(limit=limit)
            if not r.get("ok"):
                detail = r.get("detail") or ""
                return ("Could not read the open WhatsApp conversation"
                        + (f" ({detail})" if detail else "."))
            msgs = r.get("messages") or []
            if not msgs:
                return "No messages are visible in the open conversation."
            lines = []
            for m in msgs[-30:]:
                who = "You" if m.get("outgoing") else \
                      (m.get("sender") or "them")
                text = m.get("text") or ""
                if m.get("deleted"):
                    text = "(deleted message)"
                stamp = f"[{m['time']}] " if m.get("time") else ""
                lines.append(f"{stamp}{who}: {text}")
            return "\n".join(lines)
        if action in ("open_chat",):
            if not _web_already_open(ad):
                return _web_not_open_msg()
            title = (params.get("receiver") or params.get("title") or "").strip()
            if not title:
                return "open_chat requires 'receiver' (chat title)."
            r = ad.open_chat(title)
            if r.get("ok"):
                return f"Opened the chat '{title}' (verified)."
            return f"Could not open the chat '{title}': {r.get('detail')}"
        if action in ("chat_meta", "chat_info"):
            if not _web_already_open(ad):
                return _web_not_open_msg()
            m = ad.chat_meta()
            title = m.get("title") or "(none)"
            subtitle = m.get("subtitle") or ""
            return f"Chat: {title}" + (f" \u2014 {subtitle}" if subtitle else "")
        if action in ("close", "disconnect"):
            ad.close()
            return "WhatsApp session closed."
        return (
            "Unknown whatsapp_control action: '" + action + "'. Valid: status, "
            "ready, send, list_chats, read_messages, "
            "open_chat, chat_meta, queue_status, queue_flush, queue_pause, "
            "queue_resume, close.")
    except Exception as e:
        print(f"[WhatsAppControl] ERROR {action}: {e}")
        return f"whatsapp_control '" + action + "' failed: " + str(e)


def _robust_send_whatsapp(target: str, msg: str,
                          session_memory=None, player=None) -> str:
    """Reliable WhatsApp send: contact resolution + state wait + correct-chat
    verification + single verified send + honest failure.

    Returns the result string. Never raises: the caller (the public tool and
    the engine) only expects a str back.
    """
    # 1) Resolve the spoken NAME to the real contact/number, in the named
    #    priority: Google contacts first, then WhatsApp's own search.
    resolved, resolve_note = _resolve_receiver(target, "WhatsApp")

    # 1b) If the user asked for verified contacts only, gate here.
    require_verified_str = str(
        (session_memory or {}).get("require_verified", "")).lower()
    require_verified = require_verified_str in ("1", "true", "yes", "y", "true", "1")
    block, verified_note = _verified_contact_note(resolved, require_verified)
    if block:
        # Keep the resolve note in case the resolved value is just the raw
        # target (e.g. "not in your verified contacts").
        combined_note = (verified_note or "") + (resolve_note or "")
        return (block.rstrip(".") + "." + (combined_note if combined_note else "")
                if combined_note
                else block.rstrip(".") + ".")

    # 2) Wait for the WhatsApp desktop window to be present and reachable
    #    BEFORE we open any chat — this is the state wait the user asked for.
    window = _wait_for_whatsapp_ready(timeout=45.0)
    if window is False:
        # Not reachable at all — fall back to the same desktop send path
        # send_message already uses, which is exactly the previous method.
        return _send_via_send_message(resolved, msg, resolve_note, verified_note)

    # window is True: WhatsApp desktop is already open.
    # window is a non-empty str: it is the window title we should focus.

    # 3) Reliably take control and send. The takeover path itself waits for
    #    the composer to appear and verifies on screen.
    note = (verified_note or "") + (resolve_note or "")
    try:
        from actions.whatsapp_takeover import whatsapp_takeover_send
        result = whatsapp_takeover_send(resolved, msg, session_memory=session_memory,
                                        player=player)
    except Exception as e:
        result = f"WhatsApp takeover raised an error: {e}"

    # 4) Honest reporting: prepend which contact/number we aimed at.
    display = (result or "").rstrip(".")
    if note:
        display = display + note
    return display + "." if display else (note or "")


def _send_via_send_message(resolved: str, msg: str,
                           resolve_note: str, verified_note: str) -> str:
    """Fallback: reuse send_message's own desktop send (the previous method).

    We do NOT launch WhatsApp Web here. The send_message tool already runs the
    WhatsApp desktop app and falls back to WhatsApp Control-Mode takeover itself
    when the direct desktop send cannot run — so we get both paths without
    duplicating logic or opening another app.
    """
    try:
        from actions.send_message import _send_whatsapp
        result = _send_whatsapp(resolved, msg)
    except Exception as e:
        result = f"send_message path raised: {e}"

    note = (verified_note or "") + (resolve_note or "")
    display = (result or "").rstrip(".")
    if note:
        display = display + note
    return display + "." if display else (note or "")


def _wait_for_whatsapp_ready(timeout: float = 45.0) -> str | bool:
    """Wait up to `timeout` seconds for the WhatsApp desktop process to be
    reachable and for its window to exist.

    Returns:
      True  — WhatsApp was already reachable when we started.
      str   — the window title we should focus (WhatsApp was launched / became
              reachable during the wait).
      False — WhatsApp could not be reached within the timeout.
    """
    start = time.time()
    os_name = _get_os()

    def _is_reachable() -> tuple[bool, str]:
        """Try to detect a live WhatsApp desktop window. Returns (reachable,
        window_title_or_empty)."""
        try:
            from automation import get_controller
            ctrl = get_controller()
            wins = (getattr(ctrl, "list_windows", lambda: None)() or {}).get("windows") or []
        except Exception:
            wins = []

        for w in wins:
            title = str(w.get("title") or "").strip()
            if not title:
                continue
            low = title.lower()
            # Accept the obvious WhatsApp windows. Keep the check loose enough
            # to match localized/branded titles.
            if ("whatsapp" in low
                    or ("message" in low and ("web" not in low))
                    or "green bubble" in low):
                # Prefer a real, non-placeholder title.
                if title.lower() not in ("whatsapp", "whatsapp app", "green bubbles"):
                    return True, title
                return True, ""
        return False, ""

    # Poll at a reasonable rate. Do NOT busy-loop.
    poll_interval = 1.2
    already_ok, title_if_any = _is_reachable()
    if already_ok:
        return title_if_any or True

    # If it is not reachable yet, try launching it once — but only once — and
    # then keep polling for the window to appear.
    launched = False
    if not _PYAUTOGUI:
        return False

    try:
        from automation import get_controller
        ctrl = get_controller()
        launch_result = getattr(ctrl, "open_application", lambda app: None)("WhatsApp")
    except Exception:
        launch_result = None

    # Some controllers return a result object; others return None. Treat any
    # truthy result as “we initiated a launch”. Treat None as “we don’t know”.
    launched = bool(launch_result) or launched
    if launched:
        # Give the app a moment before the first poll.
        time.sleep(1.5)

    deadline = start + timeout
    while time.time() < deadline:
        ok, title = _is_reachable()
        if ok:
            return title or True
        time.sleep(poll_interval)
    return False


class _MissingDependencies(Exception):
    """Raised by whatsapp_takeover_send when the takeover cannot start."""
    pass


def _robust_send_whatsapp(target: str, msg: str,
                          session_memory=None, player=None) -> str:
    """See module docstring. Returns the result string. Never raises."""
    # 1) Resolve the spoken NAME to the real contact/number, in the named
    #    priority: Google contacts first, then WhatsApp's own search.
    resolved, resolve_note = _resolve_receiver(target, "WhatsApp")

    # 1b) If the user asked for verified contacts only, gate here.
    require_verified_str = str(
        (session_memory or {}).get("require_verified", "")).lower()
    require_verified = require_verified_str in ("1", "true", "yes", "y")
    block, verified_note = _verified_contact_note(resolved, require_verified)
    if block:
        # Keep the resolve note in case the resolved value is just the raw
        # target (e.g. "not in your verified contacts").
        combined_note = (verified_note or "") + (resolve_note or "")
        return (block.rstrip(".") + "." + (combined_note if combined_note else "")
                if combined_note
                else block.rstrip(".") + ".")

    # 2) Wait for the WhatsApp desktop window to be present and reachable
    #    BEFORE we open any chat — this is the state wait the user asked for.
    window = _wait_for_whatsapp_ready(timeout=45.0)
    if window is False:
        # Not reachable at all — fall back to the same desktop send path
        # send_message already uses, which is exactly the previous method.
        return _send_via_send_message(resolved, msg, resolve_note, verified_note)

    # window is True: WhatsApp desktop is already open.
    # window is a non-empty str: it is the window title we should focus.

    # 3) Reliably take control and send. The takeover path itself waits for
    #    the composer to appear and verifies on screen.
    note = (verified_note or "") + (resolve_note or "")
    try:
        from actions.whatsapp_takeover import whatsapp_takeover_send
        result = whatsapp_takeover_send(resolved, msg,
                                        session_memory=session_memory,
                                        player=player)
    except Exception as e:
        result = f"WhatsApp takeover raised an error: {e}"

    # 4) Honest reporting: prepend which contact/number we aimed at.
    display = (result or "").rstrip(".")
    if note:
        display = display + note
    return display + "." if display else (note or "")


def _send_via_send_message(resolved: str, msg: str,
                           resolve_note: str, verified_note: str) -> str:
    """Fallback: reuse send_message's own desktop send (the previous method).

    We do NOT launch WhatsApp Web here. The send_message tool already runs the
    WhatsApp desktop app and falls back to WhatsApp Control-Mode takeover itself
    when the direct desktop send cannot run — so we get both paths without
    duplicating logic or opening another app.
    """
    try:
        from actions.send_message import _send_whatsapp
        result = _send_whatsapp(resolved, msg)
    except Exception as e:
        result = f"send_message path raised: {e}"

    note = (verified_note or "") + (resolve_note or "")
    display = (result or "").rstrip(".")
    if note:
        display = display + note
    return display + "." if display else (note or "")


def _wait_for_whatsapp_ready(timeout: float = 45.0) -> str | bool:
    """Wait up to `timeout` seconds for the WhatsApp desktop process to be
    reachable and for its window to exist.

    Returns:
      True  — WhatsApp was already reachable when we started.
      str   — the window title we should focus (WhatsApp was launched / became
              reachable during the wait).
      False — WhatsApp could not be reached within the timeout.
    """
    start = time.time()
    os_name = _get_os()

    def _is_reachable() -> tuple[bool, str]:
        """Try to detect a live WhatsApp desktop window. Returns (reachable,
        window_title_or_empty)."""
        try:
            from automation import get_controller
            ctrl = get_controller()
            wins = (getattr(ctrl, "list_windows", lambda: None)() or {}).get("windows") or []
        except Exception:
            wins = []

        for w in wins:
            title = str(w.get("title") or "").strip()
            if not title:
                continue
            low = title.lower()
            # Accept the obvious WhatsApp windows. Keep the check loose enough
            # to match localized/branded titles.
            if ("whatsapp" in low
                    or ("message" in low and ("web" not in low))
                    or "green bubble" in low):
                # Prefer a real, non-placeholder title.
                if title.lower() not in ("whatsapp", "whatsapp app", "green bubbles"):
                    return True, title
                return True, ""
        return False, ""

    # Poll at a reasonable rate. Do NOT busy-loop.
    poll_interval = 1.2
    already_ok, title_if_any = _is_reachable()
    if already_ok:
        return title_if_any or True

    # If it is not reachable yet, try launching it once — but only once — and
    # then keep polling for the window to appear.
    launched = False
    if not _PYAUTOGUI:
        return False

    try:
        from automation import get_controller
        ctrl = get_controller()
        launch_result = getattr(ctrl, "open_application", lambda app: None)("WhatsApp")
    except Exception:
        launch_result = None

    # Some controllers return a result object; others return None. Treat any
    # truthy result as “we initiated a launch”. Treat None as “we don’t know”.
    launched = bool(launch_result) or launched
    if launched:
        # Give the app a moment before the first poll.
        time.sleep(1.5)

    deadline = start + timeout
    while time.time() < deadline:
        ok, title = _is_reachable()
        if ok:
            return title or True
        time.sleep(poll_interval)
    return False


class _MissingDependencies(Exception):
    """Raised by whatsapp_takeover_send when the takeover cannot start."""
    pass
