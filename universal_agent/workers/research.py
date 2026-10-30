"""Research worker: search → inspect sources → evidence register → cited report.

Every finding is a quotation or close paraphrase of text that was actually
retrieved, carrying a citation marker that maps to the source list. Nothing is
asserted from model memory:

* search results are discovery only (their snippets are marked "snippet only"
  when the page could not be fetched);
* a fetched page contributes sentences that overlap the research question;
* a failed source is listed in Limitations, not silently dropped;
* a model-written summary is accepted only if it cites the evidence; otherwise
  the deterministic summary is used.

If nothing can be retrieved, the worker fails instead of inventing a report.
"""

from __future__ import annotations

import re
import time

from universal_agent import intake, security
from universal_agent.workers import (Context, default_fetch, default_search,
                                     presets)

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n{2,}")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_+\-]{3,}")

_STOP = {
    "research", "investigate", "compare", "comparison", "about", "please",
    "what", "which", "with", "from", "that", "this", "these", "those", "into",
    "using", "their", "there", "have", "will", "should", "could", "would",
    "make", "build", "create", "latest", "current", "best", "between",
}


def _topic(request: str) -> str:
    text = re.sub(
        r"^\s*(please\s+)?(research|investigate|compare|survey|review|"
        r"evaluate|analy[sz]e|find out about|look into)\s+", "",
        str(request or ""), flags=re.I)
    return text.strip(" .:") or str(request or "").strip()


def _queries(topic: str, depth: str) -> list[str]:
    base = topic[:180]
    quick = [base]
    standard = [base, f"{base} documentation"]
    deep = [base, f"{base} documentation",
            f"{base} comparison alternatives",
            f"{base} limitations problems"]
    return {"quick": quick, "brief": quick, "deep": deep,
            "thorough": deep, "exhaustive": deep}.get(depth, standard)


# ── research presets ─────────────────────────────────────────────────────
#
# A preset is a saved research recipe: query templates, source hints, and what
# to keep. It broadens the search deliberately (GitHub, docs, design
# references, nationwide records) and each preset records what it contributed,
# so the report says which recipes actually found something.

def _with_presets(queries: list[str], selected: list[dict], topic: str) -> list[str]:
    """The depth queries plus every selected preset's queries (deduped, bounded)."""
    out = list(queries)
    for preset in selected:
        for query in presets.queries(preset, topic):
            if query not in out:
                out.append(query)
    # Presets add breadth, not an unbounded crawl.
    return out[:12]


_STATE_ABBR = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI",
    "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
    "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}

_PLACE = re.compile(
    r"\b([A-Z][A-Za-z0-9&'.\- ]{2,40}?)\s+[—–\-]\s+"
    r"([A-Z][A-Za-z .\-]{1,28}?,\s*([A-Z]{2}))\b")


def _state_entities(text: str, title: str, url: str) -> list[dict]:
    """Candidate records from one page: name + 'City, ST' + source.

    Deliberately labelled candidates: a name paired with a state in running
    text is a lead to verify, not a confirmed record.
    """
    rows: list[dict] = []
    for name, region, state in _PLACE.findall(text or ""):
        if state not in _STATE_ABBR:
            continue
        clean = " ".join(name.split())[:80]
        if len(clean) < 3:
            continue
        rows.append({"name": clean, "region": " ".join(region.split()),
                     "source_url": url})
    if not rows and title:
        rows.append({"name": " ".join(str(title).split())[:90],
                     "region": "", "source_url": url})
    return rows


