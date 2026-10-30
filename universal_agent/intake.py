"""Intake: read the request, decide what kind of work it is, and ask only what
the work genuinely cannot proceed without.

This is deterministic on purpose. A model that invents the missing requirement
also invents the build that satisfies it, so classification, question
selection, defaults and acceptance criteria are rules that can be tested.

Questions are split into:

* required — a value cannot be assumed safely (which file to analyse, what an
  unnamed document is about);
* optional — has a stated default; the task proceeds and records the
  assumption in the brief instead of stalling on a preference.

Answers already present in the request are never asked again.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from universal_agent import security

INTENTS = ("software", "research", "documents", "data", "images",
           "browser", "general")
_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.I)

_IMAGE_VERB = re.compile(
    r"\b(resize|rescale|crop|rotate|convert|compress|watermark|transparent|"
    r"edit|retouch|upscale|generate|create|make|draw)\b", re.I)
_IMAGE_NOUN = re.compile(
    r"\b(image|images|photo|photos|picture|pictures|png|jpe?g|webp|logo|artwork|"
    r"illustration|thumbnail|banner)\b", re.I)
_DOC_WORD = re.compile(
    r"\b(word|docx|pdf|powerpoint|pptx|slide|slides|deck|presentation|"
    r"excel|spreadsheet|workbook|xlsx|report|memo|whitepaper)\b", re.I)
_BUILD_WORD = re.compile(
    r"\b(build|create|make|develop|implement|code|program|app|application|"
    r"website|webpage|web page|api|script|cli|portfolio|dashboard|debug|fix|"
    r"refactor|bug|test|deploy|scaffold|prototype)\b", re.I)
_DATA_WORD = re.compile(
    r"\b(analy[sz]e|analysis|dataset|data set|csv|statistic|stats|aggregate|"
    r"correlat|pivot|summari[sz]e|forecast|clean)\b", re.I)
_RESEARCH_WORD = re.compile(
    r"\b(research|investigate|compare|comparison|benchmark|survey|review|"
    r"evaluate|find out|look into|state of|landscape|pros and cons|"
    r"github|repository|repositories|sources|citations?)\b", re.I)
_FILE_TOKEN = re.compile(
    r"([A-Za-z]:\\[^\s\"']+|[\w./\\-]+\.(?:csv|xlsx|xls|json|docx|pdf|pptx|"
    r"png|jpe?g|webp|txt))", re.I)
_DEPTH_WORD = re.compile(r"\b(quick|brief|short|standard|deep|thorough|"
                         r"detailed|exhaustive)\b", re.I)
_FORMAT_WORD = re.compile(r"\b(markdown|md|report|memo|docx|pdf|pptx|"
                          r"slides|brief)\b", re.I)


def classify(request: str) -> str:
    """The intent that owns this request. Rules are ordered by specificity."""
    text = str(request or "").strip()
    if not text:
        return "general"
    if _IMAGE_VERB.search(text) and _IMAGE_NOUN.search(text):
        return "images"
    # A request that opens with a research verb is research work even when it
    # also names the report format it wants at the end. A document request
    # that merely mentions "research" as a subject does not qualify.
    if (re.match(r"^\s*(please\s+)?(research|investigate|compare|survey|"
                 r"review|evaluate|find out|look into)\b", text, re.I)
            or re.search(r"\b(compare|investigate|find out|look into|benchmark)"
                         r"\b", text, re.I)):
        return "research"
    if (_URL_RE.search(text) and re.search(
            r"\b(open|visit|navigate|go to|screenshot|scrape|check|inspect|fetch|read)\b",
            text, re.I) and not re.search(
            r"\b(build|create|make|develop|code|app|application|api|script|cli)\b",
            text, re.I)):
        return "browser"
    # A request that opens with a build verb is asking for something to be
    # built. "Build a churn report with CSV export" names a feature of the
    # tool, not a dataset to analyse, so it must not be claimed by the
    # document/data branches below. Naming a real document format overrides
    # this reading: "Build a slide deck" is still a document request.
    if (re.match(r"^\s*(please\s+)?(build|develop|implement|code|program|"
                 r"scaffold|prototype)\b", text, re.I)
            and not re.search(r"\b(powerpoint|pptx|slides?|deck|presentation|"
                              r"word|docx|pdf|excel|spreadsheet|workbook|xlsx|"
                              r"memo|whitepaper)\b", text, re.I)):
        return "software"
    if _DOC_WORD.search(text) and re.search(
            r"\b(create|make|build|write|generate|prepare|produce|draft|"
            r"convert|edit|update)\b", text, re.I):
        # "Analyse this Excel file" is data work even though it names Excel.
        if _DATA_WORD.search(text) and not re.search(
                r"\b(powerpoint|slides|presentation|word|docx|pdf)\b", text, re.I):
            return "data"
        return "documents"
    # Navigation without a pasted URL is still a browser task — it is exactly
    # the case where the agent must ask which page to open.
    if (re.search(r"\b(open|visit|browse|navigate|go to)\b", text, re.I)
            and re.search(r"\b(website|web[\s-]?page|webpage|site|url|page)\b",
                          text, re.I)):
        return "browser"
    if _BUILD_WORD.search(text) and not (
            _DATA_WORD.search(text) and not re.search(
                r"\b(build|create|make|app|application|website|api|portfolio|"
                r"dashboard|fix|debug|code|script|cli)\b", text, re.I)):
        return "software"
    if _DATA_WORD.search(text):
        return "data"
    if _RESEARCH_WORD.search(text):
        return "research"
    return "general"


def workspace_root() -> Path:
    """Where task workspaces live, matching Crown Code's convention."""
    desktop = Path.home() / "Desktop"
    base = desktop if desktop.is_dir() else Path.home()
    return base / "keys_Creations" / "universal"


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9 _-]", "", str(text or "").lower())
    s = re.sub(r"\s+", "-", s).strip("-")
    return s[:38] or "project"


