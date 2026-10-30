# DECISION.md — Crown Code Engine Base & Architectural Decisions

Date: 2026-10-29
Branch: `crown-code-v2`
Decision Status: Recommended for User Approval

---

## 1. Candidate Evaluation Matrix

| Candidate | Language | License (SPDX) | Windows Fit | Local Model Fit | Adapter Effort | Selected Components |
|---|---|---|---|---|---|---|
| **LangChain Deep Agents** | Python | MIT | 5/5 (Native) | 5/5 (Ollama, vLLM) | 5/5 (Direct) | **Base Harness**: Planning, subagents, skills, AGENTS.md middleware |
| **Aider** | Python | Apache-2.0 | 5/5 (Pure Python) | 4/5 | 4/5 | Tree-sitter repo map, SEARCH/REPLACE edit format, architect/editor split |
| **mini-swe-agent** | Python | MIT/Apache | 5/5 | 4/5 | 4/5 | Ultra-lean bash-only fallback mode for non-tool-calling models |
| **OpenCode** | TypeScript | MIT | 4/5 | 4/5 | 3/5 | Plan vs build agents, permission system, shadow-git snapshots, context compaction |
| **OpenHands** | Python | MIT | 3/5 (Docker friction) | 4/5 | 2/5 | Sandboxing reference, CodeAct event loop patterns |
| **Goose** | Rust | Apache-2.0 | 4/5 | 4/5 | 3/5 | MCP protocol reference and extension architecture |
| **Qwen Code** | TypeScript | Apache-2.0 | 4/5 | 5/5 | 3/5 | Prompts and skills tuned for Qwen local weights |
| **Serena** | Python | MIT | 4/5 | 4/5 | 3/5 | LSP symbolic tools (`find_symbol`, `rename_symbol`) |

---

## 2. Core Architectural Decisions

### Decision 1: LangChain Deep Agents as Engine Base
- **Context:** Keys.AI is a pure Python / Tkinter desktop application. Introducing a mandatory secondary container or Node/Rust daemon increases deployment complexity and user install failure rates on Windows.
- **Decision:** Adopt LangChain Deep Agents as the Python base engine for `CrownEngine`.
- **Consequences:** Direct execution in the local Python virtual environment; no child process orchestration required for the core agent loop; frictionless Windows packaging via PyInstaller.

### Decision 2: Feature-Flagged Migration (`CROWN_ENGINE=legacy|v2`)
- **Context:** The existing Crown Code integration is functional. Upgrades must not break working user setups.
- **Decision:** Retain `legacy_engine.py` (wrapping groundcode) alongside `v2_engine.py` behind a toggle controlled by `CROWN_ENGINE`.
- **Consequences:** Instant rollback capability with zero data loss.

### Decision 3: UI Adapter Pattern
- **Context:** Rule R1 mandates that the Keys.AI UI is **frozen**.
- **Decision:** Place `crown_code/engine/ui_adapter.py` between the v2 event stream and legacy callbacks. All events are thread-marshaled using Tkinter's `after()` queue.

### Decision 4: Tiered Safety & Shadow Git Checkpoints
- **Context:** Autonomous coding agents can risk destructive overwrites or deletions.
- **Decision:** Enforce permission tiers T0-T3 with a separate shadow git store in `.keys/checkpoints/` before every destructive action and before every turn.