def _dedupe_entities(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        key = re.sub(r"[^a-z0-9]+", "", str(row.get("name") or "").lower())[:60]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _capture_design_references(ctx: Context, selected: list[dict],
                               results: list[dict]) -> tuple[list, list, list]:
    """Screenshot design-reference pages through the app's own browser.

    Returns (artifacts, references, notes). Everything is optional: without the
    in-app browser the pages are still read as text and the report says so.
    """
    design = [p for p in selected if p.get("id") == "ui_design"]
    if not design:
        return [], [], []
    capture = getattr(ctx, "browser", None)
    if not callable(capture):
        return [], [], ["Design references: in-app browser unavailable — "
                        "pages were read as text only."]

    preferred = [r for r in results
                 if any(presets.prefers(p, r["url"]) for p in design)]
    targets = (preferred + [r for r in results if r not in preferred])[:3]
    artifacts: list[dict] = []
    references: list[dict] = []
    notes: list[str] = []
    for item in targets:
        if ctx.check_cancel():
            break
        try:
            shot = capture(item["url"], str(ctx.workspace / "references"))
        except Exception as exc:
            notes.append(f"{item['url']}: screenshot failed ({str(exc)[:90]})")
            continue
        if not isinstance(shot, dict) or not shot.get("ok"):
            reason = str((shot or {}).get("error") or "screenshot failed")[:110]
            notes.append(f"{item['url']}: {reason}")
            continue
        path = str(shot.get("screenshot") or "")
        if path:
            artifacts.append(ctx.artifact(
                path, "png", f"Design reference: {item['title'][:60]}"))
        references.append({
            "title": item["title"],
            "url": item["url"],
            "screenshot": path,
            "palette": [str(c) for c in (shot.get("palette") or [])][:6],
        })
        ctx.log(f"Design reference captured: {item['title'][:60]}")
    return artifacts, references, notes


def _keywords(text: str) -> set[str]:
    """Match words, not punctuation.

    Dotted and punctuated forms are split (``Invoice.create.`` -> invoice,
    create) because otherwise a page that says "invoice" never overlaps a
    question that says "invoice" — which silently empties the evidence list.
    """
    out: set[str] = set()
    for word in _WORD.findall(text or ""):
        word = word.lower().strip("-_.")
        if len(word) >= 4 and word not in _STOP:
            out.add(word)
    return out


def _pick_sentences(text: str, keywords: set[str], limit: int = 3) -> list[str]:
    picked: list[str] = []
    seen = set()
    for raw in _SENTENCE.split(text or ""):
        sentence = " ".join(raw.split())
        if not 24 <= len(sentence) <= 500:
            continue
        low = sentence.lower()
        if low in seen:
            continue
        overlap = len(keywords & _keywords(sentence))
        if overlap >= 2 or (not picked and overlap >= 1):
            seen.add(low)
            picked.append(sentence)
        if len(picked) >= limit:
            break
    return picked


def _deterministic_summary(evidence: list[dict]) -> str:
    lines = []
    for i, item in enumerate(evidence[:6], 1):
        quote = item.get("quote") or item.get("claim") or ""
        quote = " ".join(quote.split())
        if len(quote) > 240:
            quote = quote[:237] + "…"
        lines.append(f"- {quote} [{i}]")
    return "\n".join(lines)


def _model_summary(ctx: Context, topic: str, evidence: list[dict]) -> str:
    if ctx.complete is None or not evidence:
        return ""
    block = "\n".join(
        f"[{i}] {item.get('quote', '')} — {item.get('source_url', '')}"
        for i, item in enumerate(evidence[:12], 1))
    prompt = (
        f"Research question: {topic}\n\n"
        "Evidence retrieved from the web (each line is a quotation from the "
        f"cited source):\n{block}\n\n"
        "Write at most five sentences summarising ONLY what this evidence "
        "supports. Cite every sentence with [n]. Do not add facts that are not "
        "in the evidence. If the evidence is not enough to answer, say so.")
    try:
        text = str(ctx.complete(prompt, "Answer from the numbered evidence "
                                       "only. Cite with [n].") or "").strip()
    except Exception as exc:
        ctx.log(f"Research summary skipped: {exc}")
        return ""
    if not text or not re.search(r"\[\d+\]", text):
        ctx.log("Research summary discarded: no citation to the evidence.")
        return ""
    return text[:2500]


def _github_urls(text: str) -> list[str]:
    return re.findall(r"https?://(?:www\.)?github\.com/[^\s<>\"')]+",
                      str(text or ""))


def _inspect_repos(ctx: Context, urls: list[str], budget: int = 2,
                   seen: set | None = None) -> list[dict]:
    """Inspect repositories through the public GitHub API.

    Data comes from GitHub itself — metadata, license, README, real source
    files and release dates — never from a model's memory. A repository that
    cannot be read is recorded as a failed source with the API's reason.
    """
    try:
        from universal_agent.tools import github as gh
    except Exception as exc:            # pragma: no cover - import is trivial
        ctx.log(f"GitHub inspection unavailable: {exc}")
        return []
    reports: list[dict] = []
    seen = seen if seen is not None else set()
    for url in urls:
        if len(reports) >= budget:
            break
        parsed = gh.parse_repo(url)
        if not parsed or parsed in seen:
            continue
        seen.add(parsed)
        ctx.log(f"Research: inspecting github {parsed[0]}/{parsed[1]}")
        report = gh.inspect(url)
        if report.get("ok"):
            reports.append(report)
            for warning in report.get("warnings") or []:
                ctx.log(f"GitHub: {warning}")
        else:
            ctx.log(f"GitHub inspection failed: {report.get('error')}")
            report["requested_url"] = url
            reports.append(report)
    return reports


def run(ctx: Context) -> dict:
    request = str(ctx.task.get("request") or "")
    answers = ctx.task.get("answers") or {}
    depth = str(ctx.params.get("depth") or answers.get("depth") or "standard")
    topic = _topic(request)
    selected = presets.resolve(ctx.params.get("presets")
                               or answers.get("presets") or [])
    queries = _with_presets(_queries(topic, depth), selected, topic)
    search = ctx.search or default_search
    fetch = ctx.fetch or default_fetch
    want_entities = any(p.get("id") == "national_search" for p in selected)

    ctx.log(f"Research: {topic} (depth {depth}, {len(queries)} queries, "
            f"presets: {presets.summary_line(selected)})")

    # Repositories named in the request are read from the GitHub API directly;
    # web search is not needed to describe what a repository actually contains.
    repo_seen: set = set()
    repo_reports = _inspect_repos(ctx, _github_urls(request), seen=repo_seen)
    results: list[dict] = []
    failed_sources: list[dict] = []
    seen_urls: set[str] = set()

    for query in queries:
        if ctx.check_cancel():
            return {"ok": False, "summary": "Research cancelled.",
                    "error": "cancelled"}
        try:
            hits = search(query, 5) or []
        except Exception as exc:
            ctx.log(f"Search failed for '{query[:60]}': {exc}")
            hits = []
        for hit in hits:
            url = str((hit or {}).get("url") or "").strip()
            if not url.lower().startswith(("http://", "https://")):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            results.append({
                "title": str(hit.get("title") or url)[:200],
                "url": url,
                "snippet": str(hit.get("snippet") or "")[:600],
            })

    # Preset source hints re-order the fetch queue only: pages that belong to a
    # selected preset are inspected first. Nothing is hidden.
    if selected:
        results.sort(key=lambda r: 0 if any(presets.prefers(p, r["url"])
                                            for p in selected) else 1)

    readable_repos = [r for r in repo_reports if r.get("ok")]
    if not results and not readable_repos:
        return {
            "ok": False,
            "summary": "No search results were returned.",
            "artifacts": [], "evidence": [], "warnings": [],
            "error": ("The search backends returned no results, so no report "
                      "was written. Nothing was fabricated."),
            "notes": [],
        }

    # Repositories that surfaced as search hits are inspected too (bounded).
    repo_reports += _inspect_repos(
        ctx, [r["url"] for r in results], budget=2 - len(repo_reports),
        seen=repo_seen)

    evidence: list[dict] = []
    inspected: list[dict] = []
    page_texts: dict[str, str] = {}
    per_query = 2 if depth in ("quick", "brief") else 3
    budget = {"quick": 3, "brief": 3, "deep": 8, "thorough": 8,
              "exhaustive": 10}.get(depth, 5)
    fetch_attempts = 0

    for item in results:
        if ctx.check_cancel():
            return {"ok": False, "summary": "Research cancelled.",
                    "error": "cancelled"}
        if fetch_attempts >= budget:
            break
        fetch_attempts += 1
        keywords = _keywords(topic) | _keywords(item.get("title", ""))
        try:
            text = fetch(item["url"], 12.0)
        except Exception as exc:
            failed_sources.append({"url": item["url"], "error": str(exc)[:160]})
            ctx.log(f"Source not reachable: {item['url']} ({str(exc)[:80]})")
            continue
        if not text or len(text) < 120:
            failed_sources.append({"url": item["url"],
                                   "error": "page returned no readable text"})
            continue
        inspected.append(item)
        if want_entities:
            page_texts[item["url"]] = text
        for sentence in _pick_sentences(text, keywords, limit=per_query):
            evidence.append({
                "claim": sentence[:400],
                "quote": sentence[:400],
                "source_url": item["url"],
                "title": item["title"],
                "retrieved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "verified": True,
                "method": "page fetched",
            })

    # Snippet-only evidence: labelled as such, never presented as inspection.
    # GitHub facts are evidence in their own right: API metadata, license,
    # README, source files and releases, each with its own cited URL.
    for report in repo_reports:
        for item in report.get("evidence") or []:
            evidence.append(dict(item))

    # When the app's visible Research Browser is available, attach real
    # screenshots/captured images to the evidence the user can actually see.
    # This is the Project Agent research skill folded into the browser: the
    # user watches the page, and the captured pixels plus page images land in
    # the workspace as artifacts.
    _attach_browser_evidence(ctx, results, inspected, failed_sources)

    if not inspected and not [r for r in repo_reports if r.get("ok")]:
        for item in results[:4]:
            if item.get("snippet"):
                evidence.append({
                    "claim": item["snippet"][:400],
                    "quote": item["snippet"][:400],
                    "source_url": item["url"],
                    "title": item["title"],
                    "retrieved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "verified": False,
                    "method": "search snippet only",
                })

    if not evidence:
        return {
            "ok": False,
            "summary": "No source could be inspected.",
            "artifacts": [], "evidence": [], "warnings": [],            "error": ("Search results were found but none could be fetched, "
                      "so no evidence was recorded and no report was written."),
            "notes": [f"{f['url']}: {f['error']}" for f in failed_sources][:5],
        }

    # When the app browser is available, capture real screenshots of the
    # pages the research tried to read (and of failed/unreadable sources).
    # The user sees the actual page through the Research Browser; the
    # screenshots and any collected page images land in the workspace as
    # artifacts, not as described-then-forgotten assets.
    _attach_browser_evidence(ctx, results, inspected, failed_sources)
    

    # Design references are captured through the app's own browser (when the
    # ui_design preset is on): real screenshots and palettes, not descriptions.
    reference_artifacts, references, capture_notes = _capture_design_references(
        ctx, selected, results)

    # Public research: open the workspace and attach browser captures so the
    # user can watch the pages and the captured pixels/images land in the
    # workspace as real artifacts (Project Agent research skill -> browser).
    _attach_browser_evidence(ctx, results, inspected, failed_sources)

    entities: list[dict] = []
    if want_entities:
        for item in inspected:
            entities += _state_entities(page_texts.get(item["url"], ""),
                                       item.get("title", ""), item["url"])
        entities = _dedupe_entities(entities)[:25]
        ctx.log(f"National search: {len(entities)} candidate record(s)")

    summary = _model_summary(ctx, topic, evidence)
    summary_source = "model summary, citation-checked" if summary else \
        "deterministic extract"

    lines = [
        f"# Research report: {topic}",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M')}  ·  "
        f"depth: {depth}  ·  sources inspected: {len(inspected)}  ·  "
        f"repositories: {len([r for r in repo_reports if r.get('ok')])}  ·  "
        f"evidence items: {len(evidence)}  ·  browser screenshots: {len(getattr(ctx, '_browser_screenshots', None) or [])}",
        "",
        "## Question",
        "",
        request,
        "",
        "## Summary",
        "",
        summary or _deterministic_summary(evidence),
        "",
        "## Findings",
        "",
    ]

    by_source: dict[str, list[dict]] = {}
    for item in evidence:
        by_source.setdefault(item["source_url"], []).append(item)
    index = {item["source_url"]: n for n, item in enumerate(
        [{"source_url": u} for u in by_source], 1)}

    for url, items in by_source.items():
        lines.append(f"### {items[0]['title']}")
        for item in items:
            quote = " ".join(str(item.get("quote") or "").split())
            marker = f"[{index[url]}]"
            suffix = "" if item.get("verified") else " (snippet only)"
            lines.append(f"- “{quote}” {marker}{suffix}")
        lines.append("")

    readable = [r for r in repo_reports if r.get("ok")]
    if readable:
        try:
            from universal_agent.tools import github as gh
        except Exception:                  # pragma: no cover
            gh = None
        if gh is not None:
            lines += ["## Repositories inspected", ""]
            for report in readable:
                section = gh.report_section(report)
                if section:
                    lines.append(section)
                    lines.append("")

    if selected:
        lines += ["## Research presets", ""]
        for preset in selected:
            tuned = presets.queries(preset, topic)
            hits = [r for r in inspected if presets.prefers(preset, r["url"])]
            detail = (f"- **{preset.get('label')}** (`{preset.get('id')}`) — "
                      f"{len(tuned)} quer{'y' if len(tuned) == 1 else 'ies'}, "
                      f"{len(hits)} source(s) inspected")
            if preset.get("collect"):
                detail += f"; keeps: {', '.join(preset['collect'])}"
            lines.append(detail)
            if preset.get("description"):
                lines.append(f"  {preset['description']}")
        lines.append("")

    if references:
        lines += ["## Design references", "",
                  "Screenshots captured from the pages with the palette read "
                  "from each image. References only — the UI is generated in "
                  "that style; no template code is copied in.", ""]
        for ref in references:
            lines.append(f"- {ref['title']} — {ref['url']}")
            if ref.get("screenshot"):
                lines.append(f"  screenshot: {ref['screenshot']}")
            if ref.get("palette"):
                lines.append(f"  palette: {', '.join(ref['palette'])}")
        lines.append("")

    # Browser-captured screenshots/evidence that the agent actually saw.
    if getattr(ctx, "_browser_screenshots", None):
        lines += ["## Browser captures", "",
                  "Real screenshots and collected page images taken through "
                  "the app's visible Research Browser during this research run. "
                  "These are the actual pixels, not descriptions.", "",
                  f"Total captured: {len(ctx._browser_screenshots)}", ""]
        for shot in ctx._browser_screenshots:
            lines.append(f"- {shot.get('label', 'capture')} — {shot.get('source_url', '')}")
            if shot.get("path"):
                lines.append(f"  file: {shot['path']}")
            if shot.get("source_url"):
                lines.append(f"  source: {shot['source_url']}")
        lines.append("")

    if entities:
        lines += ["## Candidate records", "",
                  "Names paired with a region on the inspected pages. These are "
                  "leads to verify, not confirmed records.", ""]
        for row in entities:
            where = f" — {row['region']}" if row.get("region") else ""
            lines.append(f"- {row['name']}{where}  ({row['source_url']})")
        lines.append("")

    lines += ["## Sources", ""]
    for url, items in by_source.items():
        verified = any(i.get("verified") for i in items)
        lines.append(
            f"[{index[url]}] {items[0]['title']} — {url} "
            f"({'inspected ' if verified else 'snippet only, '}"
            f"{items[0]['retrieved_at']})")
    lines += ["", "## Limitations", ""]
    if failed_sources:
        lines.append(f"- {len(failed_sources)} source(s) could not be fetched:")
        for item in failed_sources[:8]:
            lines.append(f"  - {item['url']} — {item['error']}")
    if not inspected and not [r for r in repo_reports if r.get("ok")]:
        lines.append("- No page could be fetched; all evidence is search-snippet "
                     "level and was not verified against the page.")
    lines.append(f"- Depth '{depth}' bounds the number of sources inspected "
                 f"({len(inspected)}); this is not an exhaustive survey.")
    lines.append(f"- Summary basis: {summary_source}.")
    for report in repo_reports:
        if report.get("ok"):
            continue
        label = ((report.get("repo") or {}).get("url")
                 or report.get("requested_url") or "repository")
        lines.append(f"- The repository {label} could not be inspected: "
                     f"{report.get('error') or 'unknown error'}")
    if readable:
        lines.append("- Repository facts were read from the public GitHub API at "
                     "the retrieval time shown; licenses, releases and activity "
                     "can change, so re-check before relying on them.")
    lines.append("- Statements are quotations from the cited pages; they are not "
                 "independently fact-checked.")

    # Pages are untrusted data: a credential pasted into one must not be
    # copied into the delivered report.
    report = security.redact_secrets("\n".join(lines).strip() + "\n")
    path = ctx.write_text("research-report.md", report)
    ctx.log(f"Research report written: {path.name} "
            f"({len(evidence)} evidence items)")

    repo_note = (f"; {len(readable)} repository(ies) inspected"
                 if readable else "")
    preset_note = (f"; presets: {presets.summary_line(selected)}"
                   if selected else "")
    return {
        "ok": True,
        "summary": (f"Researched '{topic[:60]}' across {len(inspected)} "
                    f"inspected source(s){repo_note}; {len(evidence)} cited "
                    f"evidence items{preset_note}."),
        "artifacts": ([ctx.artifact(path, "markdown",
                                    "Cited research report")]
                      + reference_artifacts),
        "evidence": evidence,
        "warnings": (([f"{len(failed_sources)} source(s) unreachable"]
                      if failed_sources else [])
                     + capture_notes
                     + [w for r in repo_reports for w in (r.get("warnings") or [])]),
        "error": "",
        "notes": ([summary_source]
                  + ([f"{len(entities)} candidate record(s)"] if entities else [])),
    }




# ═══════════════════════════════════════════════════════════════════════════════
#  Browser-capture attachment — Project Agent research skill in the browser.
# ═══════════════════════════════════════════════════════════════════════════════

def _attach_browser_evidence(ctx: Context, results: list[dict],
                             inspected: list[dict],
                             failed_sources: list[dict]) -> None:
    """Open the visible Research Browser and capture what it saw.

    When the app's Qt browser is available this:
      * opens the browser workspace so the user can watch the research live,
      * navigates to each inspected source (and each failed source) in a tab,
      * captures a real screenshot of each page into the workspace, and
      * collects the first page image it finds on each page.

    Captured files are registered on ``ctx._browser_screenshots`` so the
    report and the artifact list can mention them by real path. When the
    browser is unavailable the function is a no-op — research still produced
    its text evidence, it just has no on-screen screenshots to show.
    """
    browser = getattr(ctx, "browser", None)
    if not callable(browser):
        return

    task_dir = getattr(ctx, "workspace", None)
    try:
        task_dir = Path(str(task_dir or ""))  # type: ignore[arg-type]
    except Exception:
        task_dir = None
    if task_dir is None or not task_dir.exists():
        return

    shots_dir = task_dir / "browser-shots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    ctx._browser_screenshots: list[dict] = getattr(ctx, "_browser_screenshots", []) or []

    targets = []
    for item in inspected:
        url = str(item.get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            targets.append((url, item.get("title", url),
                            "inspected source"))
    for item in failed_sources:
        url = str(item.get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            targets.append((url, item.get("title", url),
                            "failed source"))

    for url, title, kind in targets:
        if ctx.check_cancel():
            break
        try:
            shot = browser(url, str(shots_dir))
        except Exception as exc:
            ctx.log(f"Browser screenshot skipped for {url[:80]}: {exc}")
            continue
        if not isinstance(shot, dict) or not shot.get("ok"):
            reason = str((shot or {}).get("error") or "screenshot failed")[:110]
            ctx.log(f"Browser screenshot failed for {url[:80]}: {reason}")
            continue
        path = str(shot.get("screenshot") or "")
        if not path:
            continue
        ctx._browser_screenshots.append({
            "path": path,
            "source_url": url,
            "title": title,
            "label": f"{kind}: {title[:50]}",
            "palette": [str(c) for c in (shot.get("palette") or [])][:6],
        })
        ctx.log(f"Browser captured: {title[:50]} — {url[:80]}")

__all__ = ["run"]
