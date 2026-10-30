"""Skill: software development through Crown Code.

Crown Code already plans, edits, runs commands and verifies. This skill declares
the contract (what it takes, what it returns, what permission it needs) and
delegates — it does not build a second coding agent.
"""

from __future__ import annotations

from skills.builtin._delegate import run_tool, tool_ready

SKILL = {
    "name": "coding",
    "purpose": "Build, change, debug and verify software in a real project "
               "folder, with real commands and real output.",
    "version": "1.0.0",
    "group": "software",
    "capabilities": ["write code", "modify code", "refactor", "debug",
                     "run tests", "build an application"],
    "tools": ["crown_code"],
    "permission": "MODERATE",
    "instructions": "Runs in the background and reports progress. Requirements "
                    "come first: if the build answers NEED REQUIREMENTS, ask "
                    "the user instead of inventing an answer.",
    "triggers": ["build me", "fix this bug", "refactor", "add a feature",
                 "debug this", "run the tests", "write a script"],
    "inputs": {
        "action": {"type": "string",
                   "description": "build | clarify | status | cancel | list"},
        "description": {"type": "string"},
        "requirements": {"type": "string"},
        "workspace": {"type": "string"},
        "project_name": {"type": "string"},
        "confirmed": {"type": "boolean"},
    },
    "outputs": ["a job id plus the verified result of the build"],
    "timeout": 60.0,          # builds are asynchronous; this bounds the call
    "tags": ["code", "software", "build"],
}


def run(parameters: dict, ctx) -> dict:
    return run_tool("crown_code", parameters, ctx)


def verify() -> tuple[bool, str]:
    return tool_ready("crown_code")
