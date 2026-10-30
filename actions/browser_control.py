
from __future__ import annotations

import asyncio
import concurrent.futures
import os
import platform
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
)
_OS = platform.system()   # "Windows" | "Darwin" | "Linux"

def _normalize_url(url: str) -> str:
    """
    Bare words like "instagram" → "https://instagram.com"
    Domains like "instagram.com" → "https://instagram.com"
    Full URLs pass through unchanged.
    """
    url = url.strip()
    if not url:
        return "about:blank"
    if "://" in url:
        return url
    # No dot at all → assume .com  (e.g. "instagram" → "instagram.com")
    if "." not in url:
        url = url + ".com"
    return "https://" + url


def _user_agent() -> str:
    if _OS == "Windows":
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    if _OS == "Darwin":
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    return (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )


def _real_profile_dir(browser: str) -> str:
    home  = Path.home()
    local = os.environ.get("LOCALAPPDATA", "")
    roam  = os.environ.get("APPDATA", "")

    candidates: list[Path] = []

    if _OS == "Windows":
        m = {
            "chrome":   [Path(local) / "Google"          / "Chrome"          / "User Data"],
            "edge":     [Path(local) / "Microsoft"        / "Edge"            / "User Data"],
            "brave":    [Path(local) / "BraveSoftware"    / "Brave-Browser"   / "User Data"],
            "vivaldi":  [Path(local) / "Vivaldi"          / "User Data"],
            "opera":    [Path(roam)  / "Opera Software"   / "Opera Stable",
                         Path(local) / "Opera Software"   / "Opera Stable"],
            "operagx":  [Path(roam)  / "Opera Software"   / "Opera GX Stable",
                         Path(local) / "Opera Software"   / "Opera GX Stable"],
        }
        candidates = m.get(browser, [])

    elif _OS == "Darwin":
        lib = home / "Library" / "Application Support"
        m = {
            "chrome":   [lib / "Google"             / "Chrome"],
            "edge":     [lib / "Microsoft Edge"],
            "brave":    [lib / "BraveSoftware"       / "Brave-Browser"],
            "vivaldi":  [lib / "Vivaldi"],
            "opera":    [lib / "com.operasoftware.Opera"],
            "operagx":  [lib / "com.operasoftware.OperaGX"],
        }
        candidates = m.get(browser, [])

    elif _OS == "Linux":
        cfg = home / ".config"
        m = {
            "chrome":   [cfg / "google-chrome", cfg / "chromium"],
            "edge":     [cfg / "microsoft-edge"],
            "brave":    [cfg / "BraveSoftware" / "Brave-Browser"],
            "vivaldi":  [cfg / "vivaldi"],
            "opera":    [cfg / "opera"],
            "operagx":  [cfg / "opera-gx"],
        }
        candidates = m.get(browser, [])

    for p in candidates:
        if p.exists():
            print(f"[Browser] ✅ Real profile found for {browser}: {p}")
            return str(p)

    fallback = home / ".keysai_profiles" / browser
    fallback.mkdir(parents=True, exist_ok=True)
    print(f"[Browser] ⚠️  Real profile not found for {browser}, using: {fallback}")
    return str(fallback)

def _firefox_profile_dir() -> Optional[str]:
    home = Path.home()

    if _OS == "Windows":
        base = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox"
    elif _OS == "Darwin":
        base = home / "Library" / "Application Support" / "Firefox"
    else:
        base = home / ".mozilla" / "firefox"

    ini = base / "profiles.ini"
    if not ini.exists():
        return None

    current: dict[str, str] = {}
    default_path: Optional[str] = None

    for line in ini.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("["):
            p = current.get("Path", "")
            if p and current.get("Default") == "1":
                is_rel = current.get("IsRelative", "1") == "1"
                default_path = str(base / p) if is_rel else p
            current = {}
        elif "=" in line:
            k, _, v = line.partition("=")
            current[k.strip()] = v.strip()

    p = current.get("Path", "")
    if p and current.get("Default") == "1":
        is_rel = current.get("IsRelative", "1") == "1"
        default_path = str(base / p) if is_rel else p

    if default_path and Path(default_path).exists():
        print(f"[Browser] Firefox real profile: {default_path}")
        return default_path
    return None

def _find_opera_windows() -> Optional[str]:
    local  = os.environ.get("LOCALAPPDATA", "")
    prog   = os.environ.get("PROGRAMFILES", "")
    prog86 = os.environ.get("PROGRAMFILES(X86)", "")

    candidates = [
        Path(local)  / "Programs" / "Opera"    / "opera.exe",
        Path(local)  / "Programs" / "Opera GX" / "opera.exe",
        Path(prog)   / "Opera"    / "opera.exe",
        Path(prog86) / "Opera"    / "opera.exe",
    ]
    for p in candidates:
        if p.exists():
            print(f"[Browser] Opera found at: {p}")
            return str(p)

    try:
        import winreg
        keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\opera.exe",
            r"SOFTWARE\Clients\StartMenuInternet\OperaStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\OperaGXStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\opera\shell\open\command",
        ]
        for key_path in keys:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    k   = winreg.OpenKey(hive, key_path)
                    val = winreg.QueryValue(k, None)
                    winreg.CloseKey(k)
                    exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        print(f"[Browser] Opera found via registry: {exe}")
                        return exe
                except Exception:
                    continue
    except Exception:
        pass

    return shutil.which("opera") or None

