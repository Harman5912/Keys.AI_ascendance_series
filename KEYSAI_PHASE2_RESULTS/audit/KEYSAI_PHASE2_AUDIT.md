# Keys.ai — Phase 2 Audit

Date: 2026-10-22 · Auditor: independent QA pass over the real repository.

Everything below was observed in this environment. Where a claim could not be
checked, it says so.

---

## 1. Existing architecture (verified from source and config)

| Layer | Reality |
|---|---|
| Language / runtime | Python 3.12.10 (system interpreter). The checked-in `.venv` is **broken** (`No pyvenv.cfg`), so the system interpreter is what actually runs |
| Frontend / shell | PyQt6 desktop app: `main.py` + `ui.py` (~274 KB) + `mini_overlay.py`. A separate FastAPI web dashboard lives in `dashboard/` |
| Backend | In-process Python. 39 tool modules in `actions/`, 29 core modules in `core/` |
| Model access | `core/llm_client.py` → `brain/providers/` (Gemini, Anthropic, OpenAI-compatible). **Configured provider: `ollama`, model `qwen3:8b`, `http://localhost:11434`** |
| Agent orchestration | `brain/` — intent → router → planner → executor → evaluator, with `safety.py` permission gating. Plus `core/crown_bridge.py` driving a Node "Crown Code" headless agent |
| Tool registry | `core/tool_registry.py` (25 core tools) + plugin fallback; declarations in `core/tool_declarations.py` |
| Command execution | Crown Code subprocess bridge (NDJSON over stdin/stdout) and `automation/` for desktop control |
| File generation | `actions/_office_builder.py` (docx/pptx/xlsx), `actions/_file_readers.py`, `core/site_builder.py` + `core/site_studio/` (websites), `core/app_builder.py` (dashboards, PyQt apps — added Phase 1) |
| Persistence | JSON config files (`config/*.json`), SQLite in generated apps, MySQL recipes, `memory/` store |
| Secrets | `config/api_keys.json` (gitignore-worthy; **must not be read into logs**) |
| Tests | `qa_artifacts/regression_tests/` — 12 pytest-able modules, 193 tests + 17 subtests |
| Version control | **ABSENT.** `git status` → *fatal: not a git repository*. No checkpoint, no branch, no diff |

## 2. Feature inventory (state as found)

| Area | State | Evidence |
|---|---|---|
| Conversational chat | **Implemented, works** | `KeysBrain.process()` answered a real prompt in 13.9 s via qwen3:8b |
| Intent + routing | Implemented | `INTENT_DETECTED QUESTION tags=['QUESTION','CONVERSATION'] conf=0.84` → `ROUTED chat` |
| Requirement gating | Implemented (deterministic) | `core/brief_spec.analyse_brief` returns slots/questions |
| Website generation | Implemented, verified | 4/4 pages passed `check_html` + Chromium audit (Phase 1 batch) |
| Dashboard generation | Implemented, verified | 4/4 recipe builds, 8 checks each (Phase 1) |
| PyQt desktop app generation | Implemented, verified | 2/2 recipe builds, offscreen `--selftest` |
| DOCX / PPTX / XLSX | Implemented, verified | 20/20 artifacts pass `qa_artifacts/validate_docs.py` (Phase 1 record) |
| General full-stack app generation | **Agent-dependent, unverified** | No recipe; routed to the 8B agent. Measured this phase (Stage 3) |
| Android / Electron / stores | Agent-dependent | No deterministic acceptance check |
| File upload → analysis | Partially implemented | `actions/_file_readers.py` reads uploaded files; no end-to-end upload UI test in this pass |
| Concurrency | Implemented (job manager, threads) | `core/crown_jobs.py`; not stress-tested this phase |
| Auth / multi-user | **Absent by design** | Single-user local app |

## 3. Available execution tools

Python 3.12.10 · pytest 9.1.1 · PyQt6 (offscreen via `QT_QPA_PLATFORM`) ·
Flask · Playwright + Chromium (verified rendering a page) · Node 26.5.0 ·
Ollama 0.32.1 with qwen3:8b, qwen2.5-coder:3b/7b, qwen3.5:4b, deepseek-r1:8b ·
python-docx / python-pptx / openpyxl · SQLite 3 (stdlib) · `curl`.

**Not available:** git repository (no VCS), a clean venv, a MySQL server
configured for the app (a MySQL *client* module is present, but no verified
server), Android SDK, deployment credentials, any external office renderer.

## 4. Baseline test results

| Command | Exit | Result |
|---|---|---|
| `python -m pytest qa_artifacts/regression_tests -q` (first run this phase) | **1** | **1 failed, 192 passed, 17 subtests** |
| after repair of D-001 | 0 | 193 passed, 17 subtests |
| `test_file_ops.py` after repair | 0 | 34 passed in 0.94 s |

The single baseline failure was **real, not environmental noise** — see D-001.

## 5. Phase 1 claims vs. what the code and evidence support

| Phase 1 claim | Verdict |
|---|---|
| "193 passed" | **Was true at the time.** Re-running this phase found 1 hidden failure once a local model became reachable — the suite was environment-dependent (D-001) |
| "dashboards + desktop apps verified" | **Confirmed** — `qa_artifacts/reports/recipe_apps.json` records 4/4 with real check output |
| "documents 20/20" | **Not re-run this phase** (prior evidence only) |
| "Android/Electron/stores still agent-dependent" | **Confirmed and still true** |
| Prior phase produced `KEYSAI_ENGINEERING_STATUS.md` | **False — that file does not exist.** Phase 1 wrote `CROWN_CODE_INTEGRATION.md` instead |

## 6. High-priority defects found in this audit

| ID | Sev | Defect |
|---|---|---|
| **D-001** | P2 | `file_processor.create` consulted the model *before* checking whether the instruction was already markdown, so a model-invented plan silently replaced the user's headings/formatting. Test result also depended on whether Ollama was reachable. **FIXED** |
| **D-002** | P2 | Conversational answer quality: qwen3:8b answered "can you help me create a small project?" by asking what a *"shall project"* is — a misread, no capability summary. Recorded in Stage 2 |
| **D-003** | P1 | No version control in the project root: no diff, no revert, no checkpoint for any of this work |

## 7. Test plan for this phase (priority order)

1. **Security & data integrity** — path traversal, SQL parameterisation, secret leakage, workspace isolation.
2. **Conversational agent** (C01–C12) — real model where the turn is chat-routed; deterministic assertions on the *decision* layer where a turn would execute a tool (dangerous actions are not executed during audit).
3. **Integrated inventory application** (Python + SQL + HTML/CSS/JS) — built, run, tested, SQL-injected, restarted.
4. **Office deliverables** — DOCX/PPTX/XLSX generated through the app's own workflow, parsed, cross-checked against the same numbers.
5. **Study planner** — attempted if the window allows; otherwise NOT RUN and reported as such.
6. **Projects A–F** — attempted in priority order; anything not reached is reported NOT RUN.

## 8. Environmental limitations

- **No git** → cannot show a real diff or revert; changes are enumerated by path.
- Local model is 8B and ~14 s per chat turn; long agent builds are slow and were capped at 420 s.
- No MySQL server → any MySQL recipe build cannot be executed here (reported, not faked).
- No PDF renderer/office suite → PDF conversion and visual slide rendering may be BLOCKED.
- GUI window is verified **offscreen only**; no interactive desktop session was driven for this audit.
