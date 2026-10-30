"""
core/doc_builder.py — let the local model write the document, not just name it.

Why this exists
---------------
`actions/_office_builder.py` builds a complete, styled Word deck or PowerPoint
from a title and an instruction — but with no model it has to fall back on a
*fixed* document plan (a proposal about "import failures", a report about a
fictional team). The file is real; the words are not the user's.

This module closes that gap in the shape the site pipeline already proved:
one JSON-only call to the local Ollama planner asks for the actual copy —
subtitle, sections, bullets, tables — and the deterministic writer turns that
into the .docx / .pptx. If the model cannot answer, the caller falls back to the
built-in plan and says so, so a document is never worse than before.
"""

from __future__ import annotations

import json
import re

# Block shapes the office writer understands: _p / _b / _n / _t.
_BLOCK_LIMIT = 6      # sections per plan
_ITEM_LIMIT = 7       # list items per block
_CELL_LIMIT = 90      # characters per table cell
_HEADING_LIMIT = 80

PLAN_SYSTEM = (
    "You write the content of business documents as JSON. You reply with one JSON "
    "object and nothing else."
)

PLAN_RULES = """Return ONLY this JSON object (no prose, no markdown fences):
{
  "subtitle": "one line, max 120 characters",
  "sections": [
    {"heading": "Section heading",
     "blocks": [
       ["p", "a paragraph of real, specific prose"],
       ["bullets", ["point one", "point two"]],
       ["numbers", ["ordered step one", "ordered step two"]],
       ["table", ["Header A", "Header B"], ["cell", "cell"]]
     ]}
  ]
}
Rules:
- 4 to __SECTIONS__ sections, in the order a reader needs them.
- Each section has 1 to 4 blocks. Use "table" at least once for data that is
  tabular, with a header row and 2 to 5 data rows of the same length.
- Write the ACTUAL content for the request: real names, numbers, dates,
  decisions. Never "Section 1", "Feature 1", "Lorem ipsum", "TBD" or "insert".
- Keep every string under __CELL__ characters. Valid JSON only."""

# Words a request uses for a count, e.g. "a four-section document".
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
              "seven": 7, "eight": 8, "nine": 9, "ten": 10}

# The planner is the same class of local model the site pipeline uses: fast,
# JSON-capable, installed here.
_PLANNER_ORDER = ("qwen2.5-coder:3b", "qwen3.5:4b", "qwen2.5-coder:7b", "qwen3:8b")


def _provider():
    from core.crown_bridge import list_models, load_config
    from brain.providers.openai_compat import OpenAICompatProvider

    cfg = load_config()
    installed = list_models(cfg["ollama_url"])
    if not installed:
        return None, "no local models installed"
    chosen = next((m for m in _PLANNER_ORDER if any(i == m or i.startswith(m) for i in installed)),
                  installed[0])
    return OpenAICompatProvider(base_url=cfg["ollama_url"], model=chosen,
                                timeout=300, num_ctx=6144), chosen