def create_workspace(request: str, task_id: str, base: str | Path | None = None) -> Path:
    root = Path(base).expanduser() if base else workspace_root()
    root = root / f"{time.strftime('%Y%m%d')}-{_slug(request)}-{task_id}"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _question(slot: str, question: str, *, hint: str = "", default: str = "",
              options: list[str] | None = None, required: bool = True,
              why: str = "") -> dict:
    return {"slot": slot, "question": question, "hint": hint,
            "default": default, "options": list(options or []),
            "required": bool(required), "why": why}


def _has(text: str, pattern: re.Pattern) -> bool:
    return bool(pattern.search(text or ""))


def extract_input_file(request: str) -> str:
    """First existing file path named in the request (read-only input)."""
    for match in _FILE_TOKEN.finditer(str(request or "")):
        raw = match.group(1).strip().strip("\"'")
        candidates = [Path(raw)]
        if not Path(raw).is_absolute():
            candidates += [Path.home() / raw, Path.cwd() / raw]
        for cand in candidates:
            try:
                if cand.is_file():
                    return str(cand.resolve())
            except Exception:
                continue
    return ""


def _software_questions(request: str) -> list[dict]:
    try:
        from core.brief_spec import analyse_brief, get_smart_defaults
        analysis = analyse_brief(request)
        artifact = analysis.get("artifact", "app")
        defaults = get_smart_defaults(request, artifact)
        out = []
        for q in analysis.get("questions", [])[:4]:
            slot = q.get("slot", "requirement")
            # For software tasks, only essential anchor slots are strictly required to start;
            # visual theme and front-end stack fall back to recommended defaults.
            if artifact in ("site", "page"):
                is_req = (slot == "subject")
            elif artifact == "app":
                is_req = (slot in ("data_source", "input", "input_file"))
            else:
                is_req = (slot in ("subject", "goal", "data_source", "input_file"))
            def_val = defaults.get(slot, "") if not is_req else ""
            out.append(_question(
                slot, q.get("ask", "Missing requirement"),
                hint=q.get("examples", ""), default=def_val, required=is_req, why=q.get("why", "")))
        return out
    except Exception:
        return []


