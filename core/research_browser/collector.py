"""Collecting research from the page the user is actually looking at.

Each function takes the live :class:`BrowserService` and a tab id, reads the
real page, and stores records only for things that were genuinely retrieved:
a source is "inspected" because its text and screenshot were captured, an asset
exists because its bytes were downloaded and decoded, and an evidence record
carries the excerpt it came from.
"""

from __future__ import annotations

import time
from pathlib import Path

from core.research_browser import assets, library, paths


def _workspace(task_id: str) -> Path:
    return paths.task_workspace(task_id)


def save_source(service, tab_id: str, task_id: str = "", *,
                question: str = "", screenshot: bool = True,
                excerpt_chars: int = 2500) -> dict:
    """Record the current page as a research source (with real evidence)."""
    state = service.state(tab_id)
    if not state.get("ok"):
        return {"ok": False, "error": state.get("error", "Unknown tab.")}
    url = state.get("url") or ""
    if not url or url == "about:blank":
        return {"ok": False, "error": "Open a page before saving a source."}
    if state.get("error"):
        # Chromium draws an error page, but nothing was retrieved from the site.
        return {"ok": False, "error": f"The page did not load: {state['error']}"}
    text = service.page_text(tab_id, limit=excerpt_chars)
    excerpt = (text.get("text") or "").strip()[:excerpt_chars]
    source = library.add_source(
        url, title=state.get("title", ""), task_id=task_id,
        question=question, excerpt=excerpt,
        method="browser", inspected=bool(excerpt),
        verification="retrieved" if excerpt else "unverified")
    shot_path = ""
    if screenshot:
        shot = service.capture_screenshot(
            tab_id, dest=str(_workspace(task_id) / "captures" /
                             f"source_{source['source_id']}.png"))
        if shot.get("ok"):
            shot_path = shot["path"]
    if excerpt or shot_path:
        library.mark_inspected(source["source_id"], title=state.get("title", ""),
                               excerpt=excerpt, screenshot=shot_path)
        source = library.get_source(source["source_id"]) or source
    return {"ok": True, "source": source, "screenshot": shot_path,
            "chars": len(excerpt)}


def collect_image(service, tab_id: str, src: str, *, task_id: str = "",
                  source_id: str = "", license_status: str = "unknown",
                  attribution: str = "", approve: bool = False) -> dict:
    """Download an image the page is showing, then record it with provenance."""
    info = service.inspect_image_resource(tab_id, src)
    if not info.get("ok"):
        return {"ok": False, "error": info.get("error", "Not an image on this page.")}
    real_src = info.get("src") or src
    page_state = service.state(tab_id)
    try:
        fetched = assets.fetch(real_src, task_id=task_id, expect="image")
    except assets.AssetError as exc:
        return {"ok": False, "error": str(exc), "url": real_src}
    record = library.add_asset(
        fetched["path"], source_url=real_src,
        page_url=page_state.get("url", ""), task_id=task_id,
        width=fetched["width"], height=fetched["height"],
        fmt=fetched["format"], size_bytes=fetched["bytes"],
        sha256=fetched["sha256"], license_status=license_status,
        attribution=attribution or info.get("alt", ""),
        filename=fetched["filename"], kind="image",
        captured_at=fetched["retrieved_at"])
    if source_id:
        source = library.get_source(source_id) or {}
        linked = list(source.get("assets") or [])
        if record["asset_id"] not in linked:
            linked.append(record["asset_id"])
            library.update_source(source_id, assets=linked)
    if approve:
        library.approve_asset(record["asset_id"], True)
        record = library.get_asset(record["asset_id"]) or record
    return {"ok": True, "asset": record, "fetched": fetched,
            "declared": {"width": info.get("width"), "height": info.get("height")},
            "duplicate": fetched["sha256"] and bool(
                library.find_asset_by_hash(fetched["sha256"], task_id))}


def collect_selection(service, tab_id: str, *, task_id: str = "",
                      claim: str = "", question: str = "",
                      source_id: str = "") -> dict:
    """Store the text the user selected as an evidence record with its source."""
    selection = service.extract_selection(tab_id)
    if not selection.get("ok"):
        return selection
    text = (selection.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "Select some text on the page first."}
    state = service.state(tab_id)
    if not source_id:
        source = library.add_source(
            state.get("url", ""), title=state.get("title", ""),
            task_id=task_id, question=question, excerpt=text[:2500],
            inspected=True, verification="retrieved")
        source_id = source["source_id"]
    record = library.add_evidence(
        claim or text[:400], source_id=source_id, url=state.get("url", ""),
        excerpt=text, task_id=task_id, question=question,
        method="selection")
    return {"ok": True, "evidence": record, "source_id": source_id,
            "text": text}


def collect_table(service, tab_id: str, index: int = 0, *, task_id: str = "",
                  source_id: str = "") -> dict:
    structure = service.page_structure(tab_id)
    if not structure.get("ok"):
        return structure
    tables = structure.get("tables") or []
    if not tables:
        return {"ok": False, "error": "This page has no tables."}
    if index < 0 or index >= len(tables):
        return {"ok": False, "error": f"Table {index} does not exist; the page "
                                     f"has {len(tables)}."}
    table = tables[index]
    state = service.state(tab_id)
    if not source_id:
        source = library.add_source(state.get("url", ""),
                                    title=state.get("title", ""),
                                    task_id=task_id, inspected=True,
                                    verification="retrieved")
        source_id = source["source_id"]
    headers = table.get("headers") or []
    rows = table.get("rows") or []
    claim = (f"Table {index} with columns: " + ", ".join(headers[:12])
             if headers else f"Table {index} with {len(rows)} rows")
    record = library.add_evidence(
        claim, source_id=source_id, url=state.get("url", ""),
        excerpt=f"{len(rows)} rows × {len(headers or (rows[0] if rows else []))} columns",
        task_id=task_id, method="table")
    return {"ok": True, "evidence": record, "table": table,
            "source_id": source_id, "rows": len(rows), "columns": headers}


def capture(service, tab_id: str, *, task_id: str = "", label: str = "",
            full_page: bool = False, element: str = "") -> dict:
    """Save a genuine screenshot into the task workspace."""
    dest = _workspace(task_id) / "captures" / (
        f"{label or 'capture'}_{time.strftime('%Y%m%d_%H%M%S')}.png")
    result = service.capture_screenshot(tab_id, full_page=full_page,
                                        element=element, dest=str(dest))
    if not result.get("ok"):
        return result
    return {"ok": True, "path": result["path"], "width": result["width"],
            "height": result["height"], "format": result["format"],
            "url": result.get("url", ""), "tab_id": result.get("tab_id", ""),
            "full_page": bool(full_page), "element": element}


__all__ = ["save_source", "collect_image", "collect_selection", "collect_table",
           "capture"]
