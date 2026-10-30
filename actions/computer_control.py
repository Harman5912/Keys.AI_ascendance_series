#computer_control.py
import io
import json
import platform
import re
import string
import subprocess
import sys

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}
import time
import random
from pathlib import Path

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.05
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


_BASE         = _base_dir()
_CONFIG_PATH  = _BASE / "config" / "api_keys.json"
_MEMORY_PATH  = _BASE / "memory" / "long_term.json"

def _load_config() -> dict:
    try:
        from core.config_store import load as _load_cfg
        return _load_cfg()
    except Exception:
        try:
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

def _platform_os() -> str:
    return {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(
        platform.system(), "linux"
    )

def _get_os() -> str:
    return _load_config().get("os_system", _platform_os()).lower()


def _get_api_key() -> str:
    return _load_config().get("gemini_api_key", "")

_SAFE_SCREENSHOT_ROOTS = (
    Path.home(),
)

def _safe_screenshot_path(requested: str | None) -> Path:
    fallback = Path.home() / "Desktop" / "keysai_screenshot.png"
    if not requested:
        return fallback
    try:
        p = Path(requested).expanduser().resolve()
        for root in _SAFE_SCREENSHOT_ROOTS:
            if p.is_relative_to(root.resolve()):
                p.parent.mkdir(parents=True, exist_ok=True)
                return p
    except Exception:
        pass
    return fallback

def _require_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")

_FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Drew", "Quinn",
    "Avery", "Blake", "Cameron", "Dakota", "Emerson", "Finley", "Harper",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson",
]
_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "proton.me", "mail.com"]


def _random_data(data_type: str) -> str:
    dt = data_type.lower().strip()

    if dt == "first_name":
        return random.choice(_FIRST_NAMES)

    if dt == "last_name":
        return random.choice(_LAST_NAMES)

    if dt == "name":
        return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"

    if dt == "email":
        first = random.choice(_FIRST_NAMES).lower()
        last  = random.choice(_LAST_NAMES).lower()
        num   = random.randint(10, 999)
        return f"{first}.{last}{num}@{random.choice(_DOMAINS)}"

    if dt == "username":
        return f"{random.choice(_FIRST_NAMES).lower()}{random.randint(100, 9999)}"

    if dt == "password":
        chars = string.ascii_letters + string.digits + "!@#$%"
        raw   = (
            random.choice(string.ascii_uppercase)
            + random.choice(string.digits)
            + random.choice("!@#$%")
            + "".join(random.choices(chars, k=9))
        )
        return "".join(random.sample(raw, len(raw)))

    if dt == "phone":
        return f"+1{random.randint(200,999)}{random.randint(1_000_000, 9_999_999)}"

    if dt == "birthday":
        y = random.randint(1980, 2000)
        m = random.randint(1, 12)
        d = random.randint(1, 28)
        return f"{m:02d}/{d:02d}/{y}"

    if dt == "address":
        num    = random.randint(100, 9999)
        street = random.choice(["Main St", "Oak Ave", "Park Blvd", "Elm St", "Cedar Ln"])
        return f"{num} {street}"

    if dt == "zip_code":
        return str(random.randint(10000, 99999))

    if dt == "city":
        return random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"])

    return f"random_{data_type}_{random.randint(1000, 9999)}"

def _user_profile() -> dict:
    """Read identity fields from long-term memory."""
    try:
        if _MEMORY_PATH.exists():
            data     = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
            identity = data.get("identity", {})
            return {k: v.get("value", "") for k, v in identity.items()}
    except Exception:
        pass
    return {}

