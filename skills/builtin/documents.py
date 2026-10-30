"""Skill: documents and data files — create, read, convert, analyse, edit."""

from __future__ import annotations

from skills.builtin._delegate import run_tool, tool_ready

SKILL = {
    "name": "documents",
    "purpose": "Create and work with Word, Excel, PowerPoint, PDF, CSV and "
               "image files on disk.",
    "version": "1.0.0",
    "group": "documents",
    "capabilities": ["create documents", "read documents", "summarise",
                     "convert formats", "analyse CSV/Excel", "edit in place"],
    "tools": ["file_processor"],
    "permission": "MODERATE",
    "instructions": "This is the tool for documents — not the coding skill. "
                    "Pass a real path with the right extension when creating.",
    "triggers": ["create a word document", "make a spreadsheet",
                 "create a presentation", "summarise this pdf",
                 "convert this file", "analyse this csv"],
    "inputs": {
        "file_path": {"type": "string"},
        "action": {"type": "string"},
        "instruction": {"type": "string"},
        "format": {"type": "string"},
        "find": {"type": "string"},
        "replace": {"type": "string"},
        "cell": {"type": "string"},
        "value": {"type": "string"},
        "sheet": {"type": "string"},
    },
    "outputs": ["the created file path or the extracted content"],
    "timeout": 180.0,
    "tags": ["documents", "office", "data"],
}


def run(parameters: dict, ctx) -> dict:
    return run_tool("file_processor", parameters, ctx)


def verify() -> tuple[bool, str]:
    return tool_ready("file_processor")
