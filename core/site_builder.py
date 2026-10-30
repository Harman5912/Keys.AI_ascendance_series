"""
core/site_builder.py — reliable single-page site builder for Crown Code.

Why this exists
---------------
A local 8B model is good at writing copy and CSS, and unreliable at driving a
twelve-tool agent loop: it stops calling tools, prints HTML into its reply, or
hands back a truncated file. Asking such a model to "use write_file" makes the
success of a build depend on a behaviour we cannot guarantee.

So the website path is a *plan → write → verify → repair* pipeline, the shape
used by the strongest coding agents today (aider's whole-file edit format,
Claude Code's plan-then-act with an explicit checklist, Cline's
act/observe/retry, OpenHands' deterministic post-processing):

    1. PLAN     one JSON-only call: brand, copy, sections, acceptance list.
                JSON is far easier for a small model than tool calling, and a
                bad plan is cheap to correct.
    2. WRITE    one whole-file call. Whole-file output removes the hardest
                part of code editing for a weak model (surgical patching).
    3. VERIFY   deterministic checks (core.site_checks) plus an optional real
                Chromium pass: console errors, 375 px overflow, dead anchors.
    4. REPAIR   mechanical fixes first (viewport, focus styles, box-sizing,
                truncation), then one targeted rewrite that quotes the exact
                failures — and, if the model still cannot produce a valid page,
                a plan-driven rendered page so the user is never left with a
                broken file.

Nothing here pretends a failed build succeeded: every attempt, its problems and
the reason for the final artifact are returned in the result dict.
"""

from __future__ import annotations

import html as _html
import json
import re
import time
from pathlib import Path

from core.brief_spec import is_app_brief
from core.site_checks import (acceptance_checklist, browser_audit, check_html,
                              checklist_summary, repair_html)
from core.site_studio import ORDER, choose_studio, plan_to_content, render_site
from core.site_studio.presets import apply_preset_css, choose_preset

# Tile gradients for the gallery renderer — the page never loads an image
# from the network, so a photography portfolio is built from CSS art.
_GRADIENTS = [
    ("#f2c1a0", "#8c4a3c"), ("#a9c8e8", "#2f4b7c"), ("#cfd8a8", "#4a5d33"),
    ("#e8c1d8", "#6b3a5c"), ("#f4d58d", "#9c6b1f"), ("#bcd9d3", "#2f5d58"),
    ("#d9c2b0", "#5c4636"), ("#b8b3e0", "#413a7a"), ("#e6e2d8", "#555049"),
]


# ── Prompts ───────────────────────────────────────────────────────────────

PLAN_SYSTEM = (
    "You are a senior product designer and front-end engineer planning one web page. "
    "You reply with a single JSON object and nothing else."
)

PLAN_RULES = """Return ONLY this JSON object (no prose, no markdown fences):
{
  "brand": "short brand or person name",
  "title": "page title for the <title> tag",
  "eyebrow": "3-6 word label above the headline",
  "headline": "one specific headline, max 12 words",
  "tagline": "one or two sentences of specific copy, no placeholders",
  "accent": "#rrggbb",
  "cta_primary": "button label",
  "cta_secondary": "button label",
  "sections": [
    {"id": "work", "kind": "projects", "heading": "Selected work", "lead": "one sentence",
     "items": [{"title": "project name", "text": "what it is and the result",
                "meta": "2025 · Client", "tags": ["React", "Node"]}]}
  ],
  "metrics": [{"value": "6+", "label": "years shipping"}],
  "faq": [{"q": "question", "a": "answer"}],
  "footer": "one line of footer copy"
}
Allowed section kinds: about, cards, projects, gallery, skills, text, faq, contact.
Rules:
- Return exactly 4 or 5 sections, in this order: about, work (kind "gallery"
  for image-led briefs, otherwise "projects"), skills, faq, contact.
  Each section needs a heading and 3 items (2 for about). Use kinds only from
  the allowed list.
- Image-led briefs (photographer, gallery, shop, travel) use kind "gallery"
  with 9 items, each carrying a category in tags (portraits / landscape / studio).
- 4 to 6 sections, in the order they should appear. Always end with a contact section.
- Write the ACTUAL copy for the brief: names, projects, prices, results. Never
  "Company Name", "Feature 1", "Lorem ipsum" or "[insert]".
- projects/cards: 3 or 4 items, each with a real title and a concrete result.
- Keep every string under 240 characters. Valid JSON only."""

WRITE_SYSTEM = (
    "You are a senior front-end engineer. You write complete, production-quality "
    "single-file HTML pages that work offline. You reply with the file only."
)

WRITE_RULES = """Write the COMPLETE index.html for this plan.

Hard requirements:
- One self-contained file. All CSS in <style>, all JS in <script>. No external
  fonts, images, scripts or stylesheets — no http(s) URLs at all.
- Semantic HTML5: <!doctype html>, <html lang>, <head> with viewport meta and a
  <title>, <header>, <main>, <footer>. One <h1>.
- Real content from the plan. Do not invent lorem ipsum, "Feature 1",
  "Your Company" or placeholder buttons.
- Responsive from 375px to 1440px, no horizontal scrolling: box-sizing reset,
  max-width:100% on media, fluid type with clamp().
- Visible :focus-visible styles, labelled form inputs, buttons that are
  <button> elements, and a mobile nav toggle.
- Working interactions in vanilla JS: nav toggle, project/category filter if the
  plan has tags, contact-form validation with an inline success message, and
  <details> based FAQ. Respect prefers-reduced-motion.
- At least 250 lines, but HARD LIMIT 700 lines total and at most 230 lines of
  CSS. Never repeat a CSS rule block; write each rule once. Modern, deliberate
  design: type scale, spacing rhythm, one accent colour, subtle depth. No CSS
  framework, no class names like "box1".
- Order matters: close </head> and open <body> before line 320, then the page
  content, then </body></html> last. A file that stops inside <style> is a
  failed build.
- Output ONLY the file. No commentary before or after, no markdown fences."""


def render_studio_page(plan: dict, kind: str, brief: str, seed: str = "",
                       studio: str = "") -> tuple[str, str]:
    """Render the plan through one of the ten studios.

    Selection is deterministic for a brief but varies with it, so a portfolio
    and a restaurant never share a layout and two similar briefs do not always
    land on the same studio. ``studio`` forces a specific one — used when two
    pages in the same set would otherwise pick the same layout. Returns
    (html, studio_key).
    """
    content = plan_to_content(plan, kind, brief)
    forced = studio if studio in ORDER else ""
    key = forced or choose_studio(brief, kind, seed=seed)
    content["studio"] = key
    return render_site(content, key), key


def _esc(value, default: str = "") -> str:
    text = str(value if value is not None else default)
    return _html.escape(text, quote=True)


def _accent(plan: dict) -> str:
    raw = str(plan.get("accent") or "").strip()
    return raw if re.fullmatch(r"#[0-9a-fA-F]{6}", raw) else "#e8b44a"


# ── Planning ──────────────────────────────────────────────────────────────

_TOPIC_STOP = {
    "a", "an", "the", "and", "or", "for", "with", "from", "into", "that", "this",
    "build", "create", "make", "design", "develop", "please", "want", "need", "help",
    "website", "webpage", "web", "page", "site", "landing", "portfolio", "one",
    "pager", "microsite", "homepage", "app", "application", "using", "should", "some",
    "few", "proper", "like", "about", "plus", "via", "new", "all", "its", "it",
    "my", "our", "your", "me", "i", "who", "what", "to", "of", "in", "on", "at",
}


