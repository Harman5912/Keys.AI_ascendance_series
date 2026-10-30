"""WhatsApp Control-Mode takeover — drive the WhatsApp app like any other app.

When the user asks to message or call on WhatsApp, Keys.ai takes VISIBLE
control of the WhatsApp window (animated gold border + watermark, exactly like
VS Code or Chrome in Agent Control Mode) and drives it through the hybrid
automation stack — UI Automation first, then Gemini vision, then OCR — so the
right control is always found. Never blind coordinates.

Flow (SEE → UNDERSTAND → ACT → VERIFY):

    ensure WhatsApp open → take_control (gold border) → open the chat
    → find the control (UIA → one-shot scene vision → OCR) → ACT ONCE via the
    missile targeting animation (a small square border flies onto the element
    and the mouse homes in) → verify on screen → release control.

Screen control here is built around TWO ideas:

  • ONE screenshot per situation, not one per step. The takeover keeps a
    cached “scene” — a single screenshot analysed once for every element it
    needs — and reuses it until the screen demonstrably changes. The search
    box, the contact row and the call button are no longer each re-photo-
    graphed over and over on every frame.

  • Missile coordinate selection. Every click runs through
    `_target_and_click`: a small square TARGET border launches from the
    previous selection and homes onto the element, then the real mouse glides
    along the same arc and clicks the centre. The whole overtake feels the
    same from start to finish.

Each public function returns None when WhatsApp itself cannot be reached (not
open and not launchable) — callers report the honest failure and NEVER fall
back to WhatsApp Web (messaging and calling are desktop-app only). Any other
return value is the honest result of the takeover attempt.

HANG-PROOFING: every potentially-blocking call (UI Automation traversal on the
WhatsApp UWP tree — pywinauto can block forever inside a UWP element handle —
and Gemini vision calls) runs inside `_bounded`, a daemon-thread timeout, so a
stuck backend can never freeze the takeover. It skips to the next approach and
reports honestly instead.
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional


class WhatsAppUnavailable(Exception):
    """WhatsApp itself could not be opened/controlled — callers fall back."""


def _bounded(fn: Callable[[], object], timeout: float = 10.0,
             default=None):
    """Run fn in a daemon thread and wait up to `timeout` seconds.

    Returns `default` when fn does not finish in time (or raise its error
    when it fails fast). Guards against hangs in pywinauto UIA traversal on
    the WhatsApp UWP tree and in Gemini API calls, which have no built-in
    timeouts.
    """
    box: dict = {}

    def _run():
        try:
            box["res"] = fn()
        except Exception as e:          # noqa: BLE001 — surfaced via box
            box["err"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        return default
    if "err" in box:
        raise box["err"]
    return box.get("res", default)


def _engine(player=None):
    from agent_control.app_control import get_control_engine
    return get_control_engine(player=player)


def _log(msg: str, player=None) -> None:
    print(f"[WhatsAppTakeover] {msg}")
    if player is not None and hasattr(player, "write_log"):
        try:
            player.write_log(f"SYS: {msg[:150]}")
        except Exception:
            pass


# ── call-trace screenshots REMOVED — calling features disabled ────────


# ── OpenCV 'graph pattern' locator REMOVED — calling features disabled ─


# ── missile targeting (shared by every click of the takeover) ──────────
_TARGET_SECONDS = 0.6     # reticle glide / homing-mouse duration per click
_TARGETER = None


def _targeter():
    """Shared Targeter so every click of a takeover glides from the previous
    selection — the reticle flies SEARCH box → CONTACT row → CALL button /
    message box without ever snapping."""
    global _TARGETER
    if _TARGETER is None:
        from automation.targeting import Targeter
        _TARGETER = Targeter()
    return _TARGETER


# ── window / control session ────────────────────────────────────────────
def _window(engine, title: str = "WhatsApp"):
    try:
        return engine.core().native().window_by_title(title)
    except Exception:
        return None


def _ensure_whatsapp(engine, player=None) -> None:
    """Open WhatsApp if needed and take visible control (gold border).

    Raises WhatsAppUnavailable when the app cannot be found or launched;
    raises Exception on other failures.
    """
    if _window(engine) is None:
        _log("WhatsApp window not found — opening the app…", player)
        try:
            r = _bounded(lambda: engine.open_application("WhatsApp"),
                         timeout=25.0)
        except Exception as e:
            raise WhatsAppUnavailable(f"could not launch WhatsApp: {e}") from e
        if r is None:
            raise WhatsAppUnavailable("opening WhatsApp timed out.")
        if not getattr(r, "ok", False):
            raise WhatsAppUnavailable(
                getattr(r, "message", "could not open WhatsApp"))
        time.sleep(3.0)
        if _window(engine) is None:
            raise WhatsAppUnavailable(
                "WhatsApp window did not appear after opening the app.")
    res = engine.take_control("WhatsApp")
    if not getattr(res, "ok", False):
        # Nothing was clicked yet and no control session exists — treat this
        # as "could not reach/control the app" so callers safely fall back to
        # the WhatsApp Web subsystem instead of failing hard.
        raise WhatsAppUnavailable(
            getattr(res, "message", "could not take control of WhatsApp"))
    # take_control does NOT focus the window, and UWP apps ignore keystrokes
    # sent to a background window — so bring WhatsApp to the foreground
    # before typing anything. (Bounded: focus is a fast native call.)
    try:
        _bounded(
            lambda: engine.core().window_op("WhatsApp", "focus", verify=False),
            timeout=8.0)
        time.sleep(0.6)
    except Exception as e:
        _log(f"could not focus WhatsApp window ({str(e)[:80]}) — continuing",
             player)
    _log("Control taken — gold border active on WhatsApp.", player)


def _release(engine) -> None:
    try:
        engine.release_control()
        _log("Control released — WhatsApp is back with you.")
    except Exception:
        pass


# ── hybrid perception (UIA → vision → OCR) ─────────────────────────────
def _rect_dict(rect) -> Optional[dict]:
    """Normalize a rect to a plain dict, whether it is a Rect object, a dict
    or a None. The real engine returns Rect objects inside element dicts;
    fakes/tests may return dicts — both must work."""
    if rect is None:
        return None
    if isinstance(rect, dict):
        return rect
    x = getattr(rect, "x", None)
    y = getattr(rect, "y", None)
    w = getattr(rect, "width", None)
    h = getattr(rect, "height", None)
    if x is None or y is None or w is None or h is None:
        return None
    return {"x": int(x), "y": int(y), "width": int(w), "height": int(h)}


def _find(engine, descriptions, window: str = "WhatsApp",
          per_timeout: float = 8.0, uia_only: bool = False) -> Optional[dict]:
    """First matching control across the hybrid chain.

    `engine.find_element` routes through the hybrid controller: UI Automation
    first, then native, then Gemini vision, then OCR text match. With
    `uia_only=True` the search stays on UI Automation — NO screenshots — so
    the keep-watching loop can re-check the screen without re-photographing
    it at every step. A rect is required — a found-but-invisible element is
    never acted on.
    """
    for desc in descriptions:
        # UIA traversal on the WhatsApp UWP tree can hang forever in
        # pywinauto — bound every find so the takeover always moves on.
        try:
            res = _bounded(
                lambda d=desc: engine.find_element(
                    d, window=window,
                    **({"uia_only": True} if uia_only else {})),
                timeout=per_timeout)
        except Exception:
            res = None
        if res is None:
            _log(f"find '{desc}' timed out / unavailable — moving on")
            continue
        if getattr(res, "ok", False):
            el = (res.data or {}).get("element") or {}
            rect = _rect_dict(el.get("rect"))
            if rect and rect.get("width") and rect.get("height"):
                return dict(el, rect=rect)
    return None


def _center(element: dict) -> Optional[tuple]:
    rect = _rect_dict((element or {}).get("rect"))
    if not rect or not rect.get("width") or not rect.get("height"):
        return None
    return (int(rect["x"] + rect["width"] / 2),
            int(rect["y"] + rect["height"] / 2))


def _click_once(engine, element: Optional[dict] = None,
                x: Optional[int] = None, y: Optional[int] = None,
                player=None) -> bool:
    """Exactly ONE physical click — never retried (a call is initiated once)."""
    if element is not None:
        pt = _center(element)
        if pt is None:
            return False
        x, y = pt
    if x is None or y is None:
        return False
    try:
        ok = bool(engine.core().motion().click(int(x), int(y)))
    except Exception as e:
        _log(f"click failed: {e}", player)
        return False
    _log(f"clicked once at ({x}, {y})", player)
    return ok


def _capture_scene(engine, wanted: dict[str, str]) -> dict[str, tuple | None]:
    """ONE screenshot + ONE vision pass locating every wanted element.

    wanted: {key: natural-language description}
    returns: {key: (x1, y1, x2, y2) or None}

    This is the “stop taking a screenshot at every step” primitive: the whole
    situation is analysed in a single shot, and the caller keeps the result
    until the screen demonstrably changes.
    """
    try:
        from actions.computer_control import _screen_find_boxes
        # Local vision (ollama llava) takes ~16-20s per look — a 16s bound
        # would cut the model off mid-analysis and the element would never
        # be found. Give the scene a generous single-look budget; UIA and
        # cv2 still answer instantly ahead of this.
        boxes = _bounded(lambda: _screen_find_boxes(wanted), timeout=45.0)
        if boxes:
            return boxes
    except Exception as e:
        _log(f"scene capture failed: {str(e)[:100]}")
    return {k: None for k in wanted}


def _target_and_click(engine, rect, player=None) -> bool:
    """THE one click path of the whole takeover: an animated missile reticle
    (small square border) launches from the last selection and locks onto the
    element, then the mouse homes in and clicks exactly once. Every step —
    search box, contact row, call button, message box — uses this, so the
    whole overtake feels the same."""
    r = _rect_dict(rect)
    # an element dict wraps its rect under .get("rect"); a plain rect dict
    # IS the rect — normalize both shapes so every caller lands here
    if isinstance(r, dict) and "rect" in r and "width" not in r:
        r = _rect_dict(r.get("rect"))
    if not r or not r.get("width") or not r.get("height"):
        return _click_once(engine, element=rect, player=player)
    x1, y1 = int(r["x"]), int(r["y"])
    x2, y2 = x1 + int(r["width"]), y1 + int(r["height"])
    tr = _targeter()
    # 0) GRID overlay: show the full-screen targeting grid and pulse the
    #    cell the mouse is heading to — the user SEES where the cursor is
    #    going before and during the move (best-effort: headless engines
    #    simply skip the grid)
    try:
        from_ = tr.launch_rect(engine.core().motion())
        engine.grid_target(from_, (x1, y1, x2, y2), seconds=_TARGET_SECONDS)
    except Exception:
        pass
    # 1) missile reticle glide — a square border flying from the last
    #    selection (or the cursor, on the first one) onto the element
    #    (best-effort: headless/test engines simply skip the animation)
    try:
        from_ = tr.launch_rect(engine.core().motion())
        engine.target_box(from_, (x1, y1, x2, y2), seconds=_TARGET_SECONDS)
    except Exception:
        pass

    def _grid_point(px: int, py: int) -> None:
        """Stream each real cursor position to the grid overlay so its
        crosshair tracks the ACTUAL mouse, not a guessed path."""
        try:
            engine.grid_point(px, py)
        except Exception:
            pass

    # 2) homing mouse approach (runs in parallel with the reticle glide —
    #    both take _TARGET_SECONDS; every cursor update streams to the grid)
    cx, cy = tr.engage(engine.core().motion(), (x1, y1, x2, y2),
                       seconds=_TARGET_SECONDS, on_move=_grid_point)
    # 3) static TARGET lock once the glide has landed — the user sees the
    #    square border settle exactly where the click is about to land
    try:
        engine.highlight_box(x1, y1, x2, y2, seconds=1.1)
    except Exception:
        pass
    # 4) the single click, then hide the grid — the move is done
    ok = _click_once(engine, x=cx, y=cy, player=player)
    try:
        engine.grid_hide()
    except Exception:
        pass
    return ok


# ── chat opening ────────────────────────────────────────────────────────
def _phone_digits(target: str) -> Optional[str]:
    """Digits-only international number when `target` looks like a phone
    number (e.g. '+1 555 123 4567', '15551234567', '555-123-4567'). Returns
    None for plain contact names — those cannot use the phone-link path."""
    t = (target or "").strip()
    if not t:
        return None
    # must consist ONLY of digits and phone separators (optional leading +)
    if not re.match(r"^\+?[\d\s().\-]{7,}$", t):
        return None
    digits = re.sub(r"\D", "", t)
    return digits if len(digits) >= 7 else None


def _launch_phone_link(uri: str) -> bool:
    """Hand a whatsapp:// URI to the OS so the installed desktop app opens
    the chat directly. Returns True when the launch was handed off."""
    try:
        if os.name == "nt":
            os.startfile(uri)
        else:
            import subprocess
            subprocess.Popen(["xdg-open", uri])
        return True
    except Exception:
        return False


def _chat_pane_open(engine) -> bool:
    """True when the WhatsApp chat pane (message composer) is on screen —
    the signal that a chat is open. UIA first (no screenshot), then ONE
    one-shot scene."""
    composer = _find(engine, ["type a message", "message", "Message",
                              "composer", "message input"], uia_only=True)
    if composer is not None:
        return True
    scene = _capture_scene(
        engine, {"composer": "the WhatsApp message input box at the bottom "
                             "of the open chat"})
    return bool((scene or {}).get("composer"))


_PHONE_LINK_WAIT_S = 2.5     # time for the app to switch to the chat
_PHONE_LINK_FOCUS_S = 0.6    # settle after re-asserting the takeover focus


def _open_chat_via_phone_link(engine, digits: str, player=None,
                              target: str = "") -> Optional[str]:
    """Last-resort chat-open: whatsapp://send?phone=<digits>.

    This is the wa.me strategy adapted to the desktop app — wa.me links open
    the BROWSER, but the Windows/macOS client registers the whatsapp:// URI
    scheme, so this deep link activates the app straight into a chat with
    that number, even when it is not saved in contacts.

    Returns None on success; an error string when the link cannot launch or
    the chat does not appear.
    """
    uri = f"whatsapp://send?phone={digits}"
    _log(f"search could not open the chat — trying the phone link {uri}",
         player)
    if not _launch_phone_link(uri):
        return (f"the phone link ({uri}) could not be launched — no handler "
                f"for whatsapp:// on this system.")
    time.sleep(_PHONE_LINK_WAIT_S)   # let the app switch to the chat
    # the deep link may have refocused the app — re-assert the takeover focus
    try:
        _bounded(
            lambda: engine.core().window_op("WhatsApp", "focus",
                                            verify=False),
            timeout=8.0)
        time.sleep(_PHONE_LINK_FOCUS_S)
    except Exception:
        pass
    # VERIFY on screen: the composer is present → the chat pane is open
    if _chat_pane_open(engine):
        _log(f"phone link opened the chat for {target or digits}", player)
        return None
    return (f"the phone link launched, but the chat with {target or digits} "
            f"did not appear.")


def _open_chat(engine, target: str, player=None) -> Optional[str]:
    """Search for the contact and open their chat. None = success.

    When the search cannot open the chat (e.g. an unsaved phone number), the
    LAST fallback is the phone deep link — whatsapp://send?phone=<number>,
    the wa.me strategy for the desktop app.
    """
    target = (target or "").strip()
    if not target:
        return "no contact name to search for."
    # Ctrl+K opens the chat search in WhatsApp Desktop AND WhatsApp Web — and
    # it avoids the UIA traversal that can hang on the WhatsApp UWP tree.
    # Only if the hotkey path fails do we fall back to a bounded search-box
    # find + click.
    hotkey_ok = False
    try:
        r = _bounded(lambda: engine.hotkey("ctrl+k"), timeout=8.0)
        hotkey_ok = r is not None and getattr(r, "ok", False)
        if hotkey_ok:
            time.sleep(0.9)
    except Exception:
        hotkey_ok = False
    if not hotkey_ok:
        box = _find(engine, ["search", "chat search", "search box"])
        if box is None:
            # one-shot scene: ONE screenshot locates the search field — no
            # per-step photography
            scene = _capture_scene(
                engine, {"search": "the WhatsApp chat search box (the search "
                                   "field or search icon in the chat list)"})
            sbox = (scene or {}).get("search")
            if sbox:
                box = {"rect": {"x": sbox[0], "y": sbox[1],
                                 "width": sbox[2] - sbox[0],
                                 "height": sbox[3] - sbox[1]}}
        if box is None:
            return "could not open the WhatsApp search (Ctrl+K and the search " \
                   "box are both unreachable)."
        # missile targeting: square border flies onto the search box, then
        # the mouse homes in and clicks
        _target_and_click(engine, box, player)
        time.sleep(0.3)
    try:
        engine.core().motion().type_text(target)
    except Exception as e:
        return f"could not type the contact name: {e}"
    time.sleep(1.0)          # let the results render
    try:
        engine.core().motion().hotkey(["enter"])
    except Exception as e:
        return f"could not select the chat: {e}"
    time.sleep(1.4)          # let the chat open

    # VERIFY the right chat actually opened (SEE->ACT->VERIFY). A wrong chat
    # here is the #1 reason the call button is "not found" afterwards.
    if _chat_open_ok(engine, target) is False:
        # one clean retry — reopen the search and select again
        _log(f"chat '{target}' did not open — retrying the search once", player)
        try:
            _bounded(lambda: engine.hotkey("esc"), timeout=4.0)
            time.sleep(0.5)
            r2 = _bounded(lambda: engine.hotkey("ctrl+k"), timeout=8.0)
            if r2 is not None and getattr(r2, "ok", False):
                time.sleep(0.9)
            engine.core().motion().type_text(target)
            time.sleep(1.0)
            engine.core().motion().hotkey(["enter"])
            time.sleep(1.4)
        except Exception as e:
            return f"could not re-open {target}'s chat: {e}"
        if _chat_open_ok(engine, target) is False:
            # last-resort fallback: when the target is a phone number, open
            # the chat through the desktop phone link (whatsapp://send?phone=
            # — the wa.me strategy for the desktop app), which works even for
            # numbers not saved in contacts.
            digits = _phone_digits(target)
            if digits:
                err = _open_chat_via_phone_link(engine, digits, player,
                                                target=target)
                if err is None:
                    return None
                return (f"WhatsApp search could not open '{target}', and the "
                        f"phone link fallback also failed ({err}).")
            return (f"WhatsApp search opened but the chat for '{target}' did not "
                    f"open (check the exact contact name).")
    return None


def _chat_open_ok(engine, target: str) -> bool | None:
    """Vision check: is the chat header showing this contact? None = can't tell."""
    try:
        from actions.computer_control import _screen_confirm
        return _bounded(
            lambda: _screen_confirm(
                f"Is the WhatsApp chat with '{target}' open right now — is the "
                f"header showing this contact's name and a visible message area?"),
            timeout=15.0)
    except Exception:
        return None