def _type(text: str, interval: float = 0.03) -> str:
    _require_pyautogui()
    time.sleep(0.3)
    pyautogui.typewrite(text, interval=interval)
    return f"Typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _smart_type(text: str, clear_first: bool = True) -> str:
    _require_pyautogui()
    if clear_first:
        _clear_field()
        time.sleep(0.1)

    if len(text) > 20 and _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        paste_key = "command" if _get_os() == "mac" else "ctrl"
        pyautogui.hotkey(paste_key, "v")
        return f"Smart-typed (clipboard): {text[:60]}{'…' if len(text) > 60 else ''}"

    pyautogui.typewrite(text, interval=0.04)
    return f"Smart-typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _click(x=None, y=None, button: str = "left", clicks: int = 1) -> str:
    _require_pyautogui()
    if x is not None and y is not None:
        pyautogui.click(x, y, button=button, clicks=clicks)
        return f"{'Double-c' if clicks == 2 else 'C'}licked ({x}, {y}) [{button}]"
    pyautogui.click(button=button, clicks=clicks)
    return f"Clicked at current position [{button}]"


def _hotkey(*keys) -> str:
    _require_pyautogui()
    pyautogui.hotkey(*keys)
    return f"Hotkey: {'+'.join(keys)}"


def _press(key: str) -> str:
    _require_pyautogui()
    pyautogui.press(key)
    return f"Pressed: {key}"


def _scroll(direction: str = "down", amount: int = 3) -> str:
    _require_pyautogui()
    vertical   = direction in ("up", "down")
    clicks     = amount if direction in ("up", "right") else -amount
    pyautogui.scroll(clicks) if vertical else pyautogui.hscroll(clicks)
    return f"Scrolled {direction} ×{amount}"


def _move(x: int, y: int, duration: float = 0.3) -> str:
    _require_pyautogui()
    pyautogui.moveTo(x, y, duration=duration)
    return f"Mouse → ({x}, {y})"


def _drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> str:
    _require_pyautogui()
    pyautogui.moveTo(x1, y1, duration=0.2)
    pyautogui.dragTo(x2, y2, duration=duration, button="left")
    return f"Dragged ({x1},{y1}) → ({x2},{y2})"


def _clipboard_get() -> str:
    if _PYPERCLIP:
        return pyperclip.paste()
    _hotkey("ctrl", "c")
    time.sleep(0.2)
    return "(copied — pyperclip unavailable for read)"


def _clipboard_paste(text: str) -> str:
    if _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        _require_pyautogui()
        paste_key = "command" if _get_os() == "mac" else "ctrl"
        pyautogui.hotkey(paste_key, "v")
        return f"Pasted: {text[:60]}{'…' if len(text) > 60 else ''}"
    return "pyperclip not available"


def _screenshot(save_path: str | None = None) -> str:
    _require_pyautogui()
    path = _safe_screenshot_path(save_path)
    img  = pyautogui.screenshot()
    img.save(str(path))
    return f"Screenshot saved: {path}"


def _clear_field() -> str:
    _require_pyautogui()
    select_key = "command" if _get_os() == "mac" else "ctrl"
    pyautogui.hotkey(select_key, "a")
    time.sleep(0.1)
    pyautogui.press("delete")
    return "Field cleared"

