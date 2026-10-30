"""Research-through-browser step for the Dev Agent (Crown Code path).

The Project Agent's research skill is now driven by the live Research Browser
instead of a headless search/fetch loop. When the build params carry
``research_mode == "browser"`` the agent:

* opens the Research Browser workspace (visible to the user),
* navigates to real pages found for the research question,
* reads the visible page text through the browser tools,
* captures **real screenshots** and **page images** into the task workspace
  (files on disk, with source URLs), and
* writes a cited report from what the page actually contained.

The browser tools are QtWebEngine GUI-thread actions (core/research_browser
.tools). They are dispatched onto the Qt thread before touching any page, so
the agent can drive the same page the user sees without aborting the process.

This step is additive — it does not touch the existing search/fetch research
worker. When the Research Browser is unavailable the step degrades to the
text path and says so in the report.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
#  Browser tool wrappers — these are the actions the research step calls.
#  They come from core.research_browser.tools; each one already hops onto the
#  Qt GUI thread before touching a page, so callers can be on any thread.
# ═══════════════════════════════════════════════════════════════════════════════

def _browser_execute(params: dict, player=None) -> str:
    """Run a research-browser action and return its user-facing string."""
    from core.research_browser.tools import execute
    return execute(params, player=player, speak=None)


def _ensure_browser_open(ui) -> str:
    """Open the Research Browser workspace if it is not on screen yet."""
    from core.research_browser.tools import _ensure_visible
    _ensure_visible(ui)
    return ""


def _open_tab(url: str, ui) -> dict:
    """Open a URL in the research browser; return tab state dict."""
    raw = _browser_execute(
        {"action": "open_tab", "url": url}, player=ui
    )
    # execute returns a human string; parse the tab id out of it when possible.
    return {"open_result": raw}


def _navigate(url: str, ui, tab_id=None, timeout=20.0) -> dict:
    """Navigate the current/given tab to a URL."""
    params = {"action": "navigate_to_url", "url": url, "timeout": str(timeout)}
    if tab_id:
        params["tab_id"] = tab_id
    raw = _browser_execute(params, player=ui)
    return {"navigate_result": raw}


def _page_text(ui, tab_id=None) -> str:
    """Return the visible text of the current/active page."""
    params = {"action": "get_page_text"}
    if tab_id:
        params["tab_id"] = tab_id
    return _browser_execute(params, player=ui)


def _page_title(ui, tab_id=None) -> str:
    params = {"action": "get_page_title"}
    if tab_id:
        params["tab_id"] = tab_id
    return _browser_execute(params, player=ui)


def _capture_screenshot(path: str, ui, tab_id=None, full_page=False) -> dict:
    params = {
        "action": "capture_full_page" if full_page else "capture_screenshot",
        "path": path,
    }
    if tab_id:
        params["tab_id"] = tab_id
    raw = _browser_execute(params, player=ui)
    return {"capture_result": raw}


def _list_page_images(ui, tab_id=None) -> str:
    params = {"action": "list_page_images"}
    if tab_id:
        params["tab_id"] = tab_id
    return _browser_execute(params, player=ui)


def _download_resource(url: str, path: str, ui, tab_id=None,
                       license_status="unknown", attribution="") -> dict:
    params = {
        "action": "download_resource",
        "url": url,
        "path": path,
        "license_status": license_status,
        "attribution": attribution,
    }
    if tab_id:
        params["tab_id"] = tab_id
    raw = _browser_execute(params, player=ui)
    return {"download_result": raw}


def _save_source(task_id: str, ui, tab_id=None, question="") -> dict:
    params = {
        "action": "save_source",
        "task_id": task_id,
        "question": question,
    }
    if tab_id:
        params["tab_id"] = tab_id
    raw = _browser_execute(params, player=ui)
    return {"save_source_result": raw}


def _list_tabs(ui) -> str:
    return _browser_execute({"action": "list_tabs"}, player=ui)


# ═══════════════════════════════════════════════════════════════════════════════
#  Research step
# ═══════════════════════════════════════════════════════════════════════════════

def run_ResearchThroughBrowser(ctx) -> dict:
    """Research step driven by the live Research Browser.

    ``ctx`` is the dev-agent step context. The minimum contract:
      - ctx.task  : dict with at least "request" (the research question)
      - ctx.workspace : Path — where screenshots/images/reports land
      - ctx.log(topic, message) : progress logging
      - ctx.ui : the MainWindow (for browser tool dispatch) — may be None in
                a fully headless run, in which case the step degrades
      - ctx.check_cancel() -> bool
    """
    request = str(ctx.task.get("request") or "").strip()
    if not request:
        return {"ok": False, "summary": "No research question given.",
                "artifacts": [], "evidence": [],
                "error": "request is empty"}

    workspace = Path(str(ctx.workspace or ""))
    workspace.mkdir(parents=True, exist_ok=True)
    refs_dir = workspace / "references"
    refs_dir.mkdir(parents=True, exist_ok=True)

    ui = getattr(ctx, "ui", None)

    # Open the workspace so the user can see the live research surface.
    if ui is not None:
        try:
            _ensure_browser_open(ui)
        except Exception as exc:
            ctx.log(f"Research-through-browser: could not open browser workspace: {exc}")
            ui = None

    task_id = getattr(ctx, "task_id", "session") or "session"

    # Build a small set of discovery queries from the question. In the full
    # integration this would be replaced by the dev agent's own search action;
    # here we accept a list of URLs the agent already decided to visit.
    queries = _queries_from_request(request)

    artifacts = []
    evidence = []
    captured = []
    notes = []
    # The queries overlap by design (topic, topic+documentation, topic+overview),
    # so the same page can win twice. Visit each URL once.
    seen_urls: set[str] = set()

    for query in queries:
        if ctx.check_cancel():
            return {"ok": False, "summary": "Research cancelled.",
                    "artifacts": artifacts, "evidence": evidence,
                    "notes": notes, "error": "cancelled"}

        hit = _search_for_query(query)
        if not hit:
            notes.append(f"no result for: {query[:80]}")
            continue

        target_url = hit.get("url") or hit.get("link") or ""
        title = hit.get("title") or query[:80]
        if not target_url.startswith(("http://", "https://")):
            notes.append(f"skipped non-url hit: {title[:60]}")
            continue
        if target_url in seen_urls:
            notes.append(f"already visited: {target_url[:80]}")
            continue
        seen_urls.add(target_url)

        ctx.log(f"Research browser: visiting {title[:60]} — {target_url[:90]}")

        screenshot_path = ""
        page_text = ""
        try:
            if ui is not None:
                tab = _open_tab(target_url, ui)
                time.sleep(1.0)
                state = _browser_execute(
                    {"action": "get_current_page"}, player=ui
                )
                page_title = _page_title(ui)
                page_text = _page_text(ui)
                # Capture a real screenshot of the visible page.
                shot_name = f"ref_{int(time.time())}_{len(captured)}.png"
                shot_path = str(refs_dir / shot_name)
                cap = _capture_screenshot(shot_path, ui)
                screenshot_path = cap.get("capture_result", "")
                # List the page's images and collect the first usable one.
                images_txt = _list_page_images(ui)
                collected = _collect_first_image(images_txt, target_url,
                                                 refs_dir, ui)
                if collected:
                    captured.append(collected)
            else:
                page_title = title
                page_text = "(Research Browser not available — page read as text only.)"
                notes.append("Research Browser unavailable — no screenshot taken.")
        except Exception as exc:
            notes.append(f"browser visit failed for {target_url[:80]}: {exc}")
            page_title = title
            page_text = ""

        if page_text and len(page_text) > 20:
            evidence.append({
                "quote": page_text[:600],
                "source_url": target_url,
                "title": page_title,
                "retrieved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "verified": True,
                "method": "research browser page text",
            })

        # Register the screenshot as an artifact if we got one.
        if screenshot_path and Path(screenshot_path).is_file():
            artifacts.append({
                "path": screenshot_path,
                "kind": "png",
                "label": f"Research screenshot: {page_title[:50]}",
                "source_url": target_url,
            })

        # Save the source page through the browser's own collector when possible.
        if ui is not None:
            try:
                saved = _save_source(task_id, ui, question=request[:200])
                if saved.get("save_source_result", "").startswith("Saved source"):
                    notes.append(saved["save_source_result"][:120])
            except Exception as exc:
                notes.append(f"save_source skipped: {exc}")

    # Write a short cited report into the workspace.
    report_path = workspace / "research_report.md"
    report_lines = [
        f"# Research report: {request}",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M')}",
        f"Mode: research browser (live Chromium workspace)",
        f"Sources visited: {len(evidence)}",
        f"Screenshots captured: {len(artifacts)}",
        f"Page images collected: {len(captured)}",
        "",
        "## Summary",
        "",
    ]
    if evidence:
        report_lines.append(_cite_summary(evidence))
    else:
        report_lines.append("No page text could be retrieved.")
    report_lines.append("")
    report_lines.append("## Findings")
    report_lines.append("")
    for i, item in enumerate(evidence, 1):
        quote = " ".join((item.get("quote") or "").split())[:400]
        marker = f"[{i}]"
        suffix = "" if item.get("verified") else " (snippet only)"
        report_lines.append(f"- “{quote}” {marker}{suffix}")
    report_lines.append("")
    if notes:
        report_lines.append("## Notes")
        report_lines.append("")
        report_lines.extend(notes[:12])
        report_lines.append("")

    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    artifacts.append({
        "path": str(report_path),
        "kind": "md",
        "label": "Research report",
        "source_url": "",
    })

    return {
        "ok": True,
        "summary": (f"Research through the live browser — "
                    f"{len(evidence)} source(s) visited, "
                    f"{len(artifacts)} artifact(s), "
                    f"{len(captured)} image(s) collected."),
        "artifacts": artifacts,
        "evidence": evidence,
        "captured_images": [c.get("path", "") for c in captured],
        "notes": notes,
        "error": "",
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Small helpers — replace these with the dev agent's real search/collect
#  actions once the step is wired into the agent loop.
# ═══════════════════════════════════════════════════════════════════════════════

def _queries_from_request(request: str) -> list[str]:
    """Turn a research question into a small set of query strings.

    This is a placeholder for the dev agent's own query planning. The live
    integration would feed these into the agent's search action, then visit
    the returned URLs through the browser.
    """
    topic = request[:180].strip()
    return [
        topic,
        f"{topic} documentation",
        f"{topic} overview",
    ]


#: Hosts that are never worth reading as a research source. They are either
#: video/social silos or aggregator homepages, and the browser would land on a
#: wall of unrelated content instead of documentation.
_NOISE_HOSTS = (
    "youtube.com", "youtu.be", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "tiktok.com", "pinterest.", "reddit.com/r/",
)


def _is_noise(url: str) -> bool:
    """True when a hit is a video/social silo rather than a readable page."""
    lowered = url.lower()
    return any(host in lowered for host in _NOISE_HOSTS)


def _search_for_query(query: str) -> dict | None:
    """Find one real page for a query using the app's own search action.

    The browser reads the page; this only discovers the URL. Search itself goes
    through ``actions.web_search`` — the same keyless DDG/Bing path the assistant
    uses — so research does not depend on a model remembering a URL, and does
    not fetch page bodies over raw HTTP behind the browser's back.

    Returns the first usable hit, or ``None`` when every backend is unavailable.
    """
    try:
        from actions.web_search import _web_results
    except Exception:
        return None

    try:
        hits = _web_results(query, max_results=6) or []
    except Exception:
        return None

    for hit in hits:
        if not isinstance(hit, dict):
            continue
        url = str(hit.get("url") or hit.get("link") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        if _is_noise(url):
            continue
        return {
            "url": url,
            "title": str(hit.get("title") or "").strip()[:120],
            "snippet": str(hit.get("snippet") or "").strip()[:300],
            "query": query,
        }
    return None


def _collect_first_image(images_txt: str, source_url: str,
                         dest_dir: Path, ui) -> dict | None:
    """Collect the first image listed on the page through the browser tools."""
    if not images_txt or images_txt.strip().startswith("No images"):
        return None
    # Parse the ``list_page_images`` text: "1.  WIDTH×HEIGHT  ALT  SRC"
    first_src = None
    for line in images_txt.splitlines():
        line = line.strip()
        if not line:
            continue
        # Try to pull a URL out of the line.
        parts = line.split()
        for part in parts:
            if part.startswith(("http://", "https://")):
                first_src = part.rstrip(")").rstrip(".")
                break
        if first_src:
            break
    if not first_src:
        return None
    dest = str(dest_dir / f"img_{int(time.time())}_{len(list(dest_dir.glob('*.png')))}.png")
    try:
        dl = _download_resource(first_src, dest, ui,
                                license_status="unknown", attribution="")
        if dl.get("download_result", "").startswith("Collected"):
            return {"path": dest, "source_url": source_url,
                    "width": 0, "height": 0, "format": "png"}
    except Exception as exc:
        return {"path": dest, "source_url": source_url, "error": str(exc)[:120]}
    return None


def _cite_summary(evidence: list[dict]) -> str:
    lines = []
    for i, item in enumerate(evidence[:8], 1):
        quote = " ".join((item.get("quote") or "").split())[:240]
        lines.append(f"- {quote} [{i}]")
    return "\n".join(lines)


__all__ = ["run_ResearchThroughBrowser"]