def _find_exe_windows(prog_name: str) -> Optional[str]:
    try:
        import winreg
        paths_to_try = [
            rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{prog_name}.exe",
            rf"SOFTWARE\Clients\StartMenuInternet\{prog_name}\shell\open\command",
        ]
        for key_path in paths_to_try:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    k   = winreg.OpenKey(hive, key_path)
                    val = winreg.QueryValue(k, None)
                    winreg.CloseKey(k)
                    exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        return exe
                except Exception:
                    continue
    except Exception:
        pass
    return None

_BROWSER_SPECS: dict[str, dict] = {
    "Windows": {
        "chrome":   {"engine": "chromium", "channel": "chrome",  "bins": []},
        "edge":     {"engine": "chromium", "channel": "msedge",  "bins": []},
        "firefox":  {"engine": "firefox",  "channel": None,      "bins": ["firefox.exe"]},
        "opera":    {"engine": "chromium", "channel": None,      "bins": ["opera.exe"],  "special": "opera_windows"},
        "operagx":  {"engine": "chromium", "channel": None,      "bins": [],             "special": "opera_windows"},
        "brave":    {"engine": "chromium", "channel": None,      "bins": ["brave.exe"]},
        "vivaldi":  {"engine": "chromium", "channel": None,      "bins": ["vivaldi.exe"]},
        "safari":   None,
    },
    "Darwin": {
        "chrome":   {"engine": "chromium", "channel": "chrome",  "bins": []},
        "edge":     {"engine": "chromium", "channel": "msedge",  "bins": ["microsoft-edge"]},
        "firefox":  {"engine": "firefox",  "channel": None,      "bins": ["firefox"]},
        "opera":    {"engine": "chromium", "channel": None,      "bins": ["opera"]},
        "operagx":  {"engine": "chromium", "channel": None,      "bins": ["opera"]},
        "brave":    {"engine": "chromium", "channel": None,      "bins": ["brave browser", "brave"]},
        "vivaldi":  {"engine": "chromium", "channel": None,      "bins": ["vivaldi"]},
        "safari":   {"engine": "webkit",   "channel": None,      "bins": []},
    },
    "Linux": {
        "chrome":   {"engine": "chromium", "channel": None,
                     "bins": ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]},
        "edge":     {"engine": "chromium", "channel": None,
                     "bins": ["microsoft-edge", "microsoft-edge-stable"]},
        "firefox":  {"engine": "firefox",  "channel": None, "bins": ["firefox"]},
        "opera":    {"engine": "chromium", "channel": None, "bins": ["opera", "opera-stable"]},
        "operagx":  {"engine": "chromium", "channel": None, "bins": ["opera", "opera-stable"]},
        "brave":    {"engine": "chromium", "channel": None, "bins": ["brave-browser", "brave"]},
        "vivaldi":  {"engine": "chromium", "channel": None, "bins": ["vivaldi-stable", "vivaldi"]},
        "safari":   None,
    },
}

_ALIASES: dict[str, str] = {
    "google chrome":   "chrome",
    "google-chrome":   "chrome",
    "microsoft edge":  "edge",
    "ms edge":         "edge",
    "msedge":          "edge",
    "mozilla firefox": "firefox",
    "opera gx":        "operagx",
    "opera_gx":        "operagx",
}


def _resolve_browser(name: str) -> dict | None:
    name   = _ALIASES.get(name.lower().strip(), name.lower().strip())
    os_map = _BROWSER_SPECS.get(_OS, {})
    spec   = os_map.get(name)
    if spec is None:
        return None

    engine  = spec["engine"]
    channel = spec.get("channel")
    bins    = spec.get("bins", [])
    exe     = None

    if spec.get("special") == "opera_windows":
        exe = _find_opera_windows()
        if not exe:
            print(f"[Browser] ⚠️  Opera executable not found on Windows.")
        return {"engine": engine, "exe": exe, "channel": channel}

    for b in bins:
        found = shutil.which(b)
        if found:
            exe = found
            break

    if not exe and _OS == "Darwin":
        app_names = {
            "chrome":  ["Google Chrome.app"],
            "edge":    ["Microsoft Edge.app"],
            "firefox": ["Firefox.app"],
            "opera":   ["Opera.app", "Opera GX.app"],
            "brave":   ["Brave Browser.app"],
            "vivaldi": ["Vivaldi.app"],
        }
        for app in app_names.get(name, []):
            app_dir = Path("/Applications") / app / "Contents" / "MacOS"
            if app_dir.exists():
                found_bins = list(app_dir.iterdir())
                if found_bins:
                    exe = str(found_bins[0])
                    break

    if not exe and _OS == "Windows" and not channel:
        exe = _find_exe_windows(name)

    return {"engine": engine, "exe": exe, "channel": channel}


