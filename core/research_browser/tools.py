"""Agent tools for the Research Browser.

Every action here targets the same live page the user sees. Tab ids are explicit:
an agent call without ``tab_id`` uses the active tab and reports which one it
used, so a tool can never silently act on "whichever tab happened to be first".

The handler signature matches ``core/tool_registry.py`` — (parameters, ui,
speak) → user-facing string — so the voice assistant and the Project Agent can
call it without a second integration layer.
"""

from __future__ import annotations

import json
import uuid

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication

from core.research_browser import collector, integration, library, urls

# How long the calling thread waits for the GUI thread to finish a browser
# action. Navigate/page-text already carry their own shorter page timeouts.
_GUI_TIMEOUT = 180.0


def _gui_runner(player):
    """The UI's GUI-thread runner, in whichever shape the caller passed.

    main.py hands tools the thread-safe KeysAIUI wrapper; the runner lives on
    MainWindow inside it, and both expose the same method.
    """
    for candidate in (player, getattr(player, "_win", None)):
        runner = getattr(candidate, "run_on_gui_thread", None)
        if callable(runner):
            return runner
    return None


def _on_gui_thread(fn, player=None):
    """Run `fn` on the Qt GUI thread and return its result.

    QtWebEngine is GUI-thread-only: a profile, page or view created (or
    navigated) from a worker thread fails Chromium's CalledOnValidBrowserThread
    check and aborts the whole process — no exception, no traceback, the app
    simply disappears. main.py dispatches every registry tool through
    ``run_in_executor``, so every browser tool arrives off-thread and has to
    hop onto the GUI thread before it touches a page.
    """
    app = QApplication.instance()
    if app is None or QThread.currentThread() is app.thread():
        return fn()                  # no Qt, or already where we need to be

    runner = _gui_runner(player)
    if runner is None:
        # Refusing beats aborting: without the UI there is no way to reach the
        # GUI thread, and touching a page from here would kill the process.
        raise RuntimeError(
            "The research browser needs the Keys.AI UI to run its page work "
            "on the Qt thread."
        )
    return runner(fn, _GUI_TIMEOUT)


def _service():
    from core.research_browser import get_service
    return get_service()


def _short(value, limit: int = 1600) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


_UI = None


def register_ui(ui) -> None:
    """Remember the main window so non-UI callers (workers) can reach Qt.

    The Project Agent runs on worker threads with no ``player`` argument, and
    QtWebEngine may only be touched from the GUI thread — this is how they get
    there. Registering a window the agent already has is not a new privilege:
    every browser action still goes through the same service and the same page.
    """
    global _UI
    _UI = ui


def _palette(path, colors: int = 6) -> list[str]:
    """The dominant colours of a saved screenshot, as hex.

    Read from the real pixels (quantised), not from a guess about the site, and
    an empty list when Pillow cannot read the file — a failed palette must not
    look like a design decision.
    """
    try:
        from PIL import Image
        with Image.open(path) as im:
            small = im.convert("RGB").resize((80, 80))
            quantised = small.quantize(colors=colors)
            table = quantised.getpalette() or []
            out: list[str] = []
            for count, index in sorted(quantised.getcolors() or [], reverse=True):
                base = index * 3
                if base + 2 >= len(table):
                    continue
                hexcode = "#{:02x}{:02x}{:02x}".format(*table[base:base + 3])
                if hexcode not in out:
                    out.append(hexcode)
                if len(out) >= colors:
                    break
            return out
    except Exception:
        return []


