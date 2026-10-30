# QA PLAN — Keys.ai / KeysCreations Codebase
# Role: independent tester judging every feature area
# Goal: critical review, find mistakes and improvements, then apply changes
# Method: phased — first code integrity, then functional smoke, then GitHub research

## Phase 0 — Pre-work (already done)
- Feature inventory across 17 areas completed
- Compile health spot-check on 20 key modules (all passed)
- AI model integration confirmed: Ollama running, qwen3:8b installed, CrownBridge importable
- Artifact: `feature_review_report.txt`

## Phase 1 — Code Integrity, Compile, Import Checks (APPROVED, START NOW)
Objectives:
- Verify EVERY Python module in the repo compiles with `py_compile` (not just a sample)
- Verify top-level imports for each major subsystem succeed without side-effect crashes
- Verify no duplicate/placeholder files masquerading as real modules
- Verify config files are valid JSON where expected
- Verify no missing cross-references between declared tools and implemented handlers

Scope:
- All `*.py` files under: core/, brain/, actions/
- Config files: config/*.json
- Ignore: __pycache__, node_modules, generated examples (covered separately), virtual env artifacts

Exit criteria:
- Every module compiles OR a list of failures is produced with exact error text
- Every major subsystem import test passes OR a list of failures is produced
- A findings table is written to `qa_artifacts/reports/phase1_code_integrity.json`

## Phase 2 — Functional Smoke Tests (pending approval)
Objectives:
- Build a desktop app from a brief and run its --selftest
- Build a website from a brief and verify it serves
- Build a .docx, .pptx, .xlsx and confirm the files open / have expected structure
- Test messaging tool dispatch path (send_message tool handler)
- Test computer control / takeover module import and basic function signatures
- Test vision path: screen capture import and describe_image dispatch
- Test CrownCode bridge spawn path in headless mode (short timeout, no long run)

## Phase 3 — GitHub Issue / PR Research (pending approval)
Objectives:
- Search GitHub for the project's own issues and PRs that touch these modules
- Search for known patterns of failure in similar tooling (PyQt6 offscreen, playwright, openpyxl, python-pptx, Ollama bridge)
- Summarize actionable improvements with sources

## Deliverables
- Phase 1 artifact: qa_artifacts/reports/phase1_code_integrity.json
- Final judge report: qa_artifacts/reports/tester_judge_report.md
- Improvement list with filed GitHub issues (where applicable) and/or code changes
