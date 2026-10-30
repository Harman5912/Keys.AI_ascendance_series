"""Document worker — reuses Keys.AI's real Office/PDF builders.

The builders in ``actions._office_builder`` already produce Word, PDF,
PowerPoint and Excel files with a deterministic plan (and optional cover
images). This worker adds the part a chat reply never had: a file on disk in
the task workspace, returned as an artifact and then reopened by the artifact
validator.

Output format comes from an explicit answer or from the request wording;
nothing is guessed silently beyond the documented Word default.
"""

from __future__ import annotations

import re
from pathlib import Path

from universal_agent import security
from universal_agent.workers import Context, title_for

_FORMAT_LABEL = {"docx": "Word document", "pdf": "PDF", "pptx": "PowerPoint",
                 "xlsx": "Excel workbook"}
_SUFFIX = {"docx": ".docx", "pdf": ".pdf", "pptx": ".pptx", "xlsx": ".xlsx"}


def _format(ctx: Context) -> str:
    raw = str(ctx.params.get("format") or
              (ctx.task.get("answers") or {}).get("format") or "").lower()
    if raw in ("word", "docx"):
        return "docx"
    if raw in ("powerpoint", "pptx", "slides", "presentation"):
        return "pptx"
    if raw in ("excel", "xlsx", "spreadsheet"):
        return "xlsx"
    if raw in ("pdf",):
        return "pdf"
    text = str(ctx.task.get("request") or "").lower()
    if re.search(r"\b(powerpoint|pptx|slide deck|presentation)\b", text):
        return "pptx"
    if re.search(r"\b(excel|xlsx|spreadsheet|workbook)\b", text):
        return "xlsx"
    if re.search(r"\bpdf\b", text):
        return "pdf"
    return "docx"


def _filename(title: str, fmt: str) -> str:
    stem = security.safe_filename(title, default="document", suffix="")
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    return f"{stem[:60]}{_SUFFIX[fmt]}"


def run(ctx: Context) -> dict:
    fmt = _format(ctx)
    title = title_for(str(ctx.task.get("request") or ""))
    instruction = str(ctx.task.get("request") or "")
    answers = ctx.task.get("answers") or {}
    if answers:
        instruction += "\n\nConfirmed requirements:\n" + "\n".join(
            f"- {k}: {v}" for k, v in answers.items())

    ctx.log(f"Documents: building {_FORMAT_LABEL.get(fmt, fmt)} — {title}")
    target = security.resolve_within(
        ctx.workspace, ctx.workspace / _filename(title, fmt))

    try:
        from actions import _office_builder as ob
    except Exception as exc:
        return {"ok": False, "summary": "Document builders unavailable.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": f"The Office builders could not be imported: {exc}",
                "notes": []}

    try:
        if fmt == "docx":
            ob.build_docx(target, title, instruction)
        elif fmt == "pdf":
            ob.build_pdf(target, title, instruction)
        elif fmt == "pptx":
            ob.build_pptx(target, title, instruction)
        else:
            ob.build_xlsx(target, title, instruction)
    except Exception as exc:
        return {"ok": False, "summary": f"{_FORMAT_LABEL[fmt]} build failed.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": f"The {_FORMAT_LABEL[fmt]} builder raised: {exc}",
                "notes": []}

    if not target.is_file() or target.stat().st_size == 0:
        return {"ok": False, "summary": "The builder produced no file.",
                "artifacts": [], "evidence": [], "warnings": [],
                "error": f"No file was written at {target.name}.",
                "notes": []}

    ctx.log(f"Documents: wrote {target.name} "
            f"({target.stat().st_size / 1024:.0f} KB)")
    return {
        "ok": True,
        "summary": f"Created the {_FORMAT_LABEL[fmt]} '{target.name}'.",
        "artifacts": [ctx.artifact(target, fmt, f"{_FORMAT_LABEL[fmt]} deliverable")],
        "evidence": [],
        "warnings": [],
        "error": "",
        "notes": [],
    }


__all__ = ["run"]
