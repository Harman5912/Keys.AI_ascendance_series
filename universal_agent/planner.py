"""Planning: turn a brief into concrete steps with measurable acceptance criteria.

The deterministic plan is the guaranteed floor — every intent maps to the
workers that actually exist in this build. A model may enrich the wording and
add criteria, but:

* it runs on a strictly bounded thread (a hung local model cannot stall a task);
* it may not add a step whose worker does not exist;
* any failure, timeout or malformed JSON leaves the deterministic plan intact.

That ordering is deliberate: a plan is only useful if the machinery behind it
is real.
"""

from __future__ import annotations

import json
import re
import threading
import time

from universal_agent import intake  # noqa: F401  (public re-export)
from universal_agent.workers import presets as presets_mod

WORKERS = ("research", "software", "documents", "data", "images",
           "browser")


def _format_from(request: str, answers: dict) -> str:
    blob = f"{request} {answers.get('format', '')}".lower()
    if re.search(r"\b(powerpoint|pptx|slides?|deck|presentation)\b", blob):
        return "pptx"
    if re.search(r"\b(excel|xlsx|workbook|spreadsheet)\b", blob):
        return "xlsx"
    if re.search(r"\bpdf\b", blob):
        return "pdf"
    if re.search(r"\b(word|docx|report|memo|whitepaper)\b", blob):
        return "docx"
    return "docx"


def _image_operation(request: str, answers: dict) -> str:
    blob = f"{request} {answers.get('operation', '')}".lower()
    for op in ("resize", "crop", "convert", "rotate", "inspect", "generate"):
        if op in blob:
            return op
    return answers.get("operation") or "inspect"