def analyse(request: str, intent: str = "", answers: dict | None = None
            ) -> dict:
    """Questions, defaults and the agreed brief for this request."""
    request = str(request or "").strip()
    intent = intent or classify(request)
    answers = {str(k): str(v) for k, v in (answers or {}).items() if str(v).strip()}
    combined = request + "\n" + "\n".join(f"{k}: {v}" for k, v in answers.items())
    questions: list[dict] = []

    if not request:
        questions.append(_question("goal", "What should this project do?",
                                   required=True))
    elif intent == "software":
        questions += _software_questions(combined)
    elif intent in ("research", "general"):
        if not _has(combined, _DEPTH_WORD):
            questions.append(_question(
                "depth", "How deep should the research go?", required=False,
                default="standard", options=["quick", "standard", "deep"]))
        if not _has(combined, _FORMAT_WORD):
            questions.append(_question(
                "format", "What should the deliverable be?", required=False,
                default="markdown",
                options=["markdown", "word", "pdf"]))
    elif intent == "documents":
        stated = re.search(r"\b(word|docx|pdf|powerpoint|pptx|slides|"
                           r"presentation|excel|spreadsheet|xlsx)\b", combined, re.I)
        if not stated:
            questions.append(_question(
                "format", "Which document format do you need?", required=False,
                default="word",
                options=["word", "pdf", "powerpoint", "excel"]))
        subject = re.sub(r"^(please\s+)?(create|make|build|write|generate|"
                         r"prepare|produce|draft)\s+(a|an|the)?\s*", "", request,
                         flags=re.I).strip()
        if len(subject.split()) < 3:
            questions.append(_question(
                "subject", "What should the document be about?", required=True))
    elif intent == "data":
        if not extract_input_file(combined) and not _FILE_TOKEN.search(combined):
            questions.append(_question(
                "input_file", "Which CSV or Excel file should I analyse?",
                hint="full path to the file", required=True))
        if not re.search(r"\b(what|which|how many|trend|compare|summar|total|"
                         r"average|forecast|chart|kpi)\b", combined, re.I):
            questions.append(_question(
                "focus", "What should the analysis answer?", required=False,
                default="Summarise the dataset and report its key numbers"))
    elif intent == "browser":
        if not _URL_RE.search(combined):
            questions.append(_question(
                "url", "Which page should I open?",
                hint="a full https:// URL", required=True))
    elif intent == "images":
        generating = bool(re.search(r"\b(generate|create|draw|make)\b", combined,
                                    re.I)) and not re.search(
            r"\b(resize|crop|convert|rotate|compress|edit|upscale)\b", combined, re.I)
        if not generating and not extract_input_file(combined) and \
                not _FILE_TOKEN.search(combined):
            questions.append(_question(
                "input_file", "Which image should I work on?",
                hint="full path to the image", required=True))
        if not re.search(r"\b(resize|crop|convert|rotate|generate|inspect|"
                         r"analyse|analyze|compress|upscale)\b", combined, re.I):
            questions.append(_question(
                "operation", "What should happen to the image?", required=False,
                default="inspect",
                options=["inspect", "resize", "crop", "convert"]))

    answered_required = [q for q in questions if q["required"]]
    defaults = {}
    assumptions = []
    for q in questions:
        if q["slot"] in answers:
            continue
        if not q["required"] and q["default"]:
            defaults[q["slot"]] = q["default"]
            assumptions.append(
                f"{q['slot']} not specified — using '{q['default']}'")

    merged = dict(defaults)
    merged.update(answers)
    brief = build_brief(request, intent, merged, assumptions)
    return {
        "intent": intent,
        "questions": questions,
        "pending_required": [q for q in questions
                             if q["required"] and q["slot"] not in answers],
        "answers": merged,
        "defaults": defaults,
        "assumptions": assumptions,
        "brief": brief,
        "ready": not answered_required,
    }