def capture_reference(url: str, dest_dir: str = "", player=None) -> dict:
    """Screenshot a URL in the app's own browser; return its palette.

    Used by the Project Agent's design-reference preset. Returns
    ``{"ok", "screenshot", "palette", "url"}`` — real pixels from the shared
    browser engine, or an explicit error, never a described screenshot.
    """
    ui = player or _UI

    def work() -> dict:
        from pathlib import Path
        service = _service()
        _ensure_visible(ui)
        tab_id = service.open_tab(str(url))
        service.wait_for_load(tab_id, timeout=20.0)
        target_dir = Path(dest_dir) if dest_dir else None
        if target_dir is not None:
            target_dir.mkdir(parents=True, exist_ok=True)
            dest = str(target_dir / f"ref_{uuid.uuid4().hex[:8]}.png")
        else:
            dest = ""
        shot = service.capture_screenshot(tab_id, dest=dest)
        if not shot.get("ok"):
            return {"ok": False, "error": str(shot.get("error") or "capture failed"),
                    "url": str(url)}
        path = str(shot.get("path") or "")
        return {"ok": True, "screenshot": path, "palette": _palette(path),
                "url": str(url), "title": shot.get("title") or ""}

    return _on_gui_thread(work, ui)


def _ensure_visible(ui) -> None:
    """Open the workspace when the agent needs the page on screen."""
    opener = getattr(ui, "_open_research_browser", None)
    if not callable(opener):
        # main.py hands tools the thread-safe KeysAIUI wrapper; the overlay
        # opener lives on the MainWindow it wraps.
        opener = getattr(getattr(ui, "_win", None), "_open_research_browser", None)
    if callable(opener):
        try:
            opener()
        except Exception:
            pass


def _tab(params: dict) -> str:
    service = _service()
    tab_id = str(params.get("tab_id") or "").strip()
    if tab_id and tab_id not in {t["tab_id"] for t in service.tabs()}:
        raise ValueError(f"Unknown tab id: {tab_id}")
    return tab_id or service.active_tab()


def execute(parameters: dict | None = None, player=None, speak=None) -> str:
    """Registry entry point — always runs the action on the Qt GUI thread."""
    return _on_gui_thread(lambda: _execute(parameters, player, speak), player)