def _parse_requirements(instruction: str) -> dict:
    """Read the shape the request demands out of the instruction text.

    A brief says things like "A four-section Word document: Revenue Update,
    Lost Contracts, ..." or "A 5-slide deck: the opening, the new lane, the
    roles table (...), the vacancy, and the ask." Those are hard requirements
    — the section count, the section headings, and whether a table is part of
    the deliverable. Passing them to the model as prose is not enough; they
    have to be stated as the shape to build, and checked afterwards.
    """
    req: dict = {"sections": None, "headings": [], "table": False, "slides": None}
    text = instruction or ""

    m = re.search(
        r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)[\s-]*"
        r"(slides?|sections?)\b(.*)", text, re.I)
    if m:
        raw = m.group(1)
        count = int(raw) if raw.isdigit() else _NUM_WORDS.get(raw.lower())
        kind = m.group(2).lower()
        rest = m.group(3)
        if count:
            if kind.startswith("slide"):
                req["slides"] = count
                # The first slide is the title slide, so the content sections
                # are one fewer than the slides.
                req["sections"] = max(1, count - 1)
            else:
                req["sections"] = count
        if ":" in rest:
            topics = rest.split(":", 1)[1]
            topics = re.sub(r"\([^)]*\)", "", topics)      # drop "(Capacity, Role, ...)"
            # Stop at the first aside — the headings come first, the prose
            # about them after a dash.
            topics = re.split(r"\s+[—–-]\s+|\.\s+", topics, maxsplit=1)[0]
            parts = re.split(r",|\band\b", topics)
            headings = [p.strip(" .—–-\t") for p in parts]
            req["headings"] = [h for h in headings if 2 < len(h) < 60][:16]

    # An explicit heading list without a count — "Use exactly these section
    # headings, in this order: Executive Summary, Objectives, ..." — is the
    # same kind of hard requirement. Without this clause the whole shape went
    # unenforced: the model was free to return whatever sections it liked,
    # and documents silently lost their requested Limitations/Future sections.
    if not req["headings"]:
        m = re.search(r"(?:headings?|sections?)[^:\n]{0,60}:\s*(.{8,})",
                      text, re.I)
        if m:
            topics = re.sub(r"\([^)]*\)", "", m.group(1))
            topics = re.split(r"\s+[—–-]\s+|\.\s+", topics, maxsplit=1)[0]
            parts = re.split(r",|\band\b", topics)
            headings = [p.strip(" .—–-\t") for p in parts]
            req["headings"] = [h for h in headings if 2 < len(h) < 60][:16]
            if req["sections"] is None:
                req["sections"] = len(req["headings"])

    req["table"] = bool(re.search(r"\btable\b", text, re.I))
    # Precise figures the request states — "54,200.00", "1,250" — must be
    # USED in the content. A requested total that never appears in the plan
    # turns the document into fiction, and the numbers are usually the point.
    req["figures"] = sorted(set(
        re.findall(r"\b\d[\d,]{3,}(?:\.\d+)?\b", text or "")))
    return req


def _effective_headings(req: dict) -> list[str]:
    """The headings a plan must contain, minus a leading title slide.

    Shared by the prompt shaper and the miss-checker: they must agree on
    what "these headings" means, or the model is asked for one shape and
    judged against another.
    """
    headings = req.get("headings") or []
    if (req.get("slides") and headings
            and len(headings) == (req.get("sections") or 0) + 1):
        return headings[1:]          # the first one is the title slide
    return headings


def _shape_rules(req: dict, doc_type: str) -> str:
    """The shape the plan must have, written for the model to follow."""
    if not req.get("sections") and not req.get("headings"):
        return ""
    lines = []
    if req.get("slides"):
        lines.append(
            f"The deck must have exactly {req['slides']} slides: a title slide plus "
            f"{req['sections']} content slides.")
    elif req.get("sections"):
        lines.append(f"The document must have exactly {req['sections']} sections.")
    headings = _effective_headings(req)
    if headings:
        listed = "\n".join(f"  {i}. {h}" for i, h in enumerate(headings, 1))
        lines.append("Use exactly these section headings, in this order:\n" + listed)
    if req.get("table"):
        lines.append(
            'At least one section must contain a "table" block holding the real '
            "numbers from the request, with a header row and 2 to 5 data rows.")
    if not lines:
        return ""
    return ("\n\nMANDATORY SHAPE (these override the general rules above):\n"
            + "\n".join(lines) + "\n")


def _prompt(title: str, instruction: str, doc_type: str) -> str:
    goal = {"docx": "a Word document", "pptx": "a slide deck",
            "xlsx": "the data tables of a workbook"}.get(doc_type, "a document")
    req = _parse_requirements(instruction)
    rules = (PLAN_RULES.replace("__SECTIONS__", str(_BLOCK_LIMIT))
                       .replace("__CELL__", str(_CELL_LIMIT)))
    # "4 to 6 sections" directly contradicts an enforced "exactly 13" —
    # small models follow the general rule and truncate. When the request
    # names the count, the general rule states THAT count.
    if req.get("sections"):
        rules = rules.replace(
            "- 4 to __SECTIONS__ sections, in the order a reader needs them.",
            "- exactly __SECTIONS__ sections, in the order a reader needs them.")
        rules = rules.replace("__SECTIONS__", str(req["sections"]))
    return (f"Title: {title}\nRequest: {instruction}\n\nWrite the content for {goal}. "
            + rules + _shape_rules(req, doc_type))


