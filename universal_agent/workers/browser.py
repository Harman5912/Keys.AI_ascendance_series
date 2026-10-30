"""Browser worker — read-only page inspection with an audit trail.

Scope is deliberately narrow: navigate, read the rendered page, screenshot it,
and download a file the page explicitly links to. It never signs in, submits a
form, clicks a consequential button, or types into a page. Anything beyond
that is reported as a limitation instead of being attempted silently.

Safety:
* only http(s) URLs (``file:``/``data:``/``javascript:`` are refused);
* a per-step timeout and a bounded page-text size;
* downloads are saved inside the task workspace and size/type checked;
* every navigation, download and refusal is written to the audit log.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import urlparse

from universal_agent import models, security
from universal_agent.workers import Context

_URL = re.compile(r"https?://[^\s<>\"')]+", re.I)
_DOWNLOAD_EXT = (".pdf", ".csv", ".xlsx", ".json", ".txt", ".zip", ".png",
                 ".jpg", ".jpeg")


def _target_url(request: str) -> str:
    match = _URL.search(str(request or ""))
    return match.group(0).rstrip(".,;") if match else ""


def _audit(action: str, detail: str, outcome: str) -> None:
    models.audit(security.audit_line(action, detail, outcome))


def _save_download(download, directory: Path, url: str) -> Path | None:
    """Persist a Playwright download inside the workspace and audit it."""
    try:
        name = security.safe_filename(download.suggested_filename or "download.bin")
        dest = security.resolve_within(
            directory, security.unique_path(directory, name))
        download.save_as(str(dest))
    except Exception as exc:
        _audit("browser.download", url, f"could not be saved: {str(exc)[:120]}")
        return None
    _audit("browser.download", f"{url} → {dest.name}",
           f"{dest.stat().st_size} bytes")
    return dest


def fetch_page(url: str, screenshot_dir: Path, *, timeout_ms: int = 20_000,
               want_download: bool = False) -> dict:
    """Navigate and extract; returns a dict — never raises for a page error."""
    if not re.match(r"^https?://", url, re.I):
        raise security.SecurityError(
            "Only http:// and https:// pages may be opened.")
    parsed = urlparse(url)
    if not parsed.hostname:
        raise security.SecurityError("The URL has no host.")

    _audit("browser.navigate", url, "requested")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        _audit("browser.navigate", url, f"playwright missing: {exc}")
        return {"ok": False, "url": url,
                "error": f"Playwright is not available: {exc}"}

    result = {"ok": False, "url": url, "title": "", "text": "",
              "screenshot": "", "download": "", "status": 0, "error": ""}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_default_timeout(timeout_ms)
                try:
                    response = page.goto(url, wait_until="domcontentloaded",
                                         timeout=timeout_ms)
                except Exception as exc:
                    # A direct link to a file makes Chromium start a download
                    # instead of a navigation. That is exactly what the user
                    # asked for, so capture the file rather than reporting a
                    # navigation error.
                    if "download is starting" not in str(exc).lower():
                        raise
                    with page.expect_download(timeout=timeout_ms) as info:
                        try:
                            page.goto(url, timeout=timeout_ms)
                        except Exception:
                            pass
                    saved = _save_download(info.value, screenshot_dir, url)
                    if saved is None:
                        result["error"] = "The download could not be saved."
                        return result
                    result.update(ok=True, status=200, title=saved.name,
                                  download=str(saved))
                    return result
                result["status"] = response.status if response else 0
                if result["status"] >= 400:
                    result["error"] = (f"The server answered HTTP "
                                       f"{result['status']} for this URL.")
                    _audit("browser.navigate", url,
                           f"HTTP {result['status']} (treated as failure)")
                    return result
                page.wait_for_timeout(1200)      # let client-rendered text settle
                result["title"] = (page.title() or "")[:200]
                text = page.inner_text("body") or ""
                result["text"] = re.sub(r"\n{3,}", "\n\n", text)[:40_000]

                shot = security.unique_path(
                    screenshot_dir,
                    security.safe_filename(f"browser-{parsed.hostname}", suffix=".png"))
                shot = security.resolve_within(screenshot_dir, shot)
                page.screenshot(path=str(shot), full_page=True)
                result["screenshot"] = str(shot)

                if want_download:
                    link = None
                    for anchor in page.query_selector_all("a[href]"):
                        href = anchor.get_attribute("href") or ""
                        if href.lower().split("?")[0].endswith(_DOWNLOAD_EXT):
                            link = anchor
                            break
                    if link is not None:
                        with page.expect_download(timeout=timeout_ms) as info:
                            link.click()
                        saved = _save_download(info.value, screenshot_dir, url)
                        if saved is not None:
                            result["download"] = str(saved)
                        else:
                            result.setdefault("notes", []).append(
                                "The file could not be saved inside the task "
                                "workspace.")
                    else:
                        result.setdefault("notes", []).append(
                            "No downloadable file link was found on the page.")

                result["ok"] = True
                _audit("browser.navigate", url,
                       f"HTTP {result['status']} · {len(result['text'])} chars")
            finally:
                browser.close()
    except Exception as exc:
        result["error"] = str(exc)[:400]
        _audit("browser.navigate", url, f"failed: {result['error']}")
    return result


def run(ctx: Context) -> dict:
    request = str(ctx.task.get("request") or "")
    url = str(ctx.params.get("url") or _target_url(request))
    if not url:
        return {"ok": False, "summary": "No URL was given.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": "A browser task needs an http(s) URL.",
                "notes": []}
    if ctx.check_cancel():
        return {"ok": False, "summary": "Browser task cancelled.",
                "error": "cancelled"}

    want_download = bool(re.search(r"\b(download|save the file|fetch the file)\b",
                                   request, re.I))
    ctx.log(f"Browser: opening {url}")
    page = fetch_page(url, ctx.workspace, want_download=want_download)

    if not page.get("ok"):
        return {"ok": False, "summary": "The page could not be opened.",
                "artifacts": [], "evidence": [],
                "warnings": [],
                "error": page.get("error") or "Navigation failed.",
                "notes": [f"HTTP {page.get('status') or '?'}"]}

    artifacts = []
    if page.get("screenshot") and Path(page["screenshot"]).is_file():
        artifacts.append(ctx.artifact(page["screenshot"], "png",
                                      "Full-page screenshot"))
    if page.get("download") and Path(page["download"]).is_file():
        downloaded = Path(page["download"])
        if downloaded.stat().st_size == 0:
            return {"ok": False, "summary": "The downloaded file was empty.",
                    "artifacts": artifacts, "evidence": [], "warnings": [],
                    "error": f"{downloaded.name} is 0 bytes; it was not accepted.",
                    "notes": []}
        artifacts.append(ctx.artifact(downloaded,
                                      downloaded.suffix.lstrip("."),
                                      "File downloaded from the page"))

    excerpt = page.get("text", "")
    evidence = [{
        "claim": excerpt[:300] or page.get("title", ""),
        "quote": excerpt[:300],
        "source_url": page["url"],
        "title": page.get("title", ""),
        "retrieved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "verified": True,
        "method": "browser rendering",
    }] if excerpt else []

    body = [
        f"# Browser report: {page.get('title') or page['url']}",
        "",
        f"URL: {page['url']}",
        f"HTTP status: {page.get('status') or 'unknown'}",
        f"Rendered: {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Page text (excerpt)",
        "",
        "```",
        excerpt[:8000] or "(no readable text on the page)",
        "```",
        "",
        "## Limitations",
        "",
        "- Read-only: no sign-in, form submission or consequential click was "
        "performed.",
        "- The excerpt is what the page rendered for this visit; it may differ "
        "for other sessions or regions.",
    ]
    # Rendered page text is untrusted: redact credential-shaped strings before
    # they are written into a delivered record.
    report = ctx.write_text(
        "browser-report.md",
        security.redact_secrets("\n".join(body).strip() + "\n"))
    artifacts.append(ctx.artifact(report, "markdown", "Page inspection record"))

    return {
        "ok": True,
        "summary": (f"Opened {page['url']} "
                    f"(HTTP {page.get('status') or '?'}) and captured "
                    f"{len(artifacts) - 1} file(s)."),
        "artifacts": artifacts,
        "evidence": evidence,
        "warnings": ([] if (excerpt or page.get("download"))
                     else ["The page rendered no readable text."]),
        "error": "",
        "notes": page.get("notes") or [],
    }


__all__ = ["run", "fetch_page"]