_CRITERIA = {
    "software": [
        "Project files exist inside the task workspace",
        "The build's own verification/tests were run and the result recorded",
        "A README or startup instructions are included",
        "Any part that could not be verified is stated as a limitation",
    ],
    "research": [
        "Every factual claim carries a citation to a retrieved source",
        "At least three sources were inspected, or the shortfall is stated",
        "Contradictory evidence is reported, not hidden",
        "Limitations and unanswered questions are listed",
    ],
    "documents": [
        "The document exists and opens with its matching parser",
        "It contains the requested subject and sections",
        "Its slide/page/sheet count is reported and non-zero",
    ],
    "data": [
        "The dataset was read and its shape reported",
        "Key aggregates are computed from the rows, not invented",
        "Any output workbook reopens successfully",
        "Data limitations (missing values, small sample) are stated",
    ],
    "images": [
        "The output image decodes at the expected dimensions",
        "The original file is preserved unchanged",
        "The applied operation is reported",
    ],
    "browser": [
        "The page was actually loaded (HTTP status recorded)",
        "The captured text and screenshot exist in the workspace",
        "Only read-only actions were performed",
        "Every navigation is recorded in the audit log",
    ],
    "general": [
        "The deliverable exists and can be opened",
        "The result is verified, not merely described",
    ],
}


def build_brief(request: str, intent: str, answers: dict,
                assumptions: list[str] | None = None) -> dict:
    deliverables = {
        "software": ["A working project folder", "Startup instructions",
                     "A verification report"],
        "research": ["A written report with sources"],
        "documents": ["The requested document file"],
        "data": ["An analysis summary", "A workbook or chart when requested"],
        "images": ["The edited or generated image"],
        "browser": ["A page inspection report with screenshot"],
        "general": ["A written deliverable"],
    }.get(intent, ["A deliverable"])
    depth = str(answers.get("depth") or "").strip()
    if intent in ("research", "general") and depth:
        deliverables.append(f"Research depth: {depth}")
    return {
        "goal": request,
        "intent": intent,
        "answers": dict(answers),
        "deliverables": deliverables,
        "acceptance_criteria": list(_CRITERIA.get(intent, _CRITERIA["general"])),
        "assumptions": list(assumptions or []),
        "constraints": [
            "Work only inside the task workspace",
            "Do not delete or overwrite user files without approval",
            "Never claim success for an unverified step",
        ],
    }


def validate_answers(questions: list[dict], answers: dict) -> dict:
    """Normalise submitted answers; refuse a missing required value."""
    clean = {}
    for key, value in (answers or {}).items():
        text = str(value or "").strip()
        if text:
            clean[str(key)] = text
    missing = [q for q in questions
               if q.get("required") and q.get("slot") not in clean]
    if missing:
        raise ValueError(
            "Still needed: " + "; ".join(q["question"] for q in missing))
    return clean


def resolve_input_path(value: str) -> Path:
    """An answer that names a file is checked like any other user input."""
    text = str(value or "").strip().strip("\"'")
    if not text:
        raise security.SecurityError("No file was given.")
    candidates = [Path(text).expanduser()]
    if not Path(text).is_absolute():
        candidates += [Path.home() / text, Path.cwd() / text]
    for cand in candidates:
        try:
            if cand.is_file():
                return security.validate_input_file(cand)
        except security.SecurityError:
            raise
        except Exception:
            continue
    raise security.SecurityError(f"File not found: {text}")


__all__ = ["INTENTS", "classify", "analyse", "build_brief", "create_workspace",
           "workspace_root", "extract_input_file", "validate_answers",
           "resolve_input_path"]