def _detect_default_browser() -> str:
    try:
        if _OS == "Windows":
            import winreg
            k = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations"
                r"\UrlAssociations\http\UserChoice",
            )
            prog_id = winreg.QueryValueEx(k, "ProgId")[0].lower()
            winreg.CloseKey(k)
            for kw in ("edge", "firefox", "opera", "brave", "vivaldi", "chrome"):
                if kw in prog_id:
                    return kw
        elif _OS == "Darwin":
            out = subprocess.run(
                ["defaults", "read",
                 "com.apple.LaunchServices/com.apple.launchservices.secure",
                 "LSHandlers"],
                capture_output=True, text=True, timeout=5,
            ).stdout.lower()
            for kw in ("firefox", "opera", "brave", "vivaldi", "safari", "chrome", "edge"):
                if kw in out:
                    return kw
        elif _OS == "Linux":
            out = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True, text=True, timeout=5,
            ).stdout.lower()
            for kw in ("firefox", "opera", "brave", "vivaldi", "chrome", "edge"):
                if kw in out:
                    return kw
    except Exception:
        pass
    return "chrome"


class _BrowserSession:
    """
    Bir tarayıcı örneği için tam oturum.
    Tüm tarayıcılar launch_persistent_context ile gerçek profil üzerinde açılır.
    """

    def __init__(self, browser_name: str):
        self.browser_name = browser_name
        self._spec        = _resolve_browser(browser_name)

        self._loop:    asyncio.AbstractEventLoop | None = None
        self._thread:  threading.Thread | None          = None
        self._ready    = threading.Event()

        self._pw:      Playwright     | None = None
        self._context: BrowserContext | None = None
        self._page:    Page           | None = None
        self._browser                  = None        # CDP-connected browser object (attach mode)
        self._cdp_port: int | None     = None        # set when attached to a running browser

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"BrowserThread-{self.browser_name}",
        )
        self._thread.start()
        self._ready.wait(timeout=20)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._async_init())
        self._ready.set()
        self._loop.run_forever()

    async def _async_init(self):
        self._pw = await async_playwright().start()

    def run(self, coro, timeout: int = 60) -> str:
        if not self._loop:
            raise RuntimeError(f"Session for '{self.browser_name}' not started.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def close(self):
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._async_close(), self._loop).result(10)

    async def _async_close(self):
        # CDP mode: closing the connected browser object only disconnects the
        # debugging session — the user's real browser keeps running untouched.
        if self._cdp_port and self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
            self._context = self._page = None
            self._cdp_port = None
            if self._pw:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
            return
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._context = self._page = None

    async def _launch(self):
        """
        Tarayıcıyı gerçek kullanıcı profiliyle başlatır.
        Context zaten açıksa hiçbir şey yapmaz.
        """
        if self._context is not None:
            return
        if self._cdp_port:
            return

        if self._spec is None:
            raise RuntimeError(
                f"'{self.browser_name}' bu platformda ({_OS}) desteklenmiyor."
            )

        engine_name = self._spec["engine"]
        exe         = self._spec["exe"]
        channel     = self._spec["channel"]
        engine_obj  = getattr(self._pw, engine_name)

        if engine_name == "firefox":
            profile = _firefox_profile_dir() or str(
                Path.home() / ".keysai_profiles" / "firefox"
            )
            kwargs: dict = {
                "headless":    False,
                "slow_mo":     0,
                "viewport":    None,
                "no_viewport": True,
            }
            if exe:
                kwargs["executable_path"] = exe
            try:
                self._context = await engine_obj.launch_persistent_context(profile, **kwargs)
            except Exception as e:
                print(f"[Browser] Firefox real profile failed ({e}), using Keys.ai profile")
                keysai_profile = str(Path.home() / ".keysai_profiles" / "firefox_keysai")
                Path(keysai_profile).mkdir(parents=True, exist_ok=True)
                self._context = await engine_obj.launch_persistent_context(keysai_profile, **kwargs)

            await asyncio.sleep(0.5)  
            self._page = await self._context.new_page()
            print(f"[Browser] ✅ Firefox launched")
            return

        if engine_name == "webkit":
            safari_profile = str(Path.home() / ".keysai_profiles" / "safari")
            Path(safari_profile).mkdir(parents=True, exist_ok=True)
            kwargs = {
                "headless":    False,
                "slow_mo":     0,
                "viewport":    None,
                "no_viewport": True,
            }
            self._context = await engine_obj.launch_persistent_context(safari_profile, **kwargs)
            await asyncio.sleep(0.5)
            self._page = await self._context.new_page()
            print(f"[Browser] ✅ Safari launched")
            return

        profile = _real_profile_dir(self.browser_name)

        kwargs = {
            "headless":    False,
            "slow_mo":     0,
            "viewport":    None,
            "no_viewport": True,
            "args": [
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--disable-default-apps",
                "--no-default-browser-check",
            ],
        }

        if exe:
            kwargs["executable_path"] = exe
        elif channel:
            kwargs["channel"] = channel

        label = (
            f"{self.browser_name}"
            + (f"/{channel}" if channel else "")
            + (f" @ {exe}" if exe else "")
        )

        try:
            self._context = await engine_obj.launch_persistent_context(profile, **kwargs)
            await asyncio.sleep(0.5) 
            self._page = await self._context.new_page()
            print(f"[Browser] ✅ Launched [{label}] profile={profile}")
            return
        except Exception as e:
            print(f"[Browser] ⚠️  Real profile failed for {label}: {e}")

        keysai_profile = str(Path.home() / ".keysai_profiles" / self.browser_name)
        Path(keysai_profile).mkdir(parents=True, exist_ok=True)
        print(f"[Browser] Retrying with Keys.ai profile: {keysai_profile}")

        try:
            self._context = await engine_obj.launch_persistent_context(keysai_profile, **kwargs)
            await asyncio.sleep(0.5)
            self._page = await self._context.new_page()
            print(f"[Browser] ✅ Launched [{label}] with Keys.ai profile")
        except Exception as e2:
            raise RuntimeError(f"Could not launch {self.browser_name}: {e2}") from e2


    async def _get_page(self) -> Page:
        await self._launch()
        # If somehow page got closed, open a fresh one
        if self._page is None or self._page.is_closed():
            self._page = await self._context.new_page()
            await asyncio.sleep(0.2)
        return self._page

    # ── CDP attach (drive the user's already-running browser) ───────────
    async def connect_cdp(self, port: int = 9222) -> bool:
        """Attach to a running Chromium browser over its remote-debugging port.
        Returns True when attached; the user's browser keeps running and every
        real tab becomes enumerable and controllable."""
        if self._context is not None and self._cdp_port:
            return True
        if self._context is not None:
            # Session already drives a launched window — don't clobber it.
            return False
        try:
            from playwright.async_api import async_playwright
            if self._pw is None:
                self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.connect_over_cdp(
                f"http://127.0.0.1:{int(port)}"
            )
            contexts = self._browser.contexts
            self._context = contexts[0] if contexts else await self._browser.new_context()
            pages = self._context.pages
            self._page = pages[0] if pages else await self._context.new_page()
            self._cdp_port = int(port)
            print(f"[Browser] ✅ Attached to running browser via CDP port {port} "
                  f"— {len(self._context.pages)} tab(s)")
            return True
        except Exception as e:
            self._browser = None
            self._context = None
            self._page = None
            self._cdp_port = None
            print(f"[Browser] ⚠️  CDP attach failed on port {port}: {e}")
            return False

    # ── tabs ────────────────────────────────────────────────────────────
    def _pages(self) -> list:
        if self._context is None:
            return []
        try:
            return [p for p in self._context.pages if not p.is_closed()]
        except Exception:
            return []

    async def _resolve_tab(self, index=None, title=None, url=None):
        """Resolve a tab by 0-based index or by title/URL fragment."""
        pages = self._pages()
        if not pages:
            return None
        if index is not None:
            try:
                i = int(index)
                if 0 <= i < len(pages):
                    return pages[i]
            except Exception:
                pass
        t = (title or "").lower()
        u = (url or "").lower()
        if t or u:
            for p in pages:
                try:
                    pt = (await p.title()).lower()
                except Exception:
                    pt = ""
                try:
                    pu = p.url.lower()
                except Exception:
                    pu = ""
                if (t and t in pt) or (u and u in pu):
                    return p
        return None

    async def list_tabs(self) -> str:
        pages = self._pages()
        if not pages:
            return "No open tabs in this browser session."
        current = self._page
        lines = []
        for i, p in enumerate(pages):
            try:
                title = (await p.title()) or "(untitled)"
            except Exception:
                title = "(untitled)"
            try:
                url = p.url or ""
            except Exception:
                url = ""
            active = " ◀ active" if (current is not None and p == current) else ""
            lines.append(f"{i:>2}. {title} — {url}{active}")
        return "Tabs in this browser:\n" + "\n".join(lines)

    async def switch_tab(self, index=None, title=None, url=None) -> str:
        p = await self._resolve_tab(index, title, url)
        if p is None:
            return (f"No tab matches index={index}, title='{title or ''}', "
                    f"url='{url or ''}' — run list_tabs first.")
        try:
            await p.bring_to_front()
        except Exception as e:
            return f"Could not bring tab to front: {e}"
        self._page = p
        try:
            t = await p.title()
        except Exception:
            t = "(untitled)"
        return f"Switched to tab: {t} — {p.url}"

    async def close_tab(self, index=None, title=None, url=None) -> str:
        """Close a specific tab (by index/title/url) — or the active one when no target given."""
        pages = self._pages()
        if not pages:
            return "No active tab to close."
        if index is None and not title and not url:
            target = self._page
        else:
            target = await self._resolve_tab(index, title, url)
            if target is None:
                return (f"No tab matches index={index}, title='{title or ''}', "
                        f"url='{url or ''}' — run list_tabs first.")
        if target is None or target.is_closed():
            return "No active tab to close."
        try:
            await target.close()
        except Exception as e:
            return f"Could not close tab: {e}"
        remaining = self._pages()
        if remaining and (self._page is None or self._page.is_closed()):
            self._page = remaining[0]
        elif not remaining:
            self._page = None
        return "Tab closed."

    async def tab_screenshot(self, path=None, index=None, title=None, url=None,
                             full_page=False) -> str:
        if index is not None or title or url:
            target = await self._resolve_tab(index, title, url)
        else:
            target = self._page
        if target is None or target.is_closed():
            return "No tab to capture — run list_tabs first."
        try:
            save_path = path or str(Path.home() / "Desktop" / "keysai_tab.png")
            if not Path(save_path).suffix:
                save_path += ".png"
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            await target.screenshot(path=save_path, full_page=bool(full_page))
            return f"Tab screenshot saved: {save_path}"
        except Exception as e:
            return f"Tab screenshot error: {e}"

    async def tab_text(self, index=None, title=None, url=None) -> str:
        if index is not None or title or url:
            target = await self._resolve_tab(index, title, url)
        else:
            target = await self._get_page()
        if target is None:
            return "No tab to read."
        try:
            text = (await target.inner_text("body") or "").strip()
            return text[:6_000] or "Page has no visible text."
        except Exception as e:
            return f"Could not read tab text: {e}"

    # ── per-component full access (inside a tab) ────────────────────────
    _COMPONENTS_JS = """() => {
      const INTEREST = new Set(['A','BUTTON','INPUT','TEXTAREA','SELECT','SUMMARY']);
      const ROLE_TAGS = new Set(['button','link','textbox','searchbox','checkbox','radio',
        'combobox','tab','menuitem','switch','slider','listbox','option','menu']);
      const out = [];
      const all = document.querySelectorAll('*');
      for (const el of all) {
        const tag = el.tagName.toLowerCase();
        const role = (el.getAttribute('role') || '').toLowerCase();
        let hit = INTEREST.has(tag.toUpperCase());
        if (role && ROLE_TAGS.has(role)) hit = true;
        if (!hit) continue;
        if (el.closest('[data-ksai-skip]')) continue;
        if (el.offsetParent === null && !(tag === 'input' && el.type === 'hidden')) continue;
        const id = el.id || '';
        const label = (el.getAttribute('aria-label') || '').trim();
        const placeholder = (el.getAttribute('placeholder') || '').trim();
        const title = (el.getAttribute('title') || '').trim();
        let name = label || placeholder || title || '';
        if (!name) {
          const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
          name = text.length <= 80 ? text : text.slice(0, 80) + '…';
        }
        el.setAttribute('data-ksai-index', String(out.length));
        out.push({ index: out.length, tag, role: role || null, name, id,
                   selector: cssPath(el),
                   disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true' });
      }
      function cssPath(el) {
        if (el.id) return '#' + CSS.escape(el.id);
        const parts = [];
        while (el && el.nodeType === 1 && parts.length < 5) {
          let sel = el.tagName.toLowerCase();
          if (el.id) { parts.unshift('#' + CSS.escape(el.id)); break; }
          const parent = el.parentElement;
          if (parent) {
            const same = Array.from(parent.children).filter(c => c.tagName === el.tagName);
            if (same.length > 1) sel += ':nth-of-type(' + (same.indexOf(el) + 1) + ')';
          }
          parts.unshift(sel);
          el = parent;
        }
        return parts.join(' > ');
      }
      return out;
    }"""

    async def components(self, limit: int = 120) -> str:
        page = await self._get_page()
        try:
            data = await page.evaluate(self._COMPONENTS_JS)
        except Exception as e:
            return f"Could not enumerate components: {e}"
        if not data:
            return "No interactive components detected on this page."
        lines = []
        for c in data[: int(limit)]:
            flags = []
            if c.get("role"):
                flags.append(f"role={c['role']}")
            if c.get("id"):
                flags.append(f"id={c['id']}")
            if c.get("disabled"):
                flags.append("disabled")
            flags_txt = (" " + " ".join(flags)) if flags else ""
            name = c.get("name") or c.get("tag") or ""
            lines.append(f"{c['index']:>3}. <{c['tag']}>{flags_txt} {name}")
        return "Components in this tab:\n" + "\n".join(lines)

    async def _component_locator(self, page, index=None, selector=None,
                                 description=None, text=None):
        """Resolve a component reference to a Playwright locator.
        Returns (locator, human-readable target) or (None, '')."""
        if index is not None:
            try:
                loc = page.locator(f'[data-ksai-index="{int(index)}"]')
                if await loc.count() > 0:
                    return loc.first, f"component #{index}"
            except Exception:
                pass
        if selector:
            try:
                loc = page.locator(selector).first
                if await loc.count() > 0:
                    return loc, f"selector '{selector}'"
            except Exception:
                pass
        if text:
            try:
                loc = page.get_by_text(text, exact=False).first
                if await loc.count() > 0:
                    return loc, f"text '{text}'"
            except Exception:
                pass
        if description:
            for role in ("button", "link", "searchbox", "textbox", "menuitem",
                         "tab", "checkbox", "combobox"):
                try:
                    loc = page.get_by_role(role, name=description, exact=False).first
                    if await loc.count() > 0:
                        return loc, f"{role} '{description}'"
                except Exception:
                    continue
            for method in ("placeholder", "label"):
                try:
                    loc = getattr(page, f"get_by_{method}")(description, exact=False).first
                    if await loc.count() > 0:
                        return loc, f"{method} '{description}'"
                except Exception:
                    continue
        return None, ""

    async def click_component(self, index=None, selector=None, text=None,
                              description=None) -> str:
        page = await self._get_page()
        loc, what = await self._component_locator(page, index, selector, description, text)
        if loc is None:
            return (f"Could not find component — index={index}, selector={selector or ''}, "
                    f"description={description or ''}. Run components first.")
        try:
            await loc.click(timeout=8_000)
            return f"Clicked {what}."
        except Exception as e:
            return f"Click on {what} failed: {e}"

    async def type_component(self, index=None, selector=None, description=None,
                             text="", clear_first=True) -> str:
        page = await self._get_page()
        loc, what = await self._component_locator(page, index, selector, description)
        if loc is None:
            return (f"Could not find input — index={index}, selector={selector or ''}, "
                    f"description={description or ''}. Run components first.")
        try:
            if clear_first:
                await loc.clear()
            await loc.type(text or "", delay=40)
            return f"Typed {len(text)} chars into {what}."
        except Exception as e:
            return f"Type into {what} failed: {e}"

    async def read_component(self, index=None, selector=None, description=None) -> str:
        page = await self._get_page()
        loc, what = await self._component_locator(page, index, selector, description)
        if loc is None:
            return (f"Could not find component — index={index}, selector={selector or ''}, "
                    f"description={description or ''}. Run components first.")
        try:
            info = await loc.evaluate("""(el) => {
                const isInput = el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'
                             || el.tagName === 'SELECT';
                return {
                  value: isInput ? (el.value ?? '') : (el.innerText || el.textContent || ''),
                  tag: el.tagName.toLowerCase(),
                  checked: el.checked !== undefined ? el.checked : null,
                  disabled: el.disabled !== undefined ? el.disabled : null,
                };
            }""")
            parts = []
            value = (info.get("value") or "").strip()
            if value:
                parts.append(f"value={value[:500]!r}")
            elif info.get("tag") == "input":
                parts.append("value=(empty)")
            if info.get("checked") is not None:
                parts.append(f"checked={info['checked']}")
            if info.get("disabled"):
                parts.append("disabled")
            return "Read " + what + ": " + (", ".join(parts) or "(no content)")
        except Exception as e:
            return f"Read failed: {e}"

    async def go_to(self, url: str) -> str:

        url      = _normalize_url(url)
        page     = await self._get_page()
        prev_url = page.url

        async def _do_goto(p: Page) -> str:
            """Attempt navigation and return the resulting URL (may still be blank)."""
            try:
                await p.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await asyncio.sleep(0.3)
            except PlaywrightTimeout:
                pass   # page may have partially loaded — check URL below
            except Exception as e:
                print(f"[Browser] goto exception (non-fatal): {e}")
            return p.url

        result_url = await _do_goto(page)

        if result_url in ("about:blank", "", None, prev_url) and prev_url in ("about:blank", "", None):
            print(f"[Browser] Still blank after goto — retrying on new tab: {url}")
            try:
                new_page   = await self._context.new_page()
                self._page = new_page
                result_url = await _do_goto(new_page)
            except Exception as e:
                print(f"[Browser] New-tab retry failed: {e}")

        if result_url and result_url not in ("about:blank", "", None):
            return f"Opened: {result_url}"
        return f"Could not open: {url}"

    async def search(self, query: str, engine: str = "google") -> str:
        _engines = {
            "google":     "https://www.google.com/search?q=",
            "bing":       "https://www.bing.com/search?q=",
            "duckduckgo": "https://duckduckgo.com/?q=",
            "yandex":     "https://yandex.com/search/?text=",
        }
        base = _engines.get(engine.lower(), _engines["google"])
        return await self.go_to(base + query.replace(" ", "+"))

    async def click(self, selector: str = None, text: str = None) -> str:
        page = await self._get_page()
        try:
            if text:
                await page.get_by_text(text, exact=False).first.click(timeout=8_000)
                return f"Clicked text: '{text}'"
            if selector:
                await page.click(selector, timeout=8_000)
                return f"Clicked selector: {selector}"
            return "No selector or text provided."
        except PlaywrightTimeout:
            return "Element not found (timeout)."
        except Exception as e:
            return f"Click error: {e}"

    async def type_text(self, selector: str = None, text: str = "",
                        clear_first: bool = True) -> str:
        page = await self._get_page()
        try:
            el = page.locator(selector).first if selector else page.locator(":focus")
            if clear_first:
                await el.clear()
            await el.type(text, delay=50)
            return "Text typed."
        except Exception as e:
            return f"Type error: {e}"

    async def scroll(self, direction: str = "down", amount: int = 500) -> str:
        page = await self._get_page()
        try:
            y = amount if direction == "down" else -amount
            await page.mouse.wheel(0, y)
            return f"Scrolled {direction}."
        except Exception as e:
            return f"Scroll error: {e}"

    async def press(self, key: str) -> str:
        page = await self._get_page()
        try:
            await page.keyboard.press(key)
            return f"Pressed: {key}"
        except Exception as e:
            return f"Key error: {e}"

    async def get_text(self) -> str:
        page = await self._get_page()
        try:
            text = await page.inner_text("body")
            return text[:4_000]
        except Exception as e:
            return f"Could not get page text: {e}"

    async def get_url(self) -> str:
        page = await self._get_page()
        return page.url

    async def fill_form(self, fields: dict) -> str:
        page    = await self._get_page()
        results = []
        for selector, value in fields.items():
            try:
                el = page.locator(selector).first
                await el.clear()
                await el.type(str(value), delay=40)
                results.append(f"✓ {selector}")
            except Exception as e:
                results.append(f"✗ {selector}: {e}")
        return "Form filled: " + ", ".join(results)

    async def smart_click(self, description: str) -> str:
        page = await self._get_page()
        for role in ("button", "link", "searchbox", "textbox", "menuitem", "tab"):
            try:
                loc = page.get_by_role(role, name=description)
                if await loc.count() > 0:
                    await loc.first.click(timeout=5_000)
                    return f"Clicked ({role}): '{description}'"
            except Exception:
                pass
        for attempt in (
            lambda: page.get_by_text(description, exact=False).first.click(timeout=5_000),
            lambda: page.get_by_placeholder(description, exact=False).first.click(timeout=5_000),
            lambda: page.locator(
                f'[alt*="{description}" i],[title*="{description}" i],'
                f'[aria-label*="{description}" i]'
            ).first.click(timeout=5_000),
        ):
            try:
                await attempt()
                return f"Clicked: '{description}'"
            except Exception:
                pass
        return f"Could not find element: '{description}'"

    async def smart_type(self, description: str, text: str) -> str:
        page = await self._get_page()
        candidates = [
            ("placeholder", page.get_by_placeholder(description, exact=False)),
            ("label",       page.get_by_label(description, exact=False)),
            ("role",        page.get_by_role("textbox", name=description)),
            ("searchbox",   page.get_by_role("searchbox")),
            ("combobox",    page.get_by_role("combobox", name=description)),
        ]
        for method, loc in candidates:
            try:
                el = loc.first
                if await el.count() == 0:
                    continue
                await el.clear()
                await el.type(text, delay=50)
                return f"Typed into ({method}): '{description}'"
            except Exception:
                continue
        return f"Could not find input: '{description}'"

    async def new_tab(self, url: str = "") -> str:
        page = await self._get_page()
        ctx  = page.context
        new  = await ctx.new_page()
        self._page = new
        if url:
            return await self.go_to(url)
        return "New tab opened."

    async def close_tab(self) -> str:
        page = self._page
        if page and not page.is_closed():
            ctx   = page.context
            await page.close()
            pages = ctx.pages
            self._page = pages[-1] if pages else None
            return "Tab closed."
        return "No active tab to close."

    async def screenshot(self, path: str = None) -> str:
        page = await self._get_page()
        try:
            save_path = path or str(Path.home() / "Desktop" / "keysai_screenshot.png")
            await page.screenshot(path=save_path, full_page=False)
            return f"Screenshot saved: {save_path}"
        except Exception as e:
            return f"Screenshot error: {e}"

    async def back(self) -> str:
        page = await self._get_page()
        try:
            await page.go_back(timeout=10_000)
            return f"Navigated back: {page.url}"
        except Exception as e:
            return f"Back error: {e}"

    async def forward(self) -> str:
        page = await self._get_page()
        try:
            await page.go_forward(timeout=10_000)
            return f"Navigated forward: {page.url}"
        except Exception as e:
            return f"Forward error: {e}"

    async def reload(self) -> str:
        page = await self._get_page()
        try:
            await page.reload(timeout=15_000)
            return f"Page reloaded: {page.url}"
        except Exception as e:
            return f"Reload error: {e}"

    async def close_browser(self) -> str:
        await self._async_close()
        return f"{self.browser_name} closed."

