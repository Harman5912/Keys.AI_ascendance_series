# ADR-0001: Selection of Engine Base and Architecture for Crown Code v2

- **Status:** Proposed
- **Date:** 2026-10-29
- **Deciders:** Harman Sadhwani, Antigravity Lead Engineer

## Context
Crown Code serves as the autonomous coding agent inside Keys.AI. The original implementation relied on a Node.js headless process (`dist-headless/headless.js`) bridged through subprocess pipes. While functional, it introduced inter-process latency, complex process tree management on Windows, and limited native access to Python AST and language server tools.

## Decision
We will build the Crown Code v2 engine using **LangChain Deep Agents** (Python, MIT) as the core harness, augmented with:
1. **Aider's Tree-Sitter Repo Map & SEARCH/REPLACE Edit Formats** for budget-aware code navigation and local model edits.
2. **mini-swe-agent's Bash-Only Mode** as a fallback for weak local LLMs.
3. **OpenCode's Architectural Patterns**: Plan vs Build separation, shadow-git checkpoints (`.keys/checkpoints/`), and sliding-window context compaction.
4. **Frozen UI Adapter**: An event adapter (`ui_adapter.py`) emitting identical legacy callbacks to preserve the existing UI without modification.
5. **Feature Flag (`CROWN_ENGINE=legacy|v2`)**: To allow instantaneous rollback.

## Consequences
- **Positive:** Single Python runtime environment; direct integration with Keys.AI's memory, tools, and permissions; zero UI regression; full offline resilience with local Ollama models (`qwen3:8b`, `qwen3-coder:30b`).
- **Negative:** Requires porting and adapting Aider's repo map and edit formats into Python modules under clean licenses.
