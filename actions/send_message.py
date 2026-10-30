import json
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.06
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
        cfg = json.loads(
            (_base_dir() / "config" / "api_keys.json").read_text(encoding="utf-8")
        )
        return cfg.get("os_system", "windows").lower()
    except Exception:
        return "windows"


def _require_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")


def _paste_text(text: str) -> None:
    _require_pyautogui()

    os_name = _get_os()
    paste_hotkey = ("command", "v") if os_name == "mac" else ("ctrl", "v")

    if _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.15)
        pyautogui.hotkey(*paste_hotkey)
        time.sleep(0.1)
    else:
        pyautogui.write(text, interval=0.03)


def _clear_and_paste(text: str) -> None:
    _require_pyautogui()
    os_name = _get_os()
    select_all = ("command", "a") if os_name == "mac" else ("ctrl", "a")
    pyautogui.hotkey(*select_all)
    time.sleep(0.1)
    pyautogui.press("delete")
    time.sleep(0.1)
    _paste_text(text)

def _open_app(app_name: str) -> bool:
    _require_pyautogui()
    os_name = _get_os()

    try:
        if os_name == "windows":
            pyautogui.press("win")
            time.sleep(0.5)
            _paste_text(app_name)
            time.sleep(0.6)
            pyautogui.press("enter")
            time.sleep(2.5)
            return True

        elif os_name == "mac":
            result = subprocess.run(
                ["open", "-a", app_name],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                result = subprocess.run(
                    ["open", "-a", f"{app_name}.app"],
                    capture_output=True, text=True, timeout=10,
                )
            time.sleep(2.5)
            return result.returncode == 0

        else: 
            launched = False
            for launcher in [
                ["gtk-launch", app_name.lower()],
                [app_name.lower()],
            ]:
                try:
                    subprocess.Popen(
                        launcher,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    launched = True
                    break
                except FileNotFoundError:
                    continue
            time.sleep(2.5)
            return launched

    except Exception as e:
        print(f"[SendMessage] ⚠️ Could not open {app_name}: {e}")
        return False


def _open_browser_url(url: str) -> bool:
    import webbrowser
    try:
        webbrowser.open(url)
        time.sleep(4.0) 
        return True
    except Exception as e:
        print(f"[SendMessage] ⚠️ Could not open browser: {e}")
        return False

def _search_in_app(query: str) -> None:
    _require_pyautogui()
    os_name = _get_os()
    search_hotkey = ("command", "f") if os_name == "mac" else ("ctrl", "f")

    pyautogui.hotkey(*search_hotkey)
    time.sleep(0.5)
    _clear_and_paste(query)
    time.sleep(1.0)

def _verify_message_sent(app_name: str, receiver: str, message: str,
                          max_wait: float = 10.0) -> str:
    """After pressing Enter, actually LOOK at the screen and confirm the
    message appeared. Polls while the app is still loading and returns an
    HONEST result: confirmed sent, or explicitly unconfirmed so the model
    never claims a send it cannot verify."""
    try:
        from actions.screen_processor import _capture_screen
        from core.vision import vision_generate_text
    except Exception as e:
        return (f"Message sent to {receiver} via {app_name}, but could NOT be "
                f"verified on screen (vision unavailable: {e}).")

    preview = (message or "")[:80]
    question = (
        f"I just tried to send a message to {receiver} via {app_name} "
        f"with the text: {preview!r}. "
        "Look at the screen right now. Did the message actually get sent and "
        "appear in the chat/conversation window? "
        "If you see it, answer with exactly one word: CONFIRMED. "
        "If you see loading, an error, a blank field, or the message is not "
        "present, answer with exactly one word: NOT_CONFIRMED."
    )

    time.sleep(0.8)          # let the send finish before first look
    deadline = time.time() + max_wait
    last_error = None
    while time.time() < deadline:
        try:
            img_bytes, mime = _capture_screen()
            answer = (vision_generate_text(question, img_bytes, mime) \
                      or "").upper().strip()
        except Exception as e:
            # Transient vision/API hiccup — keep waiting and look again,
            # so a momentary blip never fails to confirm a real send.
            last_error = e
            time.sleep(1.5)
            continue
        if not answer:
            # Vision returned nothing (no key / provider down / quota) —
            # fail fast instead of burning the whole poll window.
            last_error = last_error or RuntimeError("vision unavailable")
            time.sleep(1.5)
            continue
        if "CONFIRMED" in answer and "NOT_CONFIRMED" not in answer:
            return f"Message confirmed sent to {receiver} via {app_name} (verified on screen)."
        time.sleep(1.5)       # still loading / not visible yet — wait, then look again
    if last_error is not None:
        _err = str(last_error)[:120]
        return (f"Message sent to {receiver} via {app_name}, but could NOT be "
                f"verified on screen ({_err}).")
    return (f"Message sent to {receiver} via {app_name}, but could NOT be confirmed "
            f"on screen — please check manually.")


def _desktop_send(app_name: str, receiver: str, message: str) -> str:
    if not _open_app(app_name):
        return f"Could not open {app_name}."

    time.sleep(1.0)
    _search_in_app(receiver)
    pyautogui.press("enter")
    time.sleep(0.8)

    _paste_text(message)
    time.sleep(0.2)
    pyautogui.press("enter")
    time.sleep(0.3)
    return _verify_message_sent(app_name, receiver, message)

def _send_whatsapp(receiver: str, message: str) -> str:
    """WhatsApp: messaging happens in the WhatsApp DESKTOP app — the
    previous method. WhatsApp Web (the Selenium browser subsystem) is
    intentionally NOT launched for sends anymore: it kept popping up a
    WhatsApp Web window every time a message was sent. The chain is now
    desktop app first (direct pyautogui send), desktop Control-Mode
    takeover as the fallback, and an honest failure if neither can run.
    (The Web subsystem is still available for explicitly-requested chat
    reading via whatsapp_control list_chats/read_messages; re-enable Web
    sends here later if wanted.)"""
    # ── Direct desktop-app send first (no Web window). ──────────────────
    try:
        result = _desktop_send("WhatsApp", receiver, message)
        if result and not result.startswith("Could not open"):
            return result
        desktop_fail = result or "desktop send returned nothing"
    except Exception as e:
        print(f"[SendMessage] WhatsApp desktop send error: {e}")
        # The desktop path raised MID-FLIGHT — the message MAY have been
        # typed/sent. Never fall through to a second send path (duplicate
        # protection): report honestly and let the user check the screen.
        return (f"Message to {receiver} via WhatsApp was interrupted "
                f"({str(e)[:120]}) — please check the screen. It will not "
                f"be resent automatically.")
    # ── Desktop Control-Mode takeover fallback (still the desktop app). ──
    # Reached only when the desktop send DEFINITIVELY did nothing (the app
    # could not be opened) — never after a may-have-sent result.
    try:
        from actions.whatsapp_takeover import whatsapp_takeover_send
        takeover = whatsapp_takeover_send(receiver, message)
        if takeover:
            return takeover
    except Exception as e:
        print(f"[SendMessage] WhatsApp takeover unavailable ({e})")
    return (f"Message to {receiver} via WhatsApp was interrupted "
            f"({desktop_fail}) — please check the screen. If the WhatsApp "
            f"desktop app is not installed, open it once and try again.")

def _send_telegram(receiver: str, message: str) -> str:
    return _desktop_send("Telegram", receiver, message)

def _send_signal(receiver: str, message: str) -> str:
    return _desktop_send("Signal", receiver, message)


def _send_discord(receiver: str, message: str) -> str:
    return _desktop_send("Discord", receiver, message)


def _send_instagram(receiver: str, message: str) -> str:
    _require_pyautogui()

    if not _open_browser_url("https://www.instagram.com/direct/new/"):
        return "Could not open Instagram in browser."

    _paste_text(receiver)
    time.sleep(1.5)

    pyautogui.press("down")
    time.sleep(0.3)
    pyautogui.press("enter")   
    time.sleep(0.4)

    for _ in range(4):
        pyautogui.press("tab")
        time.sleep(0.15)
    pyautogui.press("enter")
    time.sleep(2.0)

    _paste_text(message)
    time.sleep(0.2)
    pyautogui.press("enter")
    time.sleep(0.3)

    return _verify_message_sent("Instagram", receiver, message)


def _send_messenger(receiver: str, message: str) -> str:
    _require_pyautogui()

    if not _open_browser_url("https://www.messenger.com/"):
        return "Could not open Messenger in browser."


    _search_in_app(receiver)
    time.sleep(0.5)
    pyautogui.press("down")
    time.sleep(0.3)
    pyautogui.press("enter")
    time.sleep(1.0)

    _paste_text(message)
    time.sleep(0.2)
    pyautogui.press("enter")
    time.sleep(0.3)

    return _verify_message_sent("Messenger", receiver, message)

_PLATFORM_MAP = [
    ({"whatsapp", "wp", "wapp"},              _send_whatsapp),
    ({"telegram", "tg"},                      _send_telegram),
    ({"instagram", "ig", "insta"},            _send_instagram),
    ({"signal"},                               _send_signal),
    ({"discord"},                              _send_discord),
    ({"messenger", "facebook", "fb"},         _send_messenger),
]


def _resolve_platform(platform_str: str):
    key = platform_str.lower().strip()
    for keywords, handler in _PLATFORM_MAP:
        if any(k in key for k in keywords):
            return handler
    return lambda r, m: _desktop_send(platform_str.strip().title(), r, m)


_WA_ROW_PREFIX = re.compile(r"^(?:view status|pinned chat|unread\s*\d+)\s+", re.I)
_WA_TIME_MARK = re.compile(
    r"\s(?:\d{1,2}:\d{2}|yesterday|today|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"\d{1,2}/\d{1,2}/\d{2,4})\b", re.I)


def _wa_name_from_row(label: str) -> str:
    """The contact/chat name from a WhatsApp list row.

    UI Automation flattens a chat row into one string, e.g.
    ``'Mini Malaysia 09:53 Crown_Code_Product_Showcase.pptx'``. Sending to the
    whole row would search for the message preview instead of the person, so
    the name is cut at the timestamp (or day marker) that follows it.
    """
    text = (label or "").strip()
    text = _WA_ROW_PREFIX.sub("", text).strip()
    m = _WA_TIME_MARK.search(text)
    if m and m.start() > 0:
        text = text[:m.start()].strip()
    return text.strip(" \t-\u2013\u2014.|,")


def _whatsapp_contact_search(name: str, player=None) -> tuple[str, str]:
    """Find a person using WhatsApp's OWN search, when Google contacts fail.

    Google/People lookup is the preferred source, but it can be unusable: the
    Firebase key expired, the account was signed out, or the person was simply
    never saved as a Google contact. WhatsApp's chat list is a contact list in
    its own right, so this searches it directly and reads the matching row
    back through UI Automation before anything is typed into a chat.

    Returns (matched_label, note); an empty label means WhatsApp showed no
    match and the note says so honestly.
    """
    if not _PYAUTOGUI:
        return "", " (WhatsApp search unavailable: PyAutoGUI is not installed)"
    try:
        from automation import get_controller

        ctrl = get_controller()

        # Prefer the WhatsApp window that is already open. Pressing Win+type
        # opens a SECOND window and can leave the search in the wrong one.
        window = ""
        try:
            wins = (ctrl.list_windows().data or {}).get("windows") or []
            for w in wins:
                title = str(w.get("title") or "")
                if "whatsapp" in title.lower():
                    window = title
                    break
        except Exception:
            pass
        if window:
            try:
                ctrl.focus_window(window)
            except Exception:
                pass
        else:
            if not _open_app("WhatsApp"):
                return "", " (WhatsApp could not be opened to search its contacts)"
            window = "WhatsApp"
        time.sleep(1.2)
        _search_in_app(name)          # Ctrl+F, clear, paste the name
        time.sleep(1.4)

        res = ctrl.list_elements(window)
        elements = (getattr(res, "data", {}) or {}).get("elements") or []

        # WhatsApp's own chrome is not a contact: skip navigation rows so the
        # word "Chats" can never be mistaken for a person.
        _UI = {"search", "search or start new chat", "chats", "status", "channels",
               "communities", "calls", "settings", "profile", "new chat",
               "archived", "menu", "close", "back", "more options", "whatsapp"}
        tokens = [t for t in re.split(r"\W+", (name or "").lower()) if t]
        best, best_key = "", (False, 0, 0)
        for el in elements:
            # Only rows in the chat/contact list. The search box itself is an
            # Edit whose NAME is the text just typed — matching it would
            # "find" the query and send to a chat called "Mini".
            if str(el.get("control_type") or "") not in ("DataItem", "ListItem"):
                continue
            raw = str(el.get("name") or "").replace("\r", "\n")
            label = _wa_name_from_row(raw.split("\n")[0])
            if len(label) < 2:
                continue
            low = label.lower()
            if low in _UI or low.startswith(("search for", "new chat", "archived")):
                continue
            score = sum(1 for t in tokens if t in low)
            if score == 0:
                continue
            full = score == len(tokens)
            # Prefer a full-name match, then more matching words, then the
            # shortest label (a chat row can carry a message preview).
            key = (full, score, -len(label))
            if key > best_key:
                best, best_key = label, key
        if best:
            print(f"[SendMessage] WhatsApp search matched '{best}' for '{name}'")
            return best, (f" (not in Google contacts \u2014 matched '{best}' "
                          "by searching WhatsApp directly)")
        return "", (" (not in Google contacts, and WhatsApp's own search shows "
                    "no chat or contact by that name \u2014 give me the phone "
                    "number or save the contact in WhatsApp first)")
    except Exception as e:
        print(f"[SendMessage] WhatsApp contact search failed: {e}")
        return "", f" (WhatsApp contact search failed: {str(e)[:100]})"


def _resolve_receiver(receiver: str, platform: str):
    """Look up a spoken contact NAME and return (search_target, note).

    Order: verified/Google contacts first, then — for WhatsApp — WhatsApp's own
    search, so a person who was never saved as a Google contact is still found
    in the app the message is actually going to. WhatsApp/Telegram/Signal
    search best by phone number, so a matched phone is used there;
    Instagram/Messenger search by name/username."""
    low_platform = platform.lower()
    phone_based = any(k in low_platform for k in
                      ("whatsapp", "wapp", "wp", "telegram", "tg", "signal"))
    lookup_error = ""
    c = None
    try:
        from core import firebase_client as fb
        if fb.is_signed_in():
            c = fb.find_contact(receiver)
    except Exception as e:
        lookup_error = str(e)
        print(f"[SendMessage] Google contact lookup failed for '{receiver}': {e}")

    if c is not None:
        name = c.get("name") or receiver
        src  = c.get("source", "")
        note = f" (matched contact {name} from {src} contacts)"
        if phone_based:
            if c.get("phone"):
                return c["phone"], f" (matched contact {name} \u2014 {c['phone']}, from {src} contacts)"
            if c.get("email"):
                return c["email"], f" (matched contact {name} \u2014 {c['email']}, from {src} contacts)"
            return name, note
        if "@" in receiver or receiver.startswith("@"):
            return receiver, note
        return name, note

    # Nothing in Google contacts (or the lookup was unusable): ask WhatsApp
    # itself before giving up, so the message can still reach the right chat.
    if "whatsapp" in low_platform:
        matched, note = _whatsapp_contact_search(receiver)
        if matched:
            return matched, note
        if note:
            return receiver, note

    if lookup_error:
        return receiver, f" (could not look up '{receiver}' in contacts: {lookup_error[:100]})"
    return receiver, ""


def _verified_contact_note(receiver: str, require_verified: bool):
    """Gate messaging on Google-verified contacts when Firebase is configured.

    Returns (block_result, note):
      block_result — non-empty str to return immediately (hard gate), or ""
      note         — extra "(verified Google contact: ...)" text when allowed
    When require_verified is False, no Firestore lookup happens at all (the
    tool behaves exactly as before unless the gate is explicitly on).
    """
    if not require_verified:
        return "", ""
    try:
        from core import firebase_client as fb
        if not fb.is_configured():
            return ("Contact verification requires Google sign-in — follow FIREBASE_SETUP.md "
                    "and run google_account sign_in first.", "")
        if not fb.is_signed_in():
            return "You are not signed in with Google. Say 'sign in with Google' first.", ""
        record = fb.verify_contact(receiver)
        if record is None:
            return (f"'{receiver}' is NOT in your verified contacts. Add/confirm it via "
                    "google_account first (or ask the user to send anyway).", "")
        if not record.get("verified"):
            return (f"'{receiver}' is added but NOT confirmed via Google. Confirm it with "
                    "google_account confirm_contact first.", "")
        return "", f" (verified Google contact: {record.get('google_email', '')})"
    except Exception as e:
        return f"Could not verify contact '{receiver}' right now: {str(e)[:150]}", ""


def send_message(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params       = parameters or {}
    receiver     = params.get("receiver", "").strip()
    message_text = params.get("message_text", "").strip()
    platform     = params.get("platform", "whatsapp").strip()
    require_verified = str(params.get("require_verified", "")).lower() in (
        "1", "true", "yes", "y"
    )

    if not receiver:
        return "Please specify a recipient."
    if not message_text:
        return "Please specify the message content."
    if not _PYAUTOGUI:
        return "PyAutoGUI is not installed — cannot control the desktop."

    # Google-verified contact gate (only active when Firebase is configured)
    block_result, verified_note = _verified_contact_note(receiver, require_verified)
    if block_result:
        print(f"[SendMessage] ⛔ Blocked (unverified contact): {receiver}")
        if player:
            player.write_log(f"[msg] ⛔ {block_result}")
        return block_result

    # Resolve the spoken NAME to the person's real phone/email from contacts,
    # so the search targets the right person even when only a name was given.
    search_target, resolve_note = _resolve_receiver(receiver, platform)

    preview = message_text[:50] + ("…" if len(message_text) > 50 else "")
    note    = (verified_note + resolve_note) or ""
    print(f"[SendMessage] 📨 {platform} → {search_target}: {preview}{note}")
    if player:
        player.write_log(f"[msg] {platform} → {search_target}{note}")

    try:
        handler = _resolve_platform(platform)
        result  = handler(search_target, message_text)
    except Exception as e:
        result = f"Could not send message: {e}"

    _confirmed = result.lower().startswith("message confirmed sent")
    if note:
        # Always surface which real contact/number was targeted, even if the
        # on-screen confirmation came back inconclusive.
        result = result.rstrip(".") + note + "."
    print(f"[SendMessage] {'✅' if _confirmed else '❌'} {result}")
    if player:
        player.write_log(f"[msg] {result}")

    return result