def _dimensions(request: str) -> tuple[int, int] | None:
    m = re.search(r"\b(\d{2,4})\s*[x×]\s*(\d{2,4})\b", request)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def deterministic_plan(request: str, brief: dict, intent: str,
                       answers: dict, input_file: str = "") -> dict:
    """Steps, deliverables and criteria that this build can actually execute."""
    steps: list[dict] = []

    def _step(worker: str, title: str, params: dict | None = None,
              requires_approval: bool = False) -> dict:
        return {
            "id": f"s{len(steps) + 1}",
            "worker": worker,
            "title": title,
            "params": params or {},
            "status": "pending",
            "detail": "",
            "requires_approval": bool(requires_approval),
            "started_at": "",
            "ended_at": "",
            "error": "",
            "attempts": 0,
        }

    # Research presets chosen in the panel (GitHub / docs / design references /
    # national search). They are settings, not answers, so they ride along in
    # the step params and the worker decides what each one searches. Answers are
    # stored as text, so "github, docs" and ["github", "docs"] both work.
    presets = presets_mod.parse(answers.get("presets") or [])

    # A build is always preceded by research: the panel's contract is that the
    # build follows what the research found, so every software plan gets a
    # research step first. Presets choose the sources; without them the worker
    # uses its defaults. (Only software intent gets this pre-step — other
    # intents add their own research step below.)
    research_also = intent == "software"

    if research_also:
        steps.append(_step("research", "Research the subject before building",
                           {"depth": answers.get("depth") or "quick",
                            "feed_build": True, "presets": presets}))

    if intent in ("research", "general"):
        steps.append(_step("research", "Research the question and collect evidence",
                           {"depth": answers.get("depth") or "standard",
                            "presets": presets}))
    elif intent == "software":
        # reuse_research is always on: the step only exists because research
        # ran first, and the build must receive that research's findings.
        steps.append(_step("software", "Build and verify the project",
                           {"mode": "build", "reuse_research": True}))
    elif intent == "documents":
        fmt = _format_from(request, answers)
        steps.append(_step("documents", f"Create the {fmt.upper()} deliverable",
                           {"format": fmt}))
    elif intent == "data":
        steps.append(_step("data", "Read, analyse and summarise the dataset",
                           {"input_file": input_file,
                            "focus": answers.get("focus") or ""}))
    elif intent == "images":
        op = _image_operation(request, answers)
        dims = _dimensions(request)
        params = {"operation": op, "input_file": input_file,
                  "format": answers.get("format") or "png"}
        if dims:
            params["width"], params["height"] = dims
        steps.append(_step("images", f"Image task: {op}", params))
    elif intent == "browser":
        match = re.search(r"https?://[^\s<>\"')]+", request, re.I)
        steps.append(_step("browser", "Open the page and capture its content",
                           {"url": match.group(0).rstrip(".,;") if match else
                                   (answers.get("url") or "")}))

    if not steps:
        steps.append(_step("research", "Research the request and report findings",
                           {"depth": answers.get("depth") or "standard",
                            "presets": presets}))

    return {
        "steps": steps,
        "deliverables": list(brief.get("deliverables") or []),
        "acceptance_criteria": list(brief.get("acceptance_criteria") or []),
        "source": "deterministic",
        "note": "",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


_PROMPT = """You are planning a task for a desktop agent. Return ONLY JSON:
{{"deliverables": ["..."], "acceptance_criteria": ["..."], "steps": [{{"title": "..."}}]}}

Rules:
- Keep exactly {n} steps, in the same order.
- Each step title must describe the work, not the code to write.
- Acceptance criteria must be checkable by inspecting a file or running a command.
- Do not invent capabilities, tools, data sources or results.

Request:
{request}

Confirmed requirements:
{answers}
"""


def _strip_fences(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start >= 0 and end > start else text


def _default_complete(prompt: str, system: str) -> str:
    from core.llm_client import complete
    return complete("brain", prompt, system=system, temperature=0.2,
                    max_tokens=700)


def refine(plan: dict, request: str, answers: dict, complete=None,
           timeout: float = 45.0) -> dict:
    """Best-effort model enrichment, bounded in time and never required."""
    complete = complete or _default_complete
    steps = plan.get("steps") or []
    prompt = _PROMPT.format(n=len(steps), request=request,
                            answers=json.dumps(answers, ensure_ascii=False))
    box: dict = {}

    def work():
        try:
            box["raw"] = complete(prompt, "Return only valid JSON.")
        except Exception as exc:
            box["error"] = str(exc)

    thread = threading.Thread(target=work, name="ua-planner", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return {**plan, "note": "Model planning timed out; deterministic plan kept."}
    if box.get("error") or not box.get("raw"):
        return {**plan, "note": "Model planning unavailable; deterministic plan kept."}
    try:
        data = json.loads(_strip_fences(box["raw"]))
    except Exception:
        return {**plan, "note": "Model planning returned invalid JSON; deterministic plan kept."}
    if not isinstance(data, dict):
        return {**plan, "note": "Model planning returned an unexpected shape."}

    new_steps = data.get("steps") or []
    if isinstance(new_steps, list) and len(new_steps) == len(steps):
        for step, raw in zip(steps, new_steps):
            title = str((raw or {}).get("title") or "").strip()[:160]
            if title:
                step["title"] = title

    def _merge(key: str, existing: list[str]) -> list[str]:
        out = list(existing)
        for item in data.get(key) or []:
            text = str(item).strip()[:220]
            if text and text not in out:
                out.append(text)
        return out

    return {
        **plan,
        "steps": steps,
        "deliverables": _merge("deliverables", plan.get("deliverables") or [])[:8],
        "acceptance_criteria": _merge("acceptance_criteria",
                                      plan.get("acceptance_criteria") or [])[:10],
        "source": "model-assisted",
        "note": "Step wording and criteria refined by the configured model.",
    }


def build_plan(request: str, brief: dict, intent: str, answers: dict,
               input_file: str = "", complete=None, use_model: bool = True) -> dict:
    plan = deterministic_plan(request, brief, intent, answers, input_file)
    if not use_model:
        return plan
    return refine(plan, request, answers, complete=complete)


__all__ = ["WORKERS", "deterministic_plan", "refine", "build_plan"]