def _ask_plan(provider, title: str, instruction: str, doc_type: str,
              on_log=None) -> dict | None:
    from brain.providers.base import parse_json

    prompt = _prompt(title, instruction, doc_type)
    req = _parse_requirements(instruction)
    nudge = ""
    for attempt in (0, 1, 2):
        try:
            # 2200 tokens truncated multi-section plans and 14-slide decks
            # mid-JSON, which then failed to parse and fell back to the
            # generic plan. Headroom for a full-length plan, still inside
            # the provider's 6144-token context.
            text = provider.generate(prompt + nudge, system=PLAN_SYSTEM,
                                     temperature=0.3, max_tokens=3800)
        except Exception as err:
            if on_log:
                on_log(f"document planner unavailable: {err}")
            return None
        raw = parse_json(text)
        if isinstance(raw, dict) and isinstance(raw.get("sections"), list):
            problem = _plan_missed(raw, req, doc_type)
            if problem:
                if attempt < 2:
                    nudge = (f"\n\nYour last reply {problem} Reply with the full JSON "
                             "object again, including the missing part.")
                    if on_log:
                        on_log(f"planner {problem} — asking for it again")
                    continue
                # Final attempt still dropped the requested figures. The
                # user asked for these exact numbers, so the plan carries
                # them deterministically rather than shipping a document
                # that contradicts its own brief.
                if problem.startswith("never used the requested figure"):
                    _inject_figures(raw, req)
                    if on_log:
                        on_log("planner kept dropping the requested figures "
                               "— stating them verbatim in the plan")
            return raw
        if attempt == 0:
            prompt += ("\n\nYour reply was not valid JSON. Reply with ONLY the JSON object, "
                       "starting with { and ending with }.")
    if on_log:
        on_log("document planner returned no usable plan")
    return None


def _canon_number(token: str) -> str:
    """Canonical form of a number token: 54,200.00 == 54200 == 54,200."""
    token = token.replace(",", "")
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token


def _inject_figures(raw: dict, req: dict) -> None:
    """Last-resort repair: state the requested figures verbatim.

    Called only after every retry still dropped them. The user asked for
    these exact numbers, so the plan carries them deterministically rather
    than shipping a document that contradicts its own brief.
    """
    originals = {_canon_number(f): f for f in (req.get("figures") or [])}
    blob = json.dumps(raw, ensure_ascii=False)
    present = {_canon_number(t)
               for t in re.findall(r"\d[\d,]*(?:\.\d+)?", blob)}
    missing = [originals[c] for c in sorted(set(originals) - present)]
    if not missing:
        return
    sections = raw.get("sections") or []
    if not sections:
        return
    line = "Figures stated exactly as requested: " + ", ".join(missing) + "."
    blocks = sections[0].setdefault("blocks", [])
    blocks.insert(0, ["bullets", [line]])


def _plan_missed(raw: dict, req: dict, doc_type: str) -> str:
    """What the returned plan is missing, or "" when it matches the request.

    A Word document whose numbers live only in prose is not what was asked
    for; a four-section request answered with two sections is not either.
    A brief that names "the roles table" wants the table in THAT section, not
    in whichever one the model happened to put it in. All of it is caught
    here and asked for again, rather than silently shipped.
    """
    want_sections = req.get("sections")
    sections = raw.get("sections") or []
    if want_sections:
        got = len(sections)
        if got < want_sections:
            return (f"had {got} sections but {want_sections} were required. "
                    f"Write all {want_sections}, each with its own heading and blocks.")
    # The right NUMBER of sections is not enough: every requested heading
    # must appear by name, or the document ships with the wrong sections
    # (a Limitations section requested by name was silently replaced).
    for heading in _effective_headings(req):
        if _section_for(sections, heading) is None:
            return (f"missed the '{heading}' section. Every requested heading "
                    "must appear as a section heading, in the requested order.")
    # Every precise figure in the request must survive into the content.
    # Compared canonically: the model writing "54,200" for "54,200.00" is
    # the same figure, and must not burn a retry.
    originals = {_canon_number(f): f for f in (req.get("figures") or [])}
    blob = json.dumps(raw, ensure_ascii=False)
    present = {_canon_number(t)
               for t in re.findall(r"\d[\d,]*(?:\.\d+)?", blob)}
    missing = [originals[c] for c in sorted(set(originals) - present)]
    if missing:
        return ("never used the requested figure(s) "
                f"{', '.join(missing[:4])}. The document must state these "
                "exact numbers.")
    # A heading that names a table must carry that table.
    for heading in req.get("headings") or []:
        if "table" not in heading.lower():
            continue
        target = _section_for(sections, heading)
        if target is None:
            continue
        if not any(str(b[0]).lower() in ("table", "t") and _normalise_table(b)
                   for b in target.get("blocks") or []
                   if isinstance(b, (list, tuple)) and b):
            return (f"put no table in the '{target.get('heading', heading)}' section. "
                    "That section MUST contain a table block holding the real "
                    "numbers from the request.")
    if req.get("table") and not _has_table(raw):
        return ("had no table. This document MUST contain at least one table "
                'block: ["table", ["Header A", "Header B"], [["cell", "cell"], '
                '["cell", "cell"]]]. Put the real numbers from the request into '
                "that table.")
    if doc_type == "docx" and not _has_table(raw):
        return ("had no table. This document MUST contain at least one table "
                'block: ["table", ["Header A", "Header B"], [["cell", "cell"], '
                '["cell", "cell"]]]. Put the real numbers from the request into '
                "that table.")
    return ""


