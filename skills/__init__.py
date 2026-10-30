"""SKILLS package — the capability layer of Keys.AI.

    manifest.py      what a skill must declare, and its validation
    registry.py      discovery, enable/disable, execution, prompt block
    runner.py        input checks, permission gate, timeout, retries, tracing
    orchestrator.py  which skills a request needs (deterministic, auditable)
    commands.py      /help and /skills … typed by the user
    tools.py         the `skills` tool the model calls
    inventory.py     machine-readable inventory + human-readable catalog
    catalog.py       the target capability list, so gaps stay visible

A skill is not a second implementation of a tool. It is a contract — what it
takes, what it returns, what permission it needs — over a capability that already
works, which is why adding one never requires redesigning the application.
"""

from __future__ import annotations

from skills.registry import (SkillEntry, SkillRegistry, get_registry,
                             reset_registry, skills_block)
from skills.runner import SkillContext, SkillResult, execute

__all__ = [
    "SkillEntry", "SkillRegistry", "SkillContext", "SkillResult",
    "get_registry", "reset_registry", "execute", "skills_block", "run_skill",
]


def run_skill(name: str, parameters: dict | None = None, *, ui=None,
              speak=None, approved: bool = False) -> SkillResult:
    """Run one skill by name. The short path for callers outside the agent."""
    ctx = SkillContext(ui=ui, speak=speak, approved=approved)
    return get_registry().execute(name, dict(parameters or {}), ctx)