def _focus_window(title: str) -> str:
    os_name = _get_os()

    if os_name == "windows":
        try:
            script = f'(New-Object -ComObject WScript.Shell).AppActivate("{title}")'
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, timeout=5, **_WIN_HIDE,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except Exception as e:
            return f"focus_window (Windows) failed: {e}"

    if os_name == "mac":
        script = (
            f'tell application "System Events" to '
            f'set frontmost of (first process whose name contains "{title}") to true'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except Exception as e:
            return f"focus_window (macOS) failed: {e}"

    if os_name == "linux":
        try:
            result = subprocess.run(
                ["wmctrl", "-a", title],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                time.sleep(0.3)
                return f"Focused window: {title}"
        except FileNotFoundError:
            pass
        try:
            result = subprocess.run(
                ["xdotool", "search", "--name", title, "windowactivate"],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except FileNotFoundError:
            return "focus_window (Linux) requires wmctrl or xdotool"
        except Exception as e:
            return f"focus_window (Linux) failed: {e}"

    return f"focus_window: unknown OS '{os_name}'"

def _screen_find(description: str) -> tuple[int, int] | None:
    """Locate a UI element by description, using the ACTIVE provider's
    vision model (core.vision). Returns (x, y) center, or None."""
    try:
        from core.vision import vision_generate_text

        _require_pyautogui()
        w, h  = pyautogui.size()
        img   = pyautogui.screenshot()
        buf   = io.BytesIO()
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        prompt = (
            f"This is a screenshot of a {w}×{h} pixel screen. "
            f"Locate the UI element described as: '{description}'. "
            f"Reply with ONLY the center coordinates as: x,y "
            f"If the element is not visible, reply: NOT_FOUND"
        )

        text = vision_generate_text(prompt, image_bytes, "image/png") or ""
        if "NOT_FOUND" in text.upper():
            return None

        match = re.search(r"(\d+)\s*,\s*(\d+)", text)
        if match:
            return int(match.group(1)), int(match.group(2))

    except Exception as e:
        print(f"[ComputerControl] ⚠️ screen_find failed: {e}")

    return None


def _screen_find_box(description: str, max_attempts: int = 2,
                     min_size: int = 14) -> tuple[int, int, int, int] | None:
    """Vision bounding box (x1, y1, x2, y2) for a UI element.

    This is the screenshot -> LLM bounding box -> click-center pattern used by
    the reliable desktop-agent projects (Anthropic computer use, Microsoft
    UFO/OmniParser): a box is far more robust than asking for a single point,
    and clicking the box center lands inside the target even when the model's
    estimate is off by a few pixels. Returns None when not found (after up to
    `max_attempts` fresh screenshots).
    """
    try:
        from core.vision import vision_generate_text

        _require_pyautogui()
        for _ in range(max(1, int(max_attempts))):
            w, h = pyautogui.size()
            img = pyautogui.screenshot()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            prompt = (
                f"This is a screenshot of a {w}×{h} pixel screen. "
                f"Find the bounding box of the UI element described as: "
                f"'{description}'. Reply with ONLY four integers: x1,y1,x2,y2 "
                f"(top-left corner, bottom-right corner). If the element is not "
                f"visible, reply: NOT_FOUND"
            )
            text = vision_generate_text(prompt, buf.getvalue(), "image/png") or ""
            if "NOT_FOUND" in text.upper():
                return None
            nums = re.findall(r"\d+", text)
            if len(nums) >= 4:
                x1, y1, x2, y2 = map(int, nums[:4])
                if 0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h \
                        and (x2 - x1) >= min_size and (y2 - y1) >= min_size:
                    return (x1, y1, x2, y2)
            time.sleep(0.8)   # fresh look before retrying
    except Exception as e:
        print(f"[ComputerControl] ⚠️ screen_find_box failed: {e}")
    return None


def _parse_box_map(text: str) -> dict[str, tuple]:
    """Extract {key: (x1,y1,x2,y2)} from a vision reply.

    Accepts both a JSON object and loose 'key: x1,y1,x2,y2' lines — models
    vary in formatting, so both are tolerated.
    """
    out: dict[str, tuple] = {}
    try:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(text[start:end + 1])
            for k, v in (data or {}).items():
                if isinstance(v, (list, tuple)) and len(v) >= 4:
                    nums = [int(n) for n in v[:4]]
                    if min(nums) >= 0:
                        out[str(k)] = tuple(nums)
                elif isinstance(v, str) and "," in v:
                    nums = [int(n) for n in re.findall(r"\d+", v)]
                    if len(nums) >= 4:
                        out[str(k)] = tuple(nums[:4])
    except Exception:
        pass
    for k, a, b, c, d in re.findall(
            r'"?([A-Za-z0-9_]+)"?\s*[:=]\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)',
            text):
        out[k] = (int(a), int(b), int(c), int(d))
    return out


def _screen_find_boxes(descriptions: dict[str, str]) -> dict[str, tuple | None]:
    """Locate MANY UI elements from ONE screenshot + ONE vision pass.

    descriptions: {key: natural-language description}
    returns:      {key: (x1, y1, x2, y2) or None}

    This is the "stop taking a screenshot at every step" primitive: a whole
    takeover can ask for every element it will need in a single shot instead
    of one screenshot per element. A single key is delegated to
    `_screen_find_box` (identical behaviour, one attempt). When the model
    cannot return the full map, the missing keys get their own individual
    look — bounded to one attempt each.
    """
    descs = {k: v for k, v in (descriptions or {}).items() if str(v).strip()}
    if not descs:
        return {}
    if len(descs) == 1:
        k, d = next(iter(descs.items()))
        return {k: _screen_find_box(str(d), max_attempts=1)}

    result: dict[str, tuple | None] = {}
    try:
        from core.vision import vision_generate_text

        _require_pyautogui()
        w, h = pyautogui.size()
        img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        listing = ", ".join(f'"{k}": "{d}"' for k, d in descs.items())
        prompt = (
            f"This is a screenshot of a {w}×{h} pixel screen. "
            "Locate the bounding box of EVERY ONE of the UI elements below. "
            'Reply with ONLY a JSON object like {"key": [x1, y1, x2, y2]} '
            "(top-left corner, bottom-right corner, screen pixels). For any "
            "element that is not visible on screen use null. "
            f"Elements: {listing}"
        )
        text = vision_generate_text(prompt, buf.getvalue(), "image/png") or ""
        parsed = _parse_box_map(text)
        for k in descs:
            box = parsed.get(k)
            if box and 0 <= box[0] < box[2] <= w and 0 <= box[1] < box[3] <= h \
                    and (box[2] - box[0]) >= 8 and (box[3] - box[1]) >= 8:
                result[k] = box
        for k in descs:
            if k not in result:
                result[k] = _screen_find_box(str(descs[k]), max_attempts=1)
        return result
    except Exception as e:
        print(f"[ComputerControl] ⚠️ screen_find_boxes failed: {e}")
    return {k: _screen_find_box(str(d), max_attempts=1) for k, d in descs.items()}


def _screen_confirm(question: str, max_wait: float = 10.0) -> bool | None:
    """Ask Gemini a yes/no question about the current screen.

    Returns True/False from the answer, or None when the screen cannot be
    read (no API key, vision error) so callers can decide how to fall back.
    Used to VERIFY state changes after an action (the SEE->ACT->VERIFY loop).
    """
    try:
        from core.vision import vision_generate_text

        _require_pyautogui()
        deadline = time.time() + max(2.0, max_wait)
        last = None
        while time.time() < deadline:
            try:
                img = pyautogui.screenshot()
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                ans = (vision_generate_text(
                    question + " Answer ONLY YES or NO.",
                    buf.getvalue(), "image/png") or "").upper().strip()
                last = ans
                if "YES" in ans and "NO" not in ans:
                    return True
                if "NO" in ans and "YES" not in ans:
                    return False
            except Exception as e:
                print(f"[ComputerControl] ⚠️ screen_confirm vision error: "
                      f"{str(e)[:120]}")
            time.sleep(1.2)   # uncertain or failed — look again
        print(f"[ComputerControl] ⚠️ screen_confirm unclear ({last}) — unknown")
        return None
    except Exception as e:
        print(f"[ComputerControl] ⚠️ screen_confirm failed: {e}")
        return None

def computer_control(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Dispatch table for all computer control actions.

    parameters keys (all optional unless noted):
      action        : (required) one of the actions listed below
      text          : text to type or paste
      x, y          : screen coordinates
      button        : 'left' | 'right' (default: left)
      keys          : hotkey string, e.g. 'ctrl+c'
      key           : single key name, e.g. 'enter'
      direction     : 'up' | 'down' | 'left' | 'right'
      amount        : scroll amount (default: 3)
      seconds       : wait duration
      title         : window title fragment for focus_window
      description   : natural-language element description for screen_find/click
      type          : data type for random_data
      field         : memory field name for user_data
      clear_first   : bool, clear field before typing (default: true)
      path          : save path for screenshot (must be inside home dir)

    Actions:
      type          — type text at cursor
      smart_type    — clear field + type (clipboard-backed)
      click         — left click
      double_click  — double left click
      right_click   — right click
      move          — move mouse
      drag          — click-drag between two points
      hotkey        — key combination
      press         — single key
      scroll        — scroll the wheel
      copy          — read clipboard
      paste         — write + paste clipboard
      screenshot    — capture screen (safe path only)
      wait          — sleep N seconds
      clear_field   — select-all + delete
      focus_window  — bring window to foreground
      screen_find   — AI element finder (returns x,y)
      screen_click  — AI element finder + click
      random_data   — generate fake form data
      user_data     — pull real data from memory
    """
    params = parameters or {}
    action = params.get("action", "").lower().strip()

    if not action:
        return "No action specified for computer_control."

    if player:
        player.write_log(f"[Computer] {action}")

    print(f"[ComputerControl] ▶ {action}  {params}")

    try:

        if action == "type":
            return _type(params.get("text", ""))

        if action == "smart_type":
            return _smart_type(
                params.get("text", ""),
                clear_first=params.get("clear_first", True),
            )

        if action in ("click", "left_click"):
            return _click(params.get("x"), params.get("y"), "left", 1)

        if action == "double_click":
            return _click(params.get("x"), params.get("y"), "left", 2)

        if action == "right_click":
            return _click(params.get("x"), params.get("y"), "right", 1)

        if action == "move":
            return _move(int(params.get("x", 0)), int(params.get("y", 0)))

        if action == "drag":
            return _drag(
                int(params.get("x1", 0)), int(params.get("y1", 0)),
                int(params.get("x2", 0)), int(params.get("y2", 0)),
            )

        if action == "hotkey":
            raw  = params.get("keys", "")
            keys = [k.strip() for k in raw.split("+")] if isinstance(raw, str) else raw
            return _hotkey(*keys)

        if action == "press":
            return _press(params.get("key", "enter"))

        if action == "scroll":
            return _scroll(
                direction=params.get("direction", "down"),
                amount=int(params.get("amount", 3)),
            )

        if action == "copy":
            return _clipboard_get()

        if action == "paste":
            return _clipboard_paste(params.get("text", ""))

        if action == "screenshot":
            return _screenshot(params.get("path"))

        if action == "screen_find":
            coords = _screen_find(params.get("description", ""))
            return f"{coords[0]},{coords[1]}" if coords else "NOT_FOUND"

        if action == "screen_click":
            desc   = params.get("description", "")
            coords = _screen_find(desc)
            if coords:
                time.sleep(0.2)
                _click(x=coords[0], y=coords[1])
                return f"Clicked '{desc}' at {coords}"
            return f"Element not found on screen: '{desc}'"

        if action == "wait":
            secs = float(params.get("seconds", 1.0))
            secs = min(secs, 30.0)
            time.sleep(secs)
            return f"Waited {secs}s"

        if action == "clear_field":
            return _clear_field()

        if action == "focus_window":
            return _focus_window(params.get("title", ""))

        if action == "random_data":
            dt     = params.get("type", "name")
            result = _random_data(dt)
            print(f"[ComputerControl] 🎲 random {dt} → {result}")
            return result

        if action == "user_data":
            field   = params.get("field", "name")
            profile = _user_profile()
            value   = profile.get(field, "")
            if not value:
                value = _random_data(field)
                print(f"[ComputerControl] ⚠️ No '{field}' in memory, using random: {value}")
            return value

        return f"Unknown action: '{action}'"

    except Exception as e:
        print(f"[ComputerControl] ❌ {action}: {e}")
        return f"computer_control '{action}' failed: {e}"