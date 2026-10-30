"""Skill: inspect a project folder before changing it (read-only)."""

from __future__ import annotations

from skills.builtin._delegate import run_tool, tool_ready

SKILL = {
    "name": "repo-inspect",
    "purpose": "Understand a codebase before touching it: file inventory, "
               "symbols, imports and targeted search.",
    "version": "1.0.0",
    "group": "software",
    "capabilities": ["list files", "find symbols", "map imports",
                     "search text", "list tests"],
    "tools": ["repo_inspect"],
    "permission": "SAFE",
    "instructions": "Read-only. Use it before editing so changes are based on "
                    "the real files, never on assumptions.",
    "triggers": ["what is in this project", "where is this defined",
                 "what uses this module", "map this codebase"],
    "inputs": {
        "action": {"type": "string",
                   "description": "summary | search | symbol | file | imports | tests"},
        "path": {"type": "string"},
        "query": {"type": "string"},
        "symbol": {"type": "string"},
    },
    "outputs": ["file, symbol or match listings"],
    "timeout": 90.0,
    "tags": ["code", "read-only", "inspect"],
}


def run(parameters: dict, ctx) -> dict:
    return run_tool("repo_inspect", parameters, ctx)


def verify() -> tuple[bool, str]:
    ready, detail = tool_ready("repo_inspect")
    if not ready:
        return False, detail
    try:
        from actions import repo_tool  # noqa: F401

        return True, "handler and module both load"
    except Exception as exc:
        return False, f"repo tool module failed to import: {exc}"