def whatsapp_takeover_call(contact: str, call_type: str = "voice",
                           player=None) -> Optional[str]:
    """Calling features have been removed."""
    return (
        "Calling features have been removed from Keys.ai. "
        "I can only send messages, not make calls."
    )


# ── public: send a message ──────────────────────────────────────────────
def whatsapp_takeover_send(receiver: str, message: str,
                           player=None) -> Optional[str]:
    """Take over WhatsApp in Control Mode and send ONE verified message.

    Returns None when WhatsApp could not be reached at all — callers report
    the honest failure and NEVER fall back to WhatsApp Web. Otherwise
    returns the honest outcome string.
    """
    engine = _engine(player)
    try:
        _ensure_whatsapp(engine, player)
    except WhatsAppUnavailable as e:
        _log(f"takeover unavailable: {e}", player)
        return None
    except Exception as e:
        return f"Could not take over WhatsApp: {str(e)[:150]}"
    _targeter().reset()      # fresh takeover → reticle launches from the cursor

    try:
        err = _open_chat(engine, receiver, player)
        if err:
            return f"Could not open {receiver}'s chat in WhatsApp: {err}"
        # NOTE: a None return here is an honest "could not reach the desktop
        # app" signal — callers report it, they never fall back to Web.

        composer = _find(engine, ["type a message", "message", "Message",
                                  "composer", "message input"])
        if composer is None:
            # one-shot scene: ONE screenshot locates the composer
            scene = _capture_scene(
                engine, {"composer": "the WhatsApp message input box at the "
                                     "bottom of the open chat"})
            cbox = (scene or {}).get("composer")
            if cbox:
                composer = {"rect": {"x": cbox[0], "y": cbox[1],
                                      "width": cbox[2] - cbox[0],
                                      "height": cbox[3] - cbox[1]}}
        if composer is None:
            return (f"I took control of WhatsApp and opened {receiver}'s chat, "
                    f"but could not find the message box — nothing was sent.")
        # missile targeting: square border flies onto the composer, then the
        # mouse homes in and clicks
        _target_and_click(engine, composer, player)
        time.sleep(0.3)

        if len(message) > 20:
            try:
                import pyperclip
                pyperclip.copy(message)
                time.sleep(0.1)
                engine.hotkey("ctrl+v")
            except Exception:
                engine.core().motion().type_text(message)
        else:
            engine.core().motion().type_text(message)
        time.sleep(0.3)
        engine.core().motion().hotkey(["enter"])
        time.sleep(0.5)

        # Verify ON SCREEN — never claim a send we cannot see.
        from actions.send_message import _verify_message_sent
        return _verify_message_sent("WhatsApp", receiver, message)
    except Exception as e:
        # NEVER raise mid-flow: once control was taken, a caller must not
        # fall back to a second path and risk a double send. Report honestly.
        return (f"Message to {receiver} via WhatsApp takeover was interrupted "
                f"({str(e)[:120]}) — please check the screen. It will not be "
                f"resent automatically.")
    finally:
        _release(engine)