def _section_for(sections: list, heading: str) -> dict | None:
    """The section whose heading matches the requested one, case-insensitively."""
    want = heading.strip().lower()
    for section in sections:
        if not isinstance(section, dict):
            continue
        got = str(section.get("heading") or "").strip().lower()
        if got == want:
            return section
    for section in sections:
        if not isinstance(section, dict):
            continue
        got = str(section.get("heading") or "").strip().lower()
        if got and (want in got or got in want):
            return section
    return None


def _has_table(raw: dict) -> bool:
    """True when the model's plan carries a table that can be rendered."""
    for section in (raw.get("sections") or []):
        if not isinstance(section, dict):
            continue
        for block in (section.get("blocks") or []):
            if (isinstance(block, (list, tuple)) and block
                    and str(block[0]).lower() in ("table", "t")
                    and _normalise_table(block)):
                return True
    return False


def _normalise_table(block) -> tuple[list[str], list[list[str]]] | None:
    """Read a table block in either shape the model writes it.

    Two shapes occur in practice and both must work, or the table is silently
    dropped and the document loses the numbers it was asked for:

        ["table", ["Month", "Revenue"], [["Jan", "$20M"], ["Feb", "$30M"]]]
        ["table", ["Month", "Revenue"], ["Jan", "$20M"], ["Feb", "$30M"]]

    Returns (headers, rows) or None when the block carries no usable table.
    """
    if not isinstance(block, (list, tuple)) or len(block) < 3:
        return None
    headers = [str(h).strip()[:_CELL_LIMIT] for h in block[1]
               if not isinstance(h, (list, tuple))]
    headers = [h for h in headers if h]
    if not headers:
        return None

    tail = list(block[2:])
    flat_rows = (tail and all(isinstance(r, (list, tuple)) for r in tail)
                 and all(not isinstance(c, (list, tuple))
                         for r in tail for c in r))
    if flat_rows:
        rows = [[str(c).strip()[:_CELL_LIMIT] for c in r] for r in tail]
    elif tail and isinstance(tail[0], (list, tuple)):
        rows = [[str(c).strip()[:_CELL_LIMIT] for c in r]
                for r in tail[0] if isinstance(r, (list, tuple))]
    else:
        return None
    rows = [r[:len(headers)] for r in rows[:5] if r]
    if not rows:
        return None
    return headers, rows