def _execute(parameters: dict | None = None, player=None, speak=None) -> str:
    params = dict(parameters or {})
    action = str(params.get("action") or "state").strip().lower()
    service = _service()

    if action in ("list_tabs", "tabs"):
        tabs = service.tabs()
        if not tabs:
            return "The research browser has no tabs yet."
        return "\n".join(
            f"{'●' if t['active'] else '○'} {t['tab_id']}  {t['title'][:60]}  "
            f"{t['url']}" for t in tabs)

    if action in ("open", "open_browser", "show"):
        # The browser has no launcher button; this is how text and voice open it.
        _ensure_visible(player)
        state = service.state(_tab(params)) if service.tabs() else {}
        url = str(state.get("url") or "")
        if url and url != "about:blank":
            return f"The research browser is open, showing {url}"
        return ("The research browser is open with no page loaded yet. "
                "Tell me a site or a question to research.")

    if action in ("new_tab", "open_tab"):
        _ensure_visible(player)
        tab_id = service.open_tab(params.get("url", ""))
        return f"Opened a research browser tab ({tab_id})."

    if action == "navigate_to_url":
        _ensure_visible(player)
        target = params.get("url") or params.get("query") or ""
        tab_id = _tab(params) if service.tabs() else service.open_tab("")
        result = service.navigate(tab_id, target, timeout=float(params.get("timeout") or 20))
        if not result.get("ok"):
            return f"Could not navigate: {result.get('error')}"
        state = service.state(result["tab_id"])
        return (f"Opened {state.get('url')}\nTitle: {state.get('title')}\n"
                f"Tab: {result['tab_id']}")

    if action == "request_human_takeover":
        tab = _tab(params)
        result = service.request_human_takeover(tab, params.get("reason", ""))
        return result.get("message") or result.get("error", "")

    if action in ("release_takeover", "resume"):
        return service.release_takeover(_tab(params)).get("message",
                                                          "Control returned to the agent.")

    if action in ("close_browser_tab", "close_tab"):
        result = service.close_tab(_tab(params))
        return "Tab closed." if result.get("ok") else result.get("error", "Failed.")

    if action == "copy_current_url":
        state = service.state(_tab(params))
        if not state.get("ok"):
            return state.get("error", "No page.")
        try:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(state["url"])
            copied = True
        except Exception:
            copied = False
        return (f"{'Copied' if copied else 'Current URL'}: {state['url']}")

    handlers = {
        "go_back": lambda: service.go_back(_tab(params)),
        "go_forward": lambda: service.go_forward(_tab(params)),
        "reload_page": lambda: service.reload_page(_tab(params)),
        "stop_navigation": lambda: service.stop_navigation(_tab(params)),
        "get_current_page": lambda: service.state(_tab(params)),
        "get_page_title": lambda: service.page_title(_tab(params)),
        "get_page_text": lambda: service.page_text(_tab(params)),
        "get_page_structure": lambda: service.page_structure(_tab(params)),
        "find_page_elements": lambda: service.find_page_elements(
            _tab(params), params.get("selector", ""),
            int(params.get("limit") or 50)),
        "click_element": lambda: service.click_element(
            _tab(params), selector=params.get("selector", ""),
            index=int(params.get("index") or 0),
            text=params.get("text", "")),
        "fill_input": lambda: service.fill_input(
            _tab(params), params.get("selector", ""),
            params.get("text", params.get("value", "")),
            submit=bool(params.get("submit"))),
        "select_option": lambda: service.select_option(
            _tab(params), params.get("selector", ""), params.get("value", "")),
        "scroll_page": lambda: service.scroll_page(
            _tab(params), params.get("direction", "down"),
            int(params.get("amount") or 600)),
        "wait_for_element": lambda: service.wait_for_element(
            _tab(params), params.get("selector", ""),
            float(params.get("timeout") or 10)),
        "extract_selected_content": lambda: service.extract_selection(_tab(params)),
        "list_page_images": lambda: service.list_page_images(_tab(params)),
        "inspect_image_resource": lambda: service.inspect_image_resource(
            _tab(params), params.get("url", "")),
        "capture_screenshot": lambda: _capture(params, full_page=False),
        "capture_full_page": lambda: _capture(params, full_page=True),
        "download_resource": lambda: _download(params),
        "save_source": lambda: collector.save_source(
            service, _tab(params), params.get("task_id", ""),
            question=params.get("question", "")),
        "collect_image": lambda: collector.collect_image(
            service, _tab(params), params.get("url", ""),
            task_id=params.get("task_id", ""),
            license_status=params.get("license_status", "unknown"),
            attribution=params.get("attribution", ""),
            approve=bool(params.get("approve"))),
        "collect_selection": lambda: collector.collect_selection(
            service, _tab(params), task_id=params.get("task_id", ""),
            claim=params.get("text", ""), question=params.get("question", "")),
        "collect_table": lambda: collector.collect_table(
            service, _tab(params), int(params.get("index") or 0),
            task_id=params.get("task_id", "")),
        "add_asset_to_project": lambda: _add_to_project(params),
        "list_sources": lambda: {"ok": True,
                                 "sources": library.list_sources(params.get("task_id", ""))},
        "list_assets": lambda: {"ok": True,
                                "assets": library.list_assets(params.get("task_id", ""))},
        "research_coverage": lambda: {"ok": True,
                                      "coverage": library.coverage(params.get("task_id", ""))},
    }
    handler = handlers.get(action)
    if handler is None:
        return (f"Unknown research browser action '{action}'. Available: "
                + ", ".join(sorted(set(list(handlers) + [
                    "navigate_to_url", "new_tab", "list_tabs",
                    "request_human_takeover", "copy_current_url",
                    "close_browser_tab"]))))
    try:
        result = handler()
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return f"Research browser action failed: {exc}"
    return _render(action, result)


def _capture(params: dict, *, full_page: bool) -> dict:
    tab = _tab(params)
    _ensure_visible(None)
    dest = str(params.get("path") or "")
    return collector.capture(_service(), tab, task_id=params.get("task_id", ""),
                             full_page=full_page, element=params.get("selector", "")) \
        if not dest else _service().capture_screenshot(
            tab, full_page=full_page, element=params.get("selector", ""),
            dest=dest)


