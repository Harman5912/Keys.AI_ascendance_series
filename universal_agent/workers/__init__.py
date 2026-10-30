"""Worker interface and registry.

A worker receives a :class:`Context` (task, workspace, step params, log,
cancellation check, approval gate) and returns a dict:

    {
      "ok": bool,                 # did the worker complete its own work
      "summary": str,             # one line for the task log
      "artifacts": [{"path", "kind", "detail"}],
      "evidence": [{"claim","source_url","title","retrieved_at","verified"}],
      "warnings": [str],
      "error": str,
      "notes": [str],
    }

A worker saying ``ok`` is not the end of the story: the service validates every
artifact before a task may become COMPLETED. Workers never write outside the
workspace and never delete user files.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from universal_agent import security


@dataclass
class Context:
    task: dict
    workspace: Path
    params: dict = field(default_factory=dict)
    log: Callable[[str], None] = lambda _m: None
    should_cancel: Callable[[], bool] = lambda: False
    request_approval: Callable[[str, str], bool] = lambda _t, _d: False
    complete: Callable[[str, str], str] | None = None
    search: Callable[[str, int], list] | None = None
    fetch: Callable[[str, float], str] | None = None
    build_project: Callable[[dict], dict] | None = None
    image_backend: Callable[[dict], dict] | None = None
    browser: Callable[..., dict] | None = None

    def check_cancel(self) -> bool:
        return bool(self.should_cancel())

    def write_text(self, name: str, text: str) -> Path:
        directory = self.workspace
        target = security.unique_path(directory, security.safe_filename(name))
        target = security.resolve_within(self.workspace, target)
        target.write_text(str(text), encoding="utf-8")
        return target

    def artifact(self, path, kind: str = "", detail: str = "") -> dict:
        p = Path(path)
        return {"path": str(p), "kind": kind or p.suffix.lstrip("."),
                "detail": detail}


def default_complete(prompt: str, system: str) -> str:
    """One text completion through the app's configured brain model."""
    from core.llm_client import complete
    return complete("brain", prompt, system=system, temperature=0.2,
                    max_tokens=900)


def default_search(query: str, limit: int = 5) -> list:
    from actions.web_search import _web_results
    return _web_results(query, max_results=limit)


def default_fetch(url: str, timeout: float = 12.0) -> str:
    """Readable text of a public page (scripts/styles/nav removed)."""
    import re
    import urllib.request

    req = urllib.request.Request(str(url), headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        raw = resp.read(2_000_000)
        charset = resp.headers.get_content_charset() or "utf-8"
    html = raw.decode(charset, "replace")
    if "<" not in html:
        return html[:200_000]
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "footer",
                         "header", "svg", "form"]):
            tag.decompose()
        text = soup.get_text("\n")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"[ \t\r\x0b\x0c]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()[:200_000]


def title_for(request: str) -> str:
    """A human title from the request without the leading command verb."""
    import re
    text = re.sub(
        r"^\s*(please\s+)?(create|make|build|write|generate|prepare|produce|"
        r"draft|research|investigate|analy[sz]e|edit|resize|crop|convert)\s+"
        r"(me\s+)?(a|an|the)?\s*", "", str(request or ""), flags=re.I)
    text = text.strip(" .:-")
    return (text[:80] or "Project deliverable")


def _registry() -> dict:
    from universal_agent.workers import (browser, data, documents, images,
                                         research, software)
    return {
        "research": research.run,
        "software": software.run,
        "documents": documents.run,
        "data": data.run,
        "images": images.run,
        "browser": browser.run,
    }


def execute(worker: str, ctx: Context) -> dict:
    fn = _registry().get(worker)
    if fn is None:
        return {"ok": False, "summary": f"No worker named '{worker}' exists.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": f"Unknown worker: {worker}", "notes": []}
    started = time.monotonic()
    result = fn(ctx)
    result.setdefault("artifacts", [])
    result.setdefault("evidence", [])
    result.setdefault("warnings", [])
    result.setdefault("notes", [])
    result.setdefault("error", "")
    result["elapsed"] = round(time.monotonic() - started, 2)
    return result


__all__ = ["Context", "execute", "default_complete", "default_search",
           "default_fetch", "title_for"]