def _brief_topics(brief: str, exclude=()) -> list[str]:
    """Phrases the brief itself lists, in order. Nothing is invented here."""
    skip = {str(w).lower() for w in exclude if w}
    topics: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[,;•\n]|\band\b|\bwith\b|\bplus\b", brief or ""):
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z'’-]{2,}", part)
                 if w.lower() not in _TOPIC_STOP and w.lower() not in skip]
        if len(words) < 2:
            continue
        phrase = " ".join(words[:3])
        if phrase.lower() in seen:
            continue
        seen.add(phrase.lower())
        topics.append(phrase if not phrase.islower() else phrase.title())
    return topics


def fallback_plan(brief: str, kind: str = "portfolio") -> dict:
    """A complete, specific plan built without a model.

    Used when the model cannot return valid JSON. It is deliberately generic in
    *structure* but concrete in *copy*, so the rendered page still reads like a
    finished site rather than a template full of labels.
    """
    brief = (brief or "").strip()
    quoted = re.findall(r"[\"“'‘]([^\"”'’]{2,40})[\"”'’]", brief)
    name = quoted[0].strip() if quoted else ""
    if not name:
        # "Portfolio for Arjun Mehta" / "for the fictional photographer Lena
        # Fischer" → the last proper noun in the brief that is not a role or a
        # determiner. Names come last in these briefs far more often than not.
        stop = {"fictional", "portfolio", "website", "landing", "page", "site",
                "saas", "small", "full", "stack", "front", "back", "product",
                "graphic", "visual", "creative"}
        for a, b2 in reversed(re.findall(r"\b([A-Z][a-z]{1,15})\s+([A-Z][a-z]{1,15})\b", brief)):
            if a.lower() in stop or b2.lower() in stop:
                continue
            name = f"{a} {b2}"
            break
    role_match = re.search(
        r"\b(full[- ]stack developer|front[- ]end developer|back[- ]end developer|"
        r"software engineer|ml engineer|ai engineer|data analyst|data scientist|"
        r"ui/?ux designer|product designer|photographer|photojournalist|writer|editor|"
        r"creative developer|student|fresher|agency|studio|consultancy|artist|illustrator)\b",
        brief, re.I)
    role = role_match.group(1).lower() if role_match else (
        "designer" if "portfolio" in kind else "")
    if not name:
        name = "Avery Quinn" if kind == "portfolio" else "Northline Studio"

    is_portfolio = kind == "portfolio"
    # The floor is honest. It carries the request and the facts the brief
    # states — never invented case studies, client results, team sizes or
    # policies. "Activation rose from 41% to 68%" under a coffee roastery is
    # exactly the preset-template smell, and a failed plan must not manufacture
    # a portfolio the user never asked for.
    topics = _brief_topics(brief, exclude=(name, role))
    about = {"id": "about", "kind": "about", "heading": "About",
             "lead": f"{name} — {role}." if role else f"{name}.",
             "items": [{"title": "The request", "text": brief}]}
    contact = {"id": "contact", "kind": "contact", "heading": "Get in touch",
               "lead": "Send a message with what you need and the deadline you are "
                       "working towards.",
               "items": []}
    # Shown only while the page is still the floor (no usable plan from the
    # model). Saying so beats a finished-looking page built from nothing.
    status = {"id": "status", "kind": "text", "heading": "Status",
              "lead": "The planner did not return a usable plan for this page, so only "
                      "the request itself is shown. Rebuild to get the real copy.",
              "items": []}
    if topics:
        sections = [about,
                    {"id": "work", "kind": "projects",
                     "heading": "Selected work" if is_portfolio else "What this covers",
                     "lead": "", "items": [{"title": t, "text": "", "meta": "",
                                               "tags": []} for t in topics[:4]]},
                    status, contact]
    else:
        sections = [about,
                    {"id": "brief", "kind": "text", "heading": "The brief",
                     "lead": brief, "items": []},
                    status, contact]
    return {
        "brand": name,
        "title": f"{name} — {role.title()}" if role else name,
        "eyebrow": role.title(),
        "headline": name,
        "tagline": brief or f"A page for {name}.",
        "accent": "#e8b44a",
        "cta_primary": "Get in touch",
        "cta_secondary": "Back to top",
        "sections": sections,
        "metrics": [],
        "faq": [],
        "footer": f"© {name}. Built with Crown Code.",
    }