class _SessionRegistry:
    """Tüm aktif tarayıcı oturumlarını yönetir."""

    def __init__(self):
        self._sessions:       dict[str, _BrowserSession] = {}
        self._active_browser: str                        = ""
        self._lock            = threading.Lock()

    def _get_or_create(self, browser_name: str) -> _BrowserSession:
        with self._lock:
            if browser_name not in self._sessions:
                sess = _BrowserSession(browser_name)
                sess.start()
                self._sessions[browser_name] = sess
                print(f"[Registry] New session: {browser_name}")
            return self._sessions[browser_name]

    def get(self, browser_name: str | None = None) -> _BrowserSession:
        if not browser_name:
            browser_name = self._active_browser or _detect_default_browser()
        browser_name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
        sess = self._get_or_create(browser_name)
        self._active_browser = browser_name
        return sess

    def switch(self, browser_name: str) -> str:
        browser_name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
        self._get_or_create(browser_name)
        self._active_browser = browser_name
        return f"Active browser → {browser_name}"

    def attach(self, browser_name: str, port: int = 9222) -> str:
        """Try CDP attach to the running browser; fall back to opening a managed window."""
        browser_name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
        sess = self._get_or_create(browser_name)
        try:
            attached = sess.run(sess.connect_cdp(int(port)))
        except Exception as e:
            print(f"[Registry] attach failed: {e}")
            attached = False
        if attached:
            self._active_browser = browser_name
            return (f"Attached to the running {browser_name} over CDP (port {port}). "
                    "All its tabs are now controllable — run list_tabs.")
        try:
            if sess._context is not None:
                self._active_browser = browser_name
                return (f"Could not attach to a running {browser_name} (no CDP port {port}). "
                        "The managed browser window is already open and fully controlled.")
            sess.run(sess._launch())
            self._active_browser = browser_name
            return (f"Could not attach to a running {browser_name} (no CDP port {port}). "
                    "Opened a managed browser window on your profile instead — "
                    "fully controlled. Run list_tabs to see its tabs.")
        except Exception as e:
            return f"Could not attach or launch {browser_name}: {e}"

    def close_one(self, browser_name: str) -> str:
        with self._lock:
            sess = self._sessions.pop(browser_name, None)
        if sess:
            sess.close()
            if self._active_browser == browser_name:
                self._active_browser = ""
            return f"{browser_name} closed."
        return f"No active session for: {browser_name}"

    def close_all(self) -> str:
        with self._lock:
            names    = list(self._sessions.keys())
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._active_browser = ""
        for s in sessions:
            try:
                s.close()
            except Exception:
                pass
        return "All browsers closed: " + (", ".join(names) if names else "none")

    def list_sessions(self) -> str:
        with self._lock:
            if not self._sessions:
                return "No active browser sessions."
            lines = []
            for name in self._sessions:
                marker = " ◀ active" if name == self._active_browser else ""
                lines.append(f"  • {name}{marker}")
            return "Open browsers:\n" + "\n".join(lines)