def _download(params: dict) -> dict:
    from core.research_browser import assets
    url = params.get("url") or ""
    if not url:
        raise ValueError("download_resource needs a URL.")
    try:
        fetched = assets.fetch(url, task_id=params.get("task_id", ""),
                               expect=params.get("expect", "image"))
    except assets.AssetError as exc:
        return {"ok": False, "error": str(exc)}
    record = library.add_asset(
        fetched["path"], source_url=url, task_id=params.get("task_id", ""),
        width=fetched["width"], height=fetched["height"],
        fmt=fetched["format"], size_bytes=fetched["bytes"],
        sha256=fetched["sha256"], license_status=params.get("license_status", "unknown"),
        attribution=params.get("attribution", ""), filename=fetched["filename"],
        kind=fetched["kind"], captured_at=fetched["retrieved_at"])
    return {"ok": True, "asset": record, "fetched": fetched}


def _add_to_project(params: dict) -> dict:
    asset_id = params.get("asset_id") or ""
    root = params.get("project_root") or ""
    if not root:
        raise ValueError("add_asset_to_project needs a project_root.")
    if asset_id:
        asset = library.get_asset(asset_id)
        if asset is None:
            return {"ok": False, "error": f"Unknown asset: {asset_id}"}
        path = asset["path"]
    else:
        path = params.get("path") or ""
    result = integration.add_to_project(
        path, root, kind=params.get("kind", ""),
        alt=params.get("alt", ""), caption=params.get("caption", ""),
        page=params.get("page", ""))
    if result.get("ok") and asset_id:
        library.link_usage(asset_id, result.get("dest", ""), role="embedded")
    return result


def _render(action: str, result: dict) -> str:
    if not isinstance(result, dict):
        return str(result)
    if not result.get("ok"):
        return f"{action} failed: {result.get('error', 'unknown error')}"
    if action == "get_page_text":
        return (f"{result.get('title')} — {result.get('url')}\n"
                f"{_short(result.get('text', ''))}")
    if action == "get_current_page":
        return (f"{result.get('title')}\n{result.get('url')}\n"
                f"loading: {result.get('loading')}  "
                f"back: {result.get('can_go_back')}  "
                f"forward: {result.get('can_go_forward')}")
    if action == "capture_screenshot" or action == "capture_full_page":
        return (f"Saved {result.get('width')}×{result.get('height')} screenshot "
                f"of {result.get('url')} to {result.get('path')}")
    if action == "save_source":
        source = result.get("source") or {}
        return (f"Saved source {source.get('source_id')}: {source.get('title')}\n"
                f"{source.get('url')}\nscreenshot: {result.get('screenshot') or 'none'}")
    if action in ("collect_image", "download_resource"):
        asset = result.get("asset") or {}
        return (f"Collected {asset.get('asset_id')} "
                f"({asset.get('width')}×{asset.get('height')} "
                f"{asset.get('format')}, licence {asset.get('license_status')})\n"
                f"file: {asset.get('path')}\nsource: {asset.get('source_url')}")
    if action == "add_asset_to_project":
        return (f"Integrated into {result.get('dest')} as "
                f"{result.get('reference')} (verified: {result.get('verified')})")
    if action in ("list_page_images",):
        images = result.get("images") or []
        return "\n".join(f"{i + 1}. {img.get('width')}×{img.get('height')} "
                         f"{img.get('alt', '')[:40]} {img.get('src', '')}"
                         for i, img in enumerate(images[:30])) or "No images found."
    if action in ("find_page_elements",):
        out = []
        for el in (result.get("elements") or [])[:30]:
            out.append(f"{el.get('index')}. <{el.get('tag')}> "
                       f"{el.get('text') or el.get('name') or ''}"
                       f" {el.get('href') or ''}".strip())
        return "\n".join(out) or "No matching elements."
    if action == "research_coverage":
        coverage = result.get("coverage") or {}
        return json.dumps(coverage, indent=2)
    return _short(result)


__all__ = ["execute", "capture_reference", "register_ui"]