def normalise_plan(raw: dict | None, brief: str, kind: str) -> tuple[dict, bool]:
    """Coerce whatever the model returned into the shape the renderer needs."""
    base = fallback_plan(brief, kind)
    if not isinstance(raw, dict) or not raw:
        return base, False
    plan = dict(base)
    for key in ("brand", "title", "eyebrow", "headline", "tagline",
                "cta_primary", "cta_secondary", "footer"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            plan[key] = value.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", str(raw.get("accent") or "")):
        plan["accent"] = str(raw["accent"])

    sections = raw.get("sections")
    clean = []
    if isinstance(sections, list):
        for i, s in enumerate(sections[:6]):
            if not isinstance(s, dict):
                continue
            kind_s = str(s.get("kind") or "text").lower()
            if kind_s not in ("about", "cards", "projects", "gallery", "skills",
                              "text", "faq", "contact"):
                kind_s = "cards"
            items = []
            for it in (s.get("items") or [])[:6]:
                if isinstance(it, str):
                    it = {"title": it}
                if not isinstance(it, dict):
                    continue
                items.append({
                    "title": str(it.get("title") or "")[:120],
                    "text": str(it.get("text") or "")[:400],
                    "meta": str(it.get("meta") or "")[:80],
                    "tags": [str(t)[:24] for t in (it.get("tags") or []) if str(t).strip()][:5],
                })
            heading = str(s.get("heading") or s.get("title") or s.get("name") or "").strip()
            if not heading:
                continue
            clean.append({"id": re.sub(r"[^a-z0-9]+", "-", (str(s.get("id") or heading)).lower()).strip("-") or f"s{i}",
                          "kind": kind_s, "heading": heading[:90],
                          "lead": str(s.get("lead") or "")[:300], "items": items})
    # Two real sections plus the hero/metrics/FAQ/footer the renderer always
    # adds make a complete page; demanding more just discards a small model's
    # good copy because it wrote a shorter brief than asked for.
    accepted = len([s for s in clean if s["kind"] != "contact"]) >= 2
    if accepted:
        plan["sections"] = clean
        if not any(s["kind"] == "contact" for s in clean):
            plan["sections"].append(base["sections"][-1])
    metrics = raw.get("metrics")
    if isinstance(metrics, list) and metrics:
        plan["metrics"] = [{"value": str(m.get("value") or "")[:12],
                            "label": str(m.get("label") or "")[:40]}
                           for m in metrics[:4] if isinstance(m, dict)] or base["metrics"]
    faq = raw.get("faq")
    if isinstance(faq, list) and faq:
        plan["faq"] = [{"q": str(f.get("q") or "")[:160], "a": str(f.get("a") or "")[:400]}
                       for f in faq[:5] if isinstance(f, dict) and f.get("q")] or base["faq"]
    return plan, accepted


def plan_summary(plan: dict) -> str:
    kinds = ", ".join(s["kind"] for s in plan.get("sections", []))
    return (f"{plan.get('brand')} · {len(plan.get('sections', []))} sections "
            f"({kinds}) · accent {plan.get('accent')}")


# ── Whole-file extraction ─────────────────────────────────────────────────

def extract_html(text: str) -> str:
    """Pull the document out of a model reply that may include fences or prose."""
    if not text:
        return ""
    raw = text.replace("\r\n", "\n")
    fence = re.search(r"```(?:html|HTML)?\s*\n(.*?)(?:```|\Z)", raw, re.S)
    if fence and ("<" in fence.group(1)):
        raw = fence.group(1)
    start = raw.lower().find("<!doctype")
    if start == -1:
        start = raw.lower().find("<html")
    if start == -1:
        start = raw.lower().find("<body")
    if start > 0:
        raw = raw[start:]
    end = raw.lower().rfind("</html>")
    if end != -1:
        raw = raw[:end + len("</html>")]
    # Drop a trailing commentary line that survived a missing fence.
    raw = re.sub(r"\n(?:Note|Hope this|Let me know)[^\n]*\Z", "", raw)
    return raw.strip()


# ── Deterministic renderer (the floor) ────────────────────────────────────

def render_plan_site(plan: dict, kind: str = "portfolio") -> str:
    """Render a complete page from a plan without a model.

    This is the guaranteed artifact: valid markup, real copy from the plan,
    accessible controls, working JS, responsive layout.
    """
    accent = _accent(plan)
    brand = _esc(plan.get("brand"), "Studio")
    nav = [s for s in plan.get("sections", []) if s["kind"] != "contact"][:4]
    nav_html = "".join(
        f'<li><a href="#{_esc(s["id"])}">{_esc(s["heading"])}</a></li>' for s in nav)

    def section(s: dict) -> str:
        sid, heading, lead = _esc(s["id"]), _esc(s["heading"]), _esc(s.get("lead"))
        items = s.get("items") or []
        head = (f'<div class="sec-head"><p class="eyebrow">{sid.replace("-", " ")}</p>'
                f'<h2>{heading}</h2>' + (f'<p class="lead">{lead}</p>' if lead else "") + "</div>")
        k = s["kind"]
        if k == "contact":
            fields = "".join(
                f'<label for="f-{i}">{label}<input id="f-{i}" name="{name}" type="{typ}" '
                f'{"required" if typ != "textarea" else "required"} '
                f'placeholder="{ph}" aria-describedby="form-status"></label>'
                for i, (label, name, typ, ph) in enumerate([
                    ("Name", "name", "text", "Ada Lovelace"),
                    ("Email", "email", "email", "you@studio.com"),
                    ("Message", "message", "textarea", "What are you building?")]))
            return (f'<section id="{sid}" class="section" aria-labelledby="h-{sid}">'
                    f'<div class="sec-head"><p class="eyebrow">contact</p>'
                    f'<h2 id="h-{sid}">{heading}</h2>'
                    + (f'<p class="lead">{lead}</p>' if lead else "") + "</div>"
                    '<form class="contact-form" novalidate>'
                    + fields +
                    '<button type="submit" class="btn btn-primary">Send message</button>'
                    '<p id="form-status" class="form-status" role="status" aria-live="polite"></p>'
                    "</form></section>")
        if k == "faq":
            rows = "".join(f"<details><summary>{_esc(f['q'])}</summary><p>{_esc(f['a'])}</p></details>"
                           for f in plan.get("faq", []))
            return f'<section id="{sid}" class="section">{head}<div class="faq">{rows}</div></section>'
        if k == "metrics":
            rows = "".join(f'<div class="metric"><strong>{_esc(m["value"])}</strong>'
                           f'<span>{_esc(m["label"])}</span></div>' for m in plan.get("metrics", []))
            return f'<section id="{sid}" class="section">{head}<div class="metrics">{rows}</div></section>'
        if k == "skills":
            chips = "".join(f'<li class="chip">{_esc(i["title"])}</li>' for i in items)
            return f'<section id="{sid}" class="section">{head}<ul class="chips">{chips}</ul></section>'
        if k == "about":
            body = "".join(f'<div><h3>{_esc(i["title"])}</h3><p>{_esc(i["text"])}</p></div>'
                           for i in items) or f'<p class="lead">{lead}</p>'
            return f'<section id="{sid}" class="section">{head}<div class="two-col">{body}</div></section>'
        if k in ("projects", "cards", "gallery"):
            tags = sorted({t for i in items for t in i.get("tags", [])})
            filters = ""
            if tags:
                filters = ('<div class="filters" role="group" aria-label="Filter work">'
                           '<button type="button" class="filter is-active" data-filter="all">All</button>'
                           + "".join(f'<button type="button" class="filter" data-filter="{_esc(t.lower())}">'
                                     f'{_esc(t)}</button>' for t in tags) + "</div>")
            if k == "gallery":
                tiles = "".join(
                    f'<figure class="tile" data-tags="{_esc(" ".join(t.lower() for t in i.get("tags", [])))}">'
                    f'<div class="tile-art" style="--g1:{_GRADIENTS[i2 % len(_GRADIENTS)][0]};'
                    f'--g2:{_GRADIENTS[i2 % len(_GRADIENTS)][1]}" role="img" '
                    f'aria-label="{_esc(i["title"])}"></div>'
                    f'<figcaption><strong>{_esc(i["title"])}</strong>'
                    f'<small>{_esc(i.get("meta") or i.get("text"))}</small></figcaption></figure>'
                    for i2, i in enumerate(items)) or f'<p class="lead">{lead}</p>'
                return (f'<section id="{sid}" class="section">{head}{filters}'
                        f'<div class="gallery-grid">{tiles}</div></section>')

            cards = "".join(
                f'<article class="card" data-tags="{_esc(" ".join(t.lower() for t in i.get("tags", [])))}">'
                f'<p class="meta">{_esc(i.get("meta"))}</p><h3>{_esc(i["title"])}</h3>'
                f'<p>{_esc(i["text"])}</p>'
                + (f'<ul class="tags">' + "".join(f"<li>{_esc(t)}</li>" for t in i.get("tags", [])) + "</ul>"
                   if i.get("tags") else "")
                + "</article>" for i in items)
            return (f'<section id="{sid}" class="section">{head}{filters}'
                    f'<div class="grid">{cards}</div></section>')
        body = "".join(f'<p>{_esc(i["text"] or i["title"])}</p>' for i in items) or f"<p>{lead}</p>"
        return f'<section id="{sid}" class="section">{head}{body}</section>'

    metrics = "".join(
        f'<div class="metric"><strong>{_esc(m["value"])}</strong><span>{_esc(m["label"])}</span></div>'
        for m in plan.get("metrics", []))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{_esc(plan.get('tagline'))}">
<title>{_esc(plan.get('title'), brand)}</title>
<style>
  :root {{
    --bg: #0e1014; --panel: #151922; --text: #eef1f6; --muted: #a4adba;
    --accent: {accent}; --line: rgba(255,255,255,.12); --radius: 14px;
    --step: clamp(1rem, 2.5vw, 1.25rem);
    --crown-focus: {accent};
  }}
  *, *::before, *::after {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; -webkit-text-size-adjust: 100%; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font: 400 17px/1.65 "Inter", "Segoe UI", system-ui, sans-serif;
    overflow-x: hidden;
  }}
  img, svg {{ max-width: 100%; height: auto; }}
  a {{ color: inherit; }}
  :focus-visible {{ outline: 3px solid var(--accent); outline-offset: 3px; border-radius: 4px; }}
  .skip {{ position: absolute; left: -9999px; }}
  .skip:focus {{ left: 1rem; top: 1rem; background: var(--accent); color: #111;
    padding: .6rem 1rem; border-radius: 8px; z-index: 20; }}
  .wrap {{ width: min(1120px, 100% - 2.5rem); margin-inline: auto; }}
  .site-header {{
    position: sticky; top: 0; z-index: 10; backdrop-filter: blur(12px);
    background: color-mix(in srgb, var(--bg) 82%, transparent);
    border-bottom: 1px solid var(--line);
  }}
  .bar {{ display: flex; align-items: center; gap: 1rem; padding: .9rem 0; }}
  .brand {{ font-weight: 700; letter-spacing: .02em; text-decoration: none; font-size: 1.05rem; }}
  .brand span {{ color: var(--accent); }}
  nav {{ margin-inline-start: auto; }}
  nav ul {{ display: flex; gap: 1.4rem; list-style: none; margin: 0; padding: 0; }}
  nav a {{ text-decoration: none; color: var(--muted); font-size: .95rem; }}
  nav a:hover {{ color: var(--text); }}
  .nav-toggle {{ display: none; margin-inline-start: auto; background: transparent;
    color: var(--text); border: 1px solid var(--line); border-radius: 10px;
    padding: .45rem .7rem; cursor: pointer; }}
  .btn {{ display: inline-flex; align-items: center; gap: .5rem; border-radius: 999px;
    padding: .8rem 1.35rem; font-weight: 600; font-size: .95rem; text-decoration: none;
    cursor: pointer; border: 1px solid transparent; transition: transform .15s ease, background .15s ease; }}
  .btn:hover {{ transform: translateY(-1px); }}
  .btn-primary {{ background: var(--accent); color: #14161b; }}
  .btn-ghost {{ border-color: var(--line); color: var(--text); background: transparent; }}
  .hero {{ padding: clamp(3rem, 8vw, 6.5rem) 0 2.5rem; }}
  .eyebrow {{ text-transform: uppercase; letter-spacing: .18em; font-size: .72rem;
    color: var(--accent); margin: 0 0 .6rem; }}
  h1 {{ font-size: clamp(2.1rem, 6vw, 4rem); line-height: 1.05; margin: 0 0 1rem;
    letter-spacing: -.02em; }}
  h1 em {{ font-style: normal; color: var(--accent); }}
  .hero .tagline {{ color: var(--muted); font-size: var(--step); max-width: 48ch; }}
  .hero-actions {{ display: flex; flex-wrap: wrap; gap: .8rem; margin: 1.8rem 0 0; }}
  .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 1rem; margin: 2.5rem 0 0; padding: 1.25rem; background: var(--panel);
    border: 1px solid var(--line); border-radius: var(--radius); }}
  .metric strong {{ display: block; font-size: 1.7rem; letter-spacing: -.02em; }}
  .metric span {{ color: var(--muted); font-size: .85rem; }}
  .section {{ padding: clamp(2.5rem, 6vw, 4.5rem) 0; border-top: 1px solid var(--line); }}
  .sec-head {{ max-width: 62ch; margin-bottom: 2rem; }}
  h2 {{ font-size: clamp(1.5rem, 3.6vw, 2.3rem); margin: 0 0 .5rem; letter-spacing: -.01em; }}
  h3 {{ margin: 0 0 .4rem; font-size: 1.12rem; }}
  .lead, .card p, .two-col p {{ color: var(--muted); }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1.1rem; }}
  .gallery-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; }}
  .tile {{ margin: 0; background: var(--panel); border: 1px solid var(--line);
    border-radius: var(--radius); overflow: hidden; }}
  .tile-art {{ aspect-ratio: 4 / 3; background: linear-gradient(135deg, var(--g1), var(--g2));
    transition: transform .25s ease; }}
  .tile:hover .tile-art {{ transform: scale(1.03); }}
  .tile figcaption {{ padding: .8rem 1rem 1rem; display: grid; gap: .15rem; }}
  .tile small {{ color: var(--muted); font-size: .8rem; }}
  .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius);
    padding: 1.4rem; display: flex; flex-direction: column; gap: .35rem; }}
  .card:hover {{ border-color: color-mix(in srgb, var(--accent) 55%, var(--line)); }}
  .meta {{ font-size: .78rem; color: var(--accent); text-transform: uppercase;
    letter-spacing: .12em; margin: 0; }}
  .tags {{ display: flex; flex-wrap: wrap; gap: .4rem; list-style: none; padding: 0; margin: .6rem 0 0; }}
  .tags li {{ font-size: .75rem; border: 1px solid var(--line); border-radius: 999px; padding: .15rem .55rem; }}
  .filters {{ display: flex; flex-wrap: wrap; gap: .5rem; margin: 0 0 1.4rem; }}
  .filter {{ background: transparent; color: var(--muted); border: 1px solid var(--line);
    border-radius: 999px; padding: .4rem .85rem; cursor: pointer; font-size: .85rem; }}
  .filter.is-active {{ background: var(--accent); color: #14161b; border-color: var(--accent); }}
  .two-col {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1.5rem; }}
  .chips {{ list-style: none; display: flex; flex-wrap: wrap; gap: .5rem; padding: 0; margin: 0; }}
  .chip {{ border: 1px solid var(--line); border-radius: 999px; padding: .4rem .9rem; font-size: .9rem; }}
  .faq details {{ border-top: 1px solid var(--line); padding: 1rem 0; }}
  .faq summary {{ cursor: pointer; font-weight: 600; }}
  .faq p {{ color: var(--muted); max-width: 70ch; }}
  .contact-form {{ display: grid; gap: .9rem; max-width: 560px; }}
  .contact-form label {{ display: grid; gap: .35rem; font-size: .85rem; color: var(--muted); }}
  .contact-form input, .contact-form textarea {{
    background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
    color: var(--text); padding: .7rem .8rem; font: inherit; width: 100%;
  }}
  .contact-form textarea {{ min-height: 7rem; resize: vertical; }}
  .form-status {{ min-height: 1.4rem; color: var(--accent); font-size: .9rem; }}
  .site-footer {{ border-top: 1px solid var(--line); padding: 2rem 0; color: var(--muted);
    font-size: .85rem; display: flex; flex-wrap: wrap; gap: .5rem; justify-content: space-between; }}
  .reveal {{ opacity: 0; transform: translateY(14px); transition: opacity .5s ease, transform .5s ease; }}
  .reveal.is-in {{ opacity: 1; transform: none; }}
  @media (max-width: 760px) {{
    nav {{ position: absolute; inset: 100% 0 auto; background: var(--panel);
      border-bottom: 1px solid var(--line); display: none; }}
    nav.is-open {{ display: block; }}
    nav ul {{ flex-direction: column; padding: 1rem 1.25rem; gap: .9rem; }}
    .nav-toggle {{ display: inline-flex; }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    html {{ scroll-behavior: auto; }}
    *, *::before, *::after {{ animation-duration: .01ms !important; transition-duration: .01ms !important; }}
    .reveal {{ opacity: 1; transform: none; }}
  }}
</style>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="site-header">
  <div class="wrap bar">
    <a class="brand" href="#main">{brand}<span>.</span></a>
    <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-nav">Menu</button>
    <nav id="site-nav" aria-label="Main"><ul>{nav_html}</ul></nav>
  </div>
</header>
<main id="main">
  <section class="hero wrap" aria-labelledby="hero-title">
    <p class="eyebrow">{_esc(plan.get('eyebrow'))}</p>
    <h1 id="hero-title">{_esc(plan.get('headline'))}</h1>
    <p class="tagline">{_esc(plan.get('tagline'))}</p>
    <div class="hero-actions">
      <a class="btn btn-primary" href="#{(nav[0]['id'] if nav else 'main')}">{_esc(plan.get('cta_primary'), 'See the work')}</a>
      <a class="btn btn-ghost" href="#contact">{_esc(plan.get('cta_secondary'), 'Get in touch')}</a>
    </div>
    <div class="metrics">{metrics}</div>
  </section>
  {"".join(section(s) for s in plan.get("sections", []))}
</main>
<footer class="site-footer wrap">
  <p>{_esc(plan.get('footer'), brand)}</p>
  <p><a href="#main">Back to top</a></p>
</footer>
<script>
  const navToggle = document.querySelector('.nav-toggle');
  const nav = document.getElementById('site-nav');
  navToggle?.addEventListener('click', () => {{
    const open = nav.classList.toggle('is-open');
    navToggle.setAttribute('aria-expanded', String(open));
  }});
  nav?.addEventListener('click', (e) => {{
    if (e.target.closest('a')) {{
      nav.classList.remove('is-open');
      navToggle?.setAttribute('aria-expanded', 'false');
    }}
  }});

  const filters = document.querySelectorAll('.filter');
  filters.forEach((btn) => btn.addEventListener('click', () => {{
    filters.forEach((b) => b.classList.toggle('is-active', b === btn));
    const want = btn.dataset.filter;
    document.querySelectorAll('.card[data-tags], .tile[data-tags]').forEach((card) => {{
      const tags = (card.dataset.tags || '').split(' ');
      card.hidden = want !== 'all' && !tags.includes(want);
    }});
  }}));

  const form = document.querySelector('.contact-form');
  const status = document.getElementById('form-status');
  form?.addEventListener('submit', (e) => {{
    e.preventDefault();
    const data = new FormData(form);
    const name = String(data.get('name') || '').trim();
    const email = String(data.get('email') || '').trim();
    const message = String(data.get('message') || '').trim();
    if (!name || !message || !/^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(email)) {{
      status.textContent = 'Please add your name, a valid email and a short message.';
      return;
    }}
    status.textContent = `Thanks ${{name.split(' ')[0]}} — your message is queued. I reply within two working days.`;
    form.reset();
  }});

  const reveals = document.querySelectorAll('.section, .card');
  if ('IntersectionObserver' in window &&
      !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {{
    const io = new IntersectionObserver((entries) => {{
      entries.forEach((entry) => {{
        if (entry.isIntersecting) {{ entry.target.classList.add('is-in'); io.unobserve(entry.target); }}
      }});
    }}, {{ rootMargin: '0px 0px -8% 0px' }});
    reveals.forEach((el) => {{ el.classList.add('reveal'); io.observe(el); }});
  }}
</script>
</body>
</html>
""".strip()


# ── Model plumbing ────────────────────────────────────────────────────────

def _gemini_provider(timeout: float = 900.0):
    """Gemini provider when a Gemini key is configured, else None.

    Site builds are Gemini-first: the configured key is used whenever one is
    stored, and the local model stays the fallback for installs with no key, a
    failed call, or a page that cannot be verified.
    """
    try:
        from core.api_config import get_api_key, get_task_model
        key = get_api_key("gemini")
        if not key:
            return None
        model = ""
        for task in ("crown_code", "dev_agent"):
            try:
                task_cfg = get_task_model(task)
            except Exception:
                continue
            if (str(task_cfg.get("provider") or "").lower() == "gemini"
                    and task_cfg.get("model")):
                model = str(task_cfg["model"])
                break
        if not model:
            from core.model_catalog import default_model_for
            model = default_model_for("gemini")
        from brain.providers.gemini import GeminiProvider
        return GeminiProvider(api_key=key, model=model, timeout_s=timeout), model
    except Exception as e:
        print(f"[site_builder] Gemini unavailable: {e}")
        return None


def _provider(model: str = "", timeout: float = 900.0, num_ctx: int = 8192):
    """Cloud first, local second: Gemini when a key exists, else Ollama.

    `model` names a local model explicitly (the tool's model override); without
    it the configured Gemini model is tried first and the local model is the
    fallback.
    """
    if not model:
        cloud = _gemini_provider(timeout)
        if cloud is not None:
            provider, chosen = cloud
            return provider, chosen, "gemini"
    return _local_provider(model, timeout, num_ctx)


def _local_provider(model: str = "", timeout: float = 900.0, num_ctx: int = 8192):
    """OpenAI-compatible provider pointed at the local Ollama server.

    num_ctx is raised above the runtime default: the plan plus the writing
    rules plus the model's own long answer do not fit in 4096 tokens, and a
    model that has lost its brief writes CSS for 1000 lines instead of a page.
    """
    from core.crown_bridge import list_models, load_config, recommend_model
    from brain.providers.openai_compat import OpenAICompatProvider

    cfg = load_config()
    installed = list_models(cfg["ollama_url"])
    if not installed:
        raise RuntimeError(
            "No local models are installed. Run `ollama pull gemma4:12b` and retry.")
    chosen, note = recommend_model(installed, model)
    provider = OpenAICompatProvider(
        base_url=cfg["ollama_url"], model=chosen, timeout=timeout,
        num_ctx=num_ctx)
    return provider, chosen, note


def _ask_json(provider, prompt: str, system: str, raw_sink: list | None = None,
              on_log=None, on_progress=None) -> dict | None:
    """Plan call that tolerates how small models actually answer.

    Two habits are handled: an invalid reply (retry once with a nudge) and —
    much more common — a reply that is cut off mid-object. Continuing the JSON
    from where the model stopped keeps its copy instead of throwing the whole
    plan away for a missing brace.
    """
    from brain.providers.base import parse_json

    def say(line: str) -> None:
        if on_log:
            try:
                on_log(line)
            except Exception:
                pass

    def ask(text_prompt: str, temperature: float, max_tokens: int) -> str:
        """Streamed so the planning bar keeps moving while the model writes."""
        seen: dict = {"chars": 0}

        def on_token(delta: str) -> None:
            seen["chars"] += len(delta)
            if on_progress:
                try:
                    on_progress(min(0.98, seen["chars"] / 3200.0))
                except Exception:
                    pass

        return _stream(provider, text_prompt, on_token=on_token,
                       temperature=temperature, max_tokens=max_tokens, system=system)

    attempts = [prompt, prompt + "\n\nYour previous reply was not valid JSON. "
                                 "Reply with ONLY the JSON object, starting with { and ending with }."]
    for i, text_prompt in enumerate(attempts):
        try:
            text = ask(text_prompt, temperature=0.25, max_tokens=2600)
        except Exception as e:
            if raw_sink is not None:
                raw_sink.append(f"[error] {e}")
            continue
        if raw_sink is not None:
            raw_sink.append(f"[attempt {i + 1}]\n{text}")
        plan = parse_json(text)
        if isinstance(plan, dict) and plan.get("sections"):
            return plan
        if text.rstrip() and not text.rstrip().endswith("}"):
            say("planner reply was cut off — continuing the JSON")
            try:
                more = ask(text.rstrip()
                           + "\n\nContinue the JSON object from exactly where it "
                             "stopped and close it. Output only the rest of the JSON.",
                           temperature=0.15, max_tokens=1600)
                if raw_sink is not None:
                    raw_sink.append(f"[continue {i + 1}]\n{more}")
                plan = parse_json(text.rstrip() + more.strip())
                if isinstance(plan, dict) and plan.get("sections"):
                    return plan
            except Exception as e:
                if raw_sink is not None:
                    raw_sink.append(f"[continue error] {e}")
        if i == 0:
            say("planner reply was not usable — retrying once")
    return None


def _strip_fences(text: str) -> str:
    raw = (text or "").replace("\r\n", "\n").strip()
    fence = re.search(r"```(?:html|HTML)?\s*\n(.*?)(?:```|\Z)", raw, re.S)
    if fence and "<" in fence.group(1):
        raw = fence.group(1).strip()
    return re.sub(r"^(?:Sure|Here(?:'s| is)[^\n]*|Continuing[^\n]*)[:\s]*", "", raw,
                  flags=re.I).strip()


def _stream(provider, prompt: str, on_token=None, temperature: float = 0.3,
            max_tokens: int | None = 5000, system: str | None = None) -> str:
    """Stream when the provider supports it, otherwise one blocking call."""
    system = WRITE_SYSTEM if system is None else system
    if hasattr(provider, "stream"):
        return provider.stream(prompt, system=system, on_token=on_token,
                               temperature=temperature, max_tokens=max_tokens)
    text = provider.generate(prompt, system=system, temperature=temperature,
                             max_tokens=max_tokens)
    if on_token:
        on_token(text)
    return text


def _ask_html(provider, prompt: str, on_progress=None) -> str:
    """Stream the whole file so progress is real, not a spinner."""
    seen = {"chars": 0}

    def on_token(delta: str) -> None:
        seen["chars"] += len(delta)
        if on_progress:
            on_progress(min(0.98, seen["chars"] / 26000.0))

    # The prompt (plan + rules ≈ 2k tokens) must still fit inside num_ctx, so
    # the output budget stays under it: 2k + 5k < 8192.
    text = _stream(provider, prompt, on_token=on_token, temperature=0.35,
                   max_tokens=5000)
    return extract_html(text)


def _finish_truncated(provider, html: str, brief: str, on_log=None,
                      rounds: int = 2) -> str:
    """Ask the model to continue a file that was cut off mid-document.

    Local models hit the token cap inside <style> surprisingly often; the
    cheapest fix is to let them finish what they started instead of paying for
    a whole second attempt.
    """
    for _ in range(rounds):
        low = html.lower()
        if "<body" in low and "</html>" in low:
            return html
        tail = html[-2500:]
        prompt = ("You are CONTINUING a file that was cut off. Here is the end of what you had "
                  f"written:\n---\n{tail}\n---\nContinue from exactly that point and finish the "
                  "document. Do not repeat anything already written and do not restart the "
                  "file. Output only the remaining markup, continuing immediately after the "
                  f"last character above.\n\nBrief: {brief}\n\n{WRITE_RULES}")
        try:
            more = _stream(provider, prompt, temperature=0.3, max_tokens=4000)
        except Exception as e:
            if on_log:
                on_log(f"continuation failed: {e}")
            return html
        frag = _strip_fences(more)
        if not frag or frag[:80] in html[-3000:]:
            if on_log:
                on_log("model did not continue the file")
            return html
        before = len(html)
        html = html.rstrip() + "\n" + frag
        if on_log:
            on_log(f"continued the file: +{len(html) - before} chars")
    return html


def _plan_prompt(brief: str, kind: str) -> str:
    goal = {"portfolio": "a personal portfolio page",
            "website": "a marketing/business website",
            "webapp": "a single-page web application"}.get(kind, "a web page")
    return (f"Brief: {brief}\n\nDesign {goal}. {PLAN_RULES}")


def _design_block(preset: dict | None) -> str:
    """The chosen preset, stated plainly so a model-written page matches it."""
    if not preset:
        return ""
    accent2 = str(preset.get("accent2") or "")
    secondary = (f" with {accent2} as the secondary accent"
                 if accent2 and accent2.lower() != str(preset.get("accent")).lower() else "")
    return (
        f"\n\nDESIGN PRESET — {preset.get('label')} "
        f"(studio: {preset.get('studio')}): {preset.get('summary')}\n"
        f"- Use {preset.get('accent')}{secondary}. No other accent colours.\n"
        "- Keep the studio's typographic character and spacing rhythm; do not\n"
        "  restyle it into a generic template.\n"
    )


def _image_block(images: list[dict]) -> str:
    """Local photos the page must use, with the credit line they require."""
    if not images:
        return ""
    rows = "\n".join(
        f'- {img["path"]}  (alt: {img.get("alt") or "photograph"}'
        + (f'; credit: {img["credit"]}' if img.get("credit") else "") + ")"
        for img in images)
    credits = "; ".join(
        f'{img.get("alt") or img["path"]} — {img["credit"]}'
        for img in images if img.get("credit"))
    return (
        "\n\nPHOTOGRAPHS (already downloaded next to index.html — use these exact "
        "relative paths, do NOT hotlink and do NOT invent other image URLs):\n"
        f"{rows}\n"
        "Use one as a large hero image and the rest in the work/gallery cards, each "
        'inside a <figure> with a real <img src="..." alt="..." loading="lazy">. '
        "Keep crop-friendly aspect ratios (object-fit: cover). "
        + (f"Add a small credits line in the footer: {credits}. " if credits else "")
    )


def _write_prompt(brief: str, plan: dict, images: list[dict] | None = None,
                  preset: dict | None = None) -> str:
    return (f"Brief: {brief}\n\nApproved plan (JSON):\n{json.dumps(plan, indent=2)}\n"
            f"{_image_block(images or [])}{_design_block(preset)}\n{WRITE_RULES}")


def _repair_prompt(brief: str, plan: dict, problems: list[str], current: str,
                   images: list[dict] | None = None,
                   preset: dict | None = None) -> str:
    listed = "\n".join(f"- {p}" for p in problems[:8])
    head = current[:6000]
    return (f"Brief: {brief}\n\nYou wrote an index.html that fails these checks:\n{listed}\n\n"
            f"Here is the start of your file:\n{head}\n\n"
            f"Rewrite the COMPLETE file, fixing every item above and keeping the plan:\n"
            f"{json.dumps(plan, indent=2)}\n{_image_block(images or [])}{_design_block(preset)}\n{WRITE_RULES}")


# ── Build pipeline ────────────────────────────────────────────────────────

# The plan is a small JSON document, so it does not need the big writer model.
# Measured on this machine (same prompt, same day):
#   qwen2.5-coder:3b  19 s  valid plan (gallery section, real copy)
#   qwen3.5:4b        37 s  valid plan
#   qwen2.5-coder:7b  52 s  valid plan
#   qwen3:8b          88 s  invalid/thin plan
# A 4.6x faster plan is the difference between "one minute" and "one minute
# plus a coffee", and the small model is measurably *better* at this job.
_FAST_PLANNER_MODELS = ("qwen2.5-coder:3b", "qwen3.5:4b", "qwen2.5-coder:7b",
                        "qwen3:8b")

# Wall-clock budget for the bespoke (model-written) pass. Beyond it the page
# that already passed verification is what the user gets.
WRITER_TIMEOUT = 180.0


def _planner_provider(preferred: str = ""):
    """Provider for the plan step: Gemini when configured, else the fastest local model."""
    if not preferred:
        cloud = _gemini_provider(420)
        if cloud is not None:
            return cloud
    return _local_planner_provider(preferred)


def _local_planner_provider(preferred: str = ""):
    """The fastest installed local model that plans well."""
    from core.crown_bridge import list_models, load_config
    from brain.providers.openai_compat import OpenAICompatProvider

    cfg = load_config()
    installed = list_models(cfg["ollama_url"])
    if not installed:
        raise RuntimeError(
            "No local models are installed. Run `ollama pull gemma4:12b` and retry.")
    chosen = ""
    if preferred:
        chosen = next((m for m in installed
                       if m == preferred or m.split(":")[0] == preferred), preferred)
    if not chosen:
        chosen = next((m for m in _FAST_PLANNER_MODELS
                       if any(i == m or i.startswith(m) for i in installed)),
                      installed[0])
    provider = OpenAICompatProvider(base_url=cfg["ollama_url"], model=chosen,
                                    timeout=420, num_ctx=6144)
    return provider, chosen


def build_site(brief: str, out_dir: Path | str, kind: str = "portfolio",
               model: str = "", attempts: int = 2, browser: bool = False,
               on_phase=None, on_log=None, provider=None, cancelled=None,
               speed: str = "fast", planner_model: str = "",
               studio: str = "") -> dict:
    """Build one index.html. Returns a result dict; never raises for model errors.

    Two speeds, both ending in a verified page:

        "fast"   (default) plan → render → verify ≈ one minute. The page exists
                 the moment the copy exists; the design comes from
                 render_plan_site(), which is responsive, accessible and passes
                 the browser audit.
        "custom" fast first, then the writer model rewrites the page as bespoke
                 HTML. The rendered page is kept and restored whenever the model
                 version fails verification, so the extra minutes can never cost
                 the user a working site.

    on_phase(name, pct, detail)  phase-level progress (0..1)
    on_log(line)                 human-readable log line
    """
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = out_dir / "index.html"
    rendered = out_dir / "index.rendered.html"
    custom = out_dir / "index.custom.html"
    for stale in (index, rendered, custom):
        if stale.exists():
            stale.unlink()

    def phase(name: str, pct: float, detail: str = "") -> None:
        if on_phase:
            try:
                on_phase(name, pct, detail)
            except Exception:
                pass

    def log(line: str) -> None:
        if on_log:
            try:
                on_log(line)
            except Exception:
                pass

    result = {
        "ok": False, "path": str(index), "kind": kind, "model": model,
        "plan": {}, "attempts": [], "notes": [], "bytes": 0, "mode": "render",
        "checks": {}, "browser": {}, "seconds": 0.0, "used_fallback": False,
        "planner_model": "", "studio": "", "preset": "",
    }

    # 0 ── the look. Fifty-plus presets are scored against the brief, the best
    # matches are kept, and the brief's own hash picks between near-ties: the
    # same brief rebuilds the same way, a different one usually gets a
    # different design instead of the category's first preset every time.
    preset = choose_preset(brief, kind, seed=out_dir.name)
    result["preset"] = preset["id"]
    result["studio"] = preset["studio"]
    log(f"design preset: {preset['label']} — {preset['studio']} studio")

    # Defensive: an application must never be dressed up as a page. The action
    # layer routes these to the coding agent, and this refuses rather than
    # rendering a marketing page for a dashboard if anything calls it directly.
    if is_app_brief(brief):
        result["error"] = (
            "This request is an application (dashboard, data tool, login or API "
            "integration), not a page. Applications are built as real files by "
            "the coding agent — crown_code routes them there. The page renderer "
            "refuses instead of shipping a marketing page with the words changed.")
        log(result["error"])
        phase("failed", 1.0, result["error"])
        result["seconds"] = round(time.time() - t0, 1)
        return result

    def stopped() -> bool:
        return bool(cancelled and cancelled())

    def verify(path: Path) -> tuple[bool, list[str], dict]:
        """Mechanical repair + static rules + optional Chromium audit."""
        fixed = repair_html(path, kind, plan.get("brand", ""))
        if fixed:
            log("Auto-repaired: " + ", ".join(fixed))
        ok, problems = check_html(path, kind)
        audit = browser_audit(path) if (browser and ok) else {}
        if audit.get("status") == "failed":
            ok = False
            problems = problems + audit["problems"]
        return ok, problems, audit

    if stopped():
        result["cancelled"] = True
        result["seconds"] = round(time.time() - t0, 1)
        return result

    # 1 ── a page exists in seconds, from the built-in plan. Speed here is
    # not a nicety: it is what makes the assistant's answer to "what are you
    # building?" a working link instead of a promise.
    plan = fallback_plan(brief, kind)
    phase("rendering", 0.08, "Rendering a first page from the built-in plan")
    html, studio_key = render_studio_page(plan, kind, brief, seed=out_dir.name,
                                          studio=studio or preset["studio"])
    html = apply_preset_css(html, preset)
    index.write_text(html, encoding="utf-8")
    result["studio"] = studio_key
    ok, problems, audit = verify(index)
    rendered.write_text(index.read_text(encoding="utf-8"), encoding="utf-8")
    result["attempts"].append({"attempt": "render", "problems": problems,
                               "bytes": index.stat().st_size,
                               "browser": audit.get("status", "not run")})
    log(f"first page: {index.stat().st_size} bytes — "
        + ("passes" if ok else f"failed: {problems[:2]}"))
    if ok:
        result.update({"ok": True, "mode": "render", "browser": audit,
                       "checks": {"problems": []}})

    # 2 ── the planner writes the real copy and the page is re-rendered with it
    # (a small JSON call, and it never leaves the user without a page)
    phase("planning", 0.12, f"Planning with {result['planner_model'] or 'the planner model'}")
    plan_provider = None
    if provider is None:
        try:
            plan_provider, planner = _planner_provider(planner_model)
            result["planner_model"] = planner
            log(f"planner: {planner}")
            phase("planning", 0.12, f"Planning with {planner}")
        except Exception as e:
            result["notes"].append(str(e))
            log(str(e))
    raw_plan: list[str] = []
    model_plan = _ask_json(
        plan_provider or provider, _plan_prompt(brief, kind), PLAN_SYSTEM,
        raw_sink=raw_plan, on_log=log,
        on_progress=lambda f: phase("planning", 0.12 + 0.10 * f,
                                    f"Planning the copy — {int(f * 100)}% of the plan"))
    if not model_plan and plan_provider is not None:
        # Gemini-first, local fallback: a cloud call that produced no plan must
        # not cost the page its real copy when the local planner is available.
        try:
            local_plan_provider, local_planner = _local_planner_provider(planner_model)
            if local_plan_provider is not plan_provider:
                log(f"no plan from {result.get('planner_model') or 'the cloud planner'} "
                    f"— trying {local_planner}")
                model_plan = _ask_json(
                    local_plan_provider, _plan_prompt(brief, kind), PLAN_SYSTEM,
                    raw_sink=raw_plan, on_log=log,
                    on_progress=lambda f: phase(
                        "planning", 0.12 + 0.10 * f,
                        f"Planning the copy — {int(f * 100)}% of the plan"))
                if model_plan:
                    result["planner_model"] = local_planner
        except Exception as e:
            result["notes"].append(f"local planner unavailable: {e}")
    plan, from_model = normalise_plan(model_plan, brief, kind)
    result["plan"] = plan
    (out_dir / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    if raw_plan:
        (out_dir / "plan.raw.txt").write_text("\n\n".join(raw_plan), encoding="utf-8")
    if not from_model:
        result["notes"].append("planner reply was missing or too thin; kept the built-in plan")
        log("Planner reply missing or too thin — keeping the built-in plan")
    else:
        phase("re-rendering", 0.26, "Re-rendering the page with the planner's copy")
        html, studio_key = render_studio_page(plan, kind, brief, seed=out_dir.name,
                                              studio=studio or preset["studio"])
        html = apply_preset_css(html, preset)
        index.write_text(html, encoding="utf-8")
        result["studio"] = studio_key
        ok2, problems2, audit2 = verify(index)
        result["attempts"].append({"attempt": "render-copy", "problems": problems2,
                                   "bytes": index.stat().st_size,
                                   "browser": audit2.get("status", "not run")})
        if ok2:
            rendered.write_text(index.read_text(encoding="utf-8"), encoding="utf-8")
            result.update({"ok": True, "mode": "render", "browser": audit2,
                           "checks": {"problems": []}})
            log("page upgraded with the planner's copy")
        else:
            # never trade a working page for a broken one
            index.write_text(rendered.read_text(encoding="utf-8"), encoding="utf-8")
            result["notes"].append("planner copy failed verification; kept the first page")
            log(f"planner copy failed checks {problems2[:2]} — kept the first page")
    log(plan_summary(plan))

    # 2.5 ── real photographs for the page (optional, cached, offline-safe)
    # Text-only portfolios are the reason this exists. Failure is invisible:
    # the page renders exactly as before when nothing can be downloaded.
    images: list[dict] = []
    try:
        from core.site_images import fetch_for, photo_query
        phase("images", 0.3, "Finding photographs for the page")
        images = fetch_for(photo_query(brief, plan), out_dir)
        if images:
            result["images"] = [img["path"] for img in images]
            log(f"{len(images)} photo(s) downloaded into assets/")
        else:
            log("no photos available — keeping the CSS artwork")
    except Exception as e:
        result["notes"].append(f"images unavailable: {e}")
        log(f"images unavailable: {e}")
    if stopped():
        result["cancelled"] = True
        result["seconds"] = round(time.time() - t0, 1)
        return result

    # 3 ── optional bespoke design from the writer model
    if speed != "fast" and not stopped():
        writer = provider
        writer_is_local = True
        if writer is None:
            try:
                # A writer that never finishes must not hold the verified page
                # hostage: the rendered page is already on disk, so the bespoke
                # pass gets a budget and then the page ships as rendered.
                writer, writer_model, note = _provider(model, timeout=WRITER_TIMEOUT)
                result["model"] = writer_model
                writer_is_local = str(note) != "gemini"
                if note:
                    result["notes"].append(
                        "writer: gemini" if note == "gemini" else note)
            except Exception as e:
                result["notes"].append(f"writer unavailable: {e}")
                log(f"writer unavailable: {e}")
        if writer is not None:
            custom_ok = False
            # Phase weights: writing dominates a build, so the streamed file
            # fraction is mapped across most of the bar.
            base_pct = 0.35
            for attempt in range(1, attempts + 1):
                if stopped():
                    result["cancelled"] = True
                    break
                span = (0.45 if attempt == 1 else 0.08)
                phase("writing", base_pct, f"Writing bespoke index.html (attempt {attempt})")

                def on_write_progress(fraction: float, _base=base_pct, _span=span) -> None:
                    phase("writing", _base + _span * fraction,
                          f"Writing index.html — {int(fraction * 100)}% of the file")

                html = ""
                try:
                    prompt = (_write_prompt(brief, plan, images, preset) if attempt == 1
                              else _repair_prompt(
                                  brief, plan, result["attempts"][-1]["problems"],
                                  custom.read_text(encoding="utf-8", errors="replace")
                                  if custom.exists() else index.read_text(encoding="utf-8", errors="replace"),
                                  images, preset))
                    html = _ask_html(writer, prompt, on_progress=on_write_progress)
                    html = _finish_truncated(writer, html, brief, on_log=log)
                except Exception as e:
                    log(f"model write failed: {type(e).__name__}: {e}")
                if html:
                    custom.write_text(html, encoding="utf-8")
                    phase("writing", 0.8, f"Model wrote {len(html)} chars — verifying")
                else:
                    log("model returned no usable HTML")
                    if not writer_is_local:
                        # Gemini-first, local fallback: one failed cloud write
                        # does not end the bespoke pass while Ollama can write.
                        try:
                            writer, writer_model, _note = _local_provider(
                                model, timeout=WRITER_TIMEOUT)
                            writer_is_local = True
                            result["model"] = writer_model
                            log(f"falling back to the local model: {writer_model}")
                            continue
                        except Exception as e:
                            result["notes"].append(f"local writer unavailable: {e}")
                    break

                phase("verifying", 0.85, "Checking the model's design")
                cok, cproblems, caudit = verify(custom)
                result["attempts"].append({"attempt": attempt, "problems": cproblems,
                                           "bytes": custom.stat().st_size if custom.exists() else 0,
                                           "browser": caudit.get("status", "not run")})
                log(f"attempt {attempt}: {'pass' if cok else 'fail'}"
                    + ("" if cok else f" — {cproblems[:3]}"))
                if cok:
                    index.write_text(custom.read_text(encoding="utf-8"), encoding="utf-8")
                    result.update({"ok": True, "mode": "model", "browser": caudit,
                                   "checks": {"problems": []}})
                    custom_ok = True
                    break
                base_pct = 0.88
            if not custom_ok and not result.get("cancelled"):
                # keep the verified rendered page: the extra minutes are free
                # only if failure costs nothing.
                index.write_text(rendered.read_text(encoding="utf-8"), encoding="utf-8")
                result["notes"].append(
                    "bespoke design failed verification — shipped the verified rendered page")
                log("Model design kept the page unverified — shipped the rendered page")

    # 4 ── acceptance checklist: every promise in the plan, verified
    try:
        html_now = index.read_text(encoding="utf-8", errors="replace") if index.exists() else ""
        checklist = acceptance_checklist(html_now, kind, plan)
        passed_items, total, failing = checklist_summary(checklist)
        result["checklist"] = checklist
        result["checklist_score"] = f"{passed_items}/{total}"
        log(f"acceptance checklist {passed_items}/{total}"
            + (f" — open: {'; '.join(failing[:3])}" if failing else " — all items met"))
    except Exception as e:
        log(f"checklist unavailable: {e}")

    result["bytes"] = index.stat().st_size if index.exists() else 0
    result["seconds"] = round(time.time() - t0, 1)
    result["mode"] = result.get("mode") or "render"
    if speed == "fast":
        # No writer ran in fast mode — saying "model: qwen3:8b" would claim
        # work that did not happen.
        result["model"] = ""
    phase("done" if result["ok"] else "failed", 1.0,
          f"{result['mode']} · {result['bytes']} bytes in {result['seconds']}s")
    return result