_registry = _SessionRegistry()

def browser_control(
    parameters:    dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params  = parameters or {}
    action  = params.get("action", "").lower().strip()
    browser = params.get("browser", "").lower().strip() or None
    result  = "Unknown action."

    if action == "switch":
        target = browser or params.get("target", "").lower().strip()
        result = _registry.switch(target) if target else "Please specify a browser."
        _log(player, result)
        return result

    if action == "attach":
        target = browser or params.get("browser", "").lower().strip()
        port = int(params.get("port", 9222) or 9222)
        if not target:
            result = "Please specify a browser to attach (e.g. chrome, edge)."
        else:
            result = _registry.attach(target, port)
        _log(player, result)
        return result

    if action == "list_browsers":
        result = _registry.list_sessions()
        _log(player, result)
        return result

    if action == "close_all":
        result = _registry.close_all()
        _log(player, result)
        return result

    try:
        sess = _registry.get(browser)
    except Exception as e:
        result = f"Could not start browser session: {e}"
        _log(player, result)
        return result

    try:
        if action == "go_to":
            result = sess.run(sess.go_to(params.get("url", "")))
        elif action == "search":
            result = sess.run(sess.search(params.get("query", ""), params.get("engine", "google")))
        elif action == "click":
            result = sess.run(sess.click(params.get("selector"), params.get("text")))
        elif action == "type":
            result = sess.run(sess.type_text(
                params.get("selector"), params.get("text", ""), params.get("clear_first", True)))
        elif action == "scroll":
            result = sess.run(sess.scroll(params.get("direction", "down"), int(params.get("amount", 500))))
        elif action == "fill_form":
            result = sess.run(sess.fill_form(params.get("fields", {})))
        elif action == "smart_click":
            result = sess.run(sess.smart_click(params.get("description", "")))
        elif action == "smart_type":
            result = sess.run(sess.smart_type(params.get("description", ""), params.get("text", "")))
        elif action == "get_text":
            result = sess.run(sess.get_text())
        elif action == "get_url":
            result = sess.run(sess.get_url())
        elif action == "press":
            result = sess.run(sess.press(params.get("key", "Enter")))
        elif action == "new_tab":
            result = sess.run(sess.new_tab(params.get("url", "")))
        elif action == "close_tab":
            result = sess.run(sess.close_tab(
                _opt_index(params.get("index")), params.get("title"), params.get("url")))
        elif action == "list_tabs":
            result = sess.run(sess.list_tabs())
        elif action == "switch_tab":
            result = sess.run(sess.switch_tab(
                _opt_index(params.get("index")), params.get("title"), params.get("url")))
        elif action == "components":
            result = sess.run(sess.components())
        elif action == "click_component":
            result = sess.run(sess.click_component(
                _opt_index(params.get("index")), params.get("selector"),
                params.get("text"), params.get("description")))
        elif action == "type_component":
            result = sess.run(sess.type_component(
                _opt_index(params.get("index")), params.get("selector"),
                params.get("description"), params.get("text", ""),
                bool(params.get("clear_first", True))))
        elif action == "read_component":
            result = sess.run(sess.read_component(
                _opt_index(params.get("index")), params.get("selector"),
                params.get("description")))
        elif action == "tab_screenshot":
            result = sess.run(sess.tab_screenshot(
                params.get("path"), _opt_index(params.get("index")),
                params.get("title"), params.get("url"),
                bool(params.get("full_page", False))))
        elif action == "tab_text":
            result = sess.run(sess.tab_text(
                _opt_index(params.get("index")), params.get("title"), params.get("url")))
        elif action == "screenshot":
            result = sess.run(sess.screenshot(params.get("path")))
        elif action == "back":
            result = sess.run(sess.back())
        elif action == "forward":
            result = sess.run(sess.forward())
        elif action == "reload":
            result = sess.run(sess.reload())
        elif action == "close":
            target = browser or _registry._active_browser
            result = _registry.close_one(target) if target else "No browser specified."
        else:
            result = f"Unknown browser action: '{action}'"

    except concurrent.futures.TimeoutError:
        result = f"Browser action '{action}' timed out (60s)."
    except Exception as e:
        result = f"Browser error ({action}): {e}"

    _log(player, result)
    return result


def _log(player, text: str):
    short = str(text)[:80]
    print(f"[Browser] {short}")
    if player:
        player.write_log(f"[browser] {short[:60]}")


def _opt_index(v):
    """Parse an optional 0-based tab/component index; None when absent/invalid."""
    if v in (None, "", "None"):
        return None
    try:
        return int(v)
    except Exception:
        return None