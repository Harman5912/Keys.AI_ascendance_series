"""
KEYS.AI SMART BRAIN V2 — agentic intelligence layer for Keys.ai.

Public API:
    from brain import KeysBrain, BrainResponse, load_config, get_provider

    brain = KeysBrain(ui=ui, speak=speak)
    resp  = brain.process("open VS Code and fix the error")
    if resp.used_brain:
        speak(resp.text)
    else:
        # fall back to the normal conversational path

Modules:
    brain.py        KeysBrain orchestrator
    intent.py       intent classification
    context.py      context engine + reference/pronoun resolution
    memory.py       long-term memory layer + memory decisions
    providers/      model-agnostic LLM provider abstraction
    router.py       deterministic routing (chat / tool / plan)
    planner.py      dynamic multi-step plan generation
    executor.py     step execution with retry/recovery
    evaluator.py    observation/evaluation of tool results
    safety.py       permission levels + confirmation gating
    state.py        TaskState model
    reasoning.py    conversational answering
    tools.py        universal tool registry over existing tools
    log.py          structured high-level event logging
"""

# The brain prints emoji/Unicode status lines. Mirrors main.py: force UTF-8
# console output so it never crashes on legacy (cp1252) Windows consoles,
# regardless of which entry point imports the brain.
import sys as _sys
for _stream in (_sys.stdout, _sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from brain.brain import BrainResponse, KeysBrain
from brain.config import BrainConfig, load_config
from brain.providers import get_provider

__all__ = [
    "KeysBrain", "BrainResponse", "BrainConfig", "load_config",
    "get_provider",
]