def _clean_plan(raw: dict, title: str, req: dict | None = None) -> dict:
    """Coerce whatever the model returned into the shape the writer renders."""
    req = req or {}
    subtitle = str(raw.get("subtitle") or "").strip()[:_HEADING_LIMIT + 40]
    # The clip must never cut BELOW what the request demanded: an enforced
    # 8-section or 13-slide plan validated by _plan_missed was silently
    # truncated to _BLOCK_LIMIT here, at render time.
    keep = max(_BLOCK_LIMIT, len(req.get("headings") or []),
               int(req.get("sections") or 0))
    sections = []
    for sec in (raw.get("sections") or [])[:keep]:
        if not isinstance(sec, dict):
            continue
        heading = str(sec.get("heading") or "").strip()[:_HEADING_LIMIT]
        heading = _tidy_heading(heading, req)
        blocks = []
        for block in (sec.get("blocks") or [])[:4]:
            if not isinstance(block, (list, tuple)) or not block:
                continue
            kind = str(block[0]).lower()
            if kind in ("p", "paragraph", "text"):
                text = " ".join(str(x) for x in block[1:]).strip()[:600]
                if text:
                    blocks.append(("p", text))
            elif kind in ("bullets", "bullet", "b"):
                items = [str(i).strip()[:_CELL_LIMIT + 110]
                         for i in (block[1] if len(block) > 1 else [])]
                items = [i for i in items if i][:_ITEM_LIMIT]
                if items:
                    blocks.append(("bullets", items))
            elif kind in ("numbers", "numbered", "n"):
                items = [str(i).strip()[:_CELL_LIMIT + 110]
                         for i in (block[1] if len(block) > 1 else [])]
                items = [i for i in items if i][:_ITEM_LIMIT]
                if items:
                    blocks.append(("numbers", items))
            elif kind in ("table", "t"):
                table = _normalise_table(block)
                if table:
                    blocks.append(("table", table))
        if heading and blocks:
            sections.append({"heading": heading, "blocks": blocks})
    return {"subtitle": subtitle, "sections": sections}


def _tidy_heading(heading: str, req: dict) -> str:
    """Give a section heading the case a reader expects.

    The model copies the brief's headings verbatim, so "the roles table"
    arrives as a slide title in lower case. When the heading matches a
    requested one, it is re-cased; otherwise it is left alone.
    """
    if not heading:
        return heading
    for wanted in req.get("headings") or []:
        if heading.strip().lower() == wanted.strip().lower():
            # Verbatim: .capitalize() here turned "JSON API Endpoints" into
            # "Json api endpoints" — the user's own casing is the right one.
            return wanted.strip()
    if heading.islower() and len(heading) > 3:
        return heading.capitalize()
    return heading


def to_doc_plan(model_plan: dict, title: str, instruction: str = ""):
    """Turn the model's plan into a DocPlan the deterministic writer can render."""
    from actions._office_builder import DocPlan

    return DocPlan(
        title=title,
        subject=re.sub(r"\s+", " ", instruction or title).strip()[:80] or title,
        kind="model",
        subtitle=str(model_plan.get("subtitle") or ""),
        meta=[("Prepared", "today"), ("Written by", "Keys.ai local model")],
        sections=[{"heading": s["heading"], "blocks": s["blocks"]}
                  for s in model_plan.get("sections", [])],
    )


def to_outline(model_plan: dict, title: str, instruction: str = "") -> list[tuple[str, list[str]]]:
    """Turn the model's plan into the (heading, bullets) pairs the deck renders.

    The first section becomes the title slide's deck line; the rest become one
    slide each. A table stays a table — it is handed over as a dict so the
    deck renderer can draw it with its columns intact.
    """
    subtitle = str(model_plan.get("subtitle") or "").strip()
    outline: list[tuple[str, list[str]]] = [(title, [subtitle] if subtitle else
                                             re.sub(r"\s+", " ", instruction or title)[:110])]
    for section in model_plan.get("sections", []):
        lines: list[str] = []
        for kind, payload in section["blocks"]:
            if kind == "p":
                lines.append(str(payload))
            elif kind in ("bullets", "numbers"):
                lines.extend(str(i) for i in payload)
            elif kind == "table":
                # A table stays a table: the deck renderer draws it as a real
                # table, so the numbers keep their columns instead of being
                # flattened into prose.
                headers, rows = payload
                lines.append({"table": (list(headers), [list(r) for r in rows])})
        lines = lines[:6]
        if lines:
            outline.append((section["heading"], lines))
    return outline


def model_doc_plan(title: str, instruction: str, doc_type: str,
                   on_log=None) -> tuple[dict | None, str]:
    """Ask the local model for the document's actual content.

    Returns (plan, model_name) on success and (None, model_name) when the model
    could not answer — the caller then falls back to the built-in plan.
    """
    provider, model = _provider()
    if provider is None:
        if on_log:
            on_log(model)
        return None, model
    raw = _ask_plan(provider, title, instruction, doc_type, on_log=on_log)
    if not raw:
        return None, model
    plan = _clean_plan(raw, title, _parse_requirements(instruction))
    if not plan["sections"]:
        return None, model
    if on_log:
        on_log(f"document planned by {model} · {len(plan['sections'])} sections")
    return plan, model
