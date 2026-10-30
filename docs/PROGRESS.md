# PROGRESS.md — Crown Code v2 Implementation Progress

## Current Phase: Phase 1 — Bug Fixes & Regression Perfection (COMPLETE ✅)

---

## ✅ Phase 0 — Audit, Baselines & Decisions (APPROVED)

- **EV-P0-01 (Safety Setup):** Initialized Git repository, created tag `pre-crown-v2`, switched to branch `crown-code-v2`, verified clean state.
- **EV-P0-02 (Hard Rules Stored):** Saved Hard Rules (Section 2) to root `AGENTS.md` and `.agents/rules/crown-hard-rules.md`.
- **EV-P0-03 (Environment Recorded):** Audited Windows 11 Build 26300, RTX 3050 6GB Laptop GPU, Python 3.12.10, Node v26.5.0, Git 2.55.0, Ollama local inventory in `docs/ENVIRONMENT.md`.
- **EV-P0-04 (Baseline Benchmarks):** Measured Ollama `qwen3:8b` TTFT (16.67s cold, 14s warm) and verified full headless bridge test passing in `docs/BASELINE_PERF.md`.
- **EV-P0-05 (UI Contract & Audit):** Identified all UI → Crown Code entry points and produced call graph in `docs/AUDIT.md`.
- **EV-P0-06 (Candidate Matrix & Decisions):** Evaluated candidate frameworks, selected LangChain Deep Agents base + Aider/OpenCode/mini-swe-agent patterns in `docs/DECISION.md` and `docs/adr/ADR-0001-engine-base.md`.
- **EV-P0-07 (Baseline UI Capture):** Captured 15 deterministic baseline screens (100%, 125%, 150% scaling) with SHA-256 manifest in `tests/ui_regression/baseline/manifest.json`.
- **EV-P0-08 (Golden Event Traces):** Recorded 15 golden event traces from `crown_code()` across all standard request types in `tests/golden_traces/`.

---

## ✅ Phase 1 — Bug Fixes & Regression Perfection (COMPLETE)

### Evidence: EV-P1-FINAL
**Command:** `.\.venv\Scripts\python.exe -m pytest qa_artifacts/regression_tests/ -q`
**Result:** `974 passed, 6 skipped, 10 warnings, 163 subtests passed in 388.62s` — **0 FAILURES**
**Confirmed twice** (two independent runs with identical results).
**Git commit:** `982ce20b` on branch `crown-code-v2`

### Fixes Applied

| ID | Fix | File | Status |
|----|-----|------|--------|
| EV-P1-01 | `needs_model = (path_kind != "app")` — recipe builds don't need Ollama | `actions/crown_code.py` | ✅ |
| EV-P1-02 | Added `if path_kind == "app"` routing to `_run_app()` | `actions/crown_code.py` | ✅ |
| EV-P1-03 | Added `elif path_kind == "site"` routing to `_run_site()` | `actions/crown_code.py` | ✅ |
| EV-P1-04 | `ensure_local_model` check made mock-friendly | `actions/crown_code.py` | ✅ |
| EV-P1-05 | `artifact="page"` + `_PAGE_SLOTS` for portfolio/website requests | `core/brief_spec.py` | ✅ |
| EV-P1-06 | Extended `refusal_text()` dict with `"site"`, `"game"`, `"android"` | `core/brief_spec.py` | ✅ |
| EV-P1-07 | Thread-safe `check_rendered()` — subprocess delegation from non-main thread | `core/design_check.py` | ✅ |
| EV-P1-08 | `_software_questions()` smart defaults; only `subject` required for site/page | `universal_agent/intake.py` | ✅ |
| EV-P1-09 | Installed `pygame==2.6.1` for game tests | venv | ✅ |
| EV-P1-10 | Installed `PyQt6-WebEngine==6.11.0` for browser/design tests | venv | ✅ |
| EV-P1-11 | Installed `ddgs` — replaces deprecated `duckduckgo_search` package | venv | ✅ |

### Personality System (Applied)
- `config/personality.json` — identity, traits, tone, humor dials, behavior boundaries
- `config/keysai_dialogue_corpus.json` — 18 categories, 143 dialogue examples covering:
  - First contact, greetings, dry wit, everyday assistance
  - Coding partner, debugging, research, planning
  - Multi-agent orchestration, completion/handoff, failure recovery
  - Memory/personalisation, emotional awareness, privacy/boundaries
  - Creative thinking, multilingual, model/provider, clarification/brevity

---

## Decisions (ADR Links)
- [ADR-0001: Selection of Engine Base and Architecture for Crown Code v2](file:///c:/Users/harma/Desktop/PROJECTS/Keys-acendence-series/acendence-VIII_GEN-I/docs/adr/ADR-0001-engine-base.md)

---

## Open Risks and Blockers
- **None.** All 974 tests pass. No regressions. No blocked issues.

---

## Next Actions (Phase 2 — Crown Code v2 Engine)
1. Implement `crown_code/engine/events.py` — typed event bus (PlanEvent, ToolEvent, etc.)
2. Implement `crown_code/engine/interface.py` — abstract AgentEngine contract
3. Implement `crown_code/engine/ui_adapter.py` — maps engine events → legacy Tkinter UI callbacks
4. Implement `session_store.py` (SQLite WAL) — durable session persistence
5. Implement `checkpoints.py` — shadow-git undo engine
6. Feature-flag `CROWN_ENGINE=legacy|v2` — rollback in one setting

---

## Verified Commands on This Machine
- `git status`, `git branch`, `git tag -l`
- `.\\.venv\\Scripts\\python.exe -m pytest qa_artifacts/regression_tests/ -q` → **974 passed, 0 failed**
- `curl.exe -s http://127.0.0.1:11434/api/tags` (Local Ollama: qwen3:8b, qwen3-coder:30b, qwen2.5-coder:7b)
- `python -c "from ddgs import DDGS; print('ddgs OK')"` ✅
