# Test results

Recorded: 2026-10-23. Python 3.12 on Windows (Git Bash). Every number below comes
from running the command shown; nothing is estimated.

## Regression suite — all passing

```
for f in qa_artifacts/regression_tests/test_*.py; do
  python -m unittest "$(basename $f .py)"
done
```

| Module | Tests | Result |
| --- | --- | --- |
| test_app_builder | 18 | pass |
| test_brief_spec | 22 | pass |
| test_crown_bridge | 27 | pass |
| test_crown_jobs | 6 | pass |
| test_file_ops | 35 | pass |
| test_messaging | 13 | pass |
| test_office_builder | 12 | pass |
| test_openai_compat | 11 | pass |
| test_pdf_pipeline | 7 | pass |
| test_provider_fallback | 11 | pass |
| test_security | 9 | pass |
| test_site_builder | 22 | pass |
| test_site_studio | 10 | pass |
| **Total** | **203** | **0 failures** |

Before the changes in `docs/audit/IMPLEMENTATION_LOG.md`, four of these modules
failed: `test_site_builder` (SyntaxError), `test_brief_spec` (3 failures + 3
errors), `test_file_ops` (1 failure), `test_pdf_pipeline` (1 failure).

## Project-level suites

```
python -m unittest test_brain test_install test_targeting test_google_accounts \
                     test_firebase_feature test_window_chrome
```

| Module | Tests | Result |
| --- | --- | --- |
| test_brain | 76 | pass |
| test_install | 7 | pass |
| test_targeting | 13 | pass |
| test_google_accounts | 14 | pass |
| test_firebase_feature | 59 | pass |
| test_window_chrome | 14 | pass |
| **Total** | **183** | **0 failures** |

`test_crown_code.py`, `test_crown_flow.py`, `test_crown_ui.py` and
`test_gemini_ladder.py` are runnable scripts, not `unittest` modules — they
report "Ran 0 tests". They were not executed as scripts here.

## Behaviour checked directly (not through the suite)

* `analyse_brief` on "a tool that converts a folder of PDFs to text" →
  `artifact="app"`, asks `input`, `output`, `scope`.
* `analyse_brief` on the dashboard, portfolio, CLI and nav-fix briefs →
  unchanged from before (`app` / `page` / `task` respectively).
* A `JobManager` target returning `{"ok": True, "writes": 0, "commands": 0}` →
  job status `failed`, message matches "without writing any file".
* A target returning `{"ok": True, "writes": 1}` → job status `done`.
* `crown_code` returns in under 3 s with a job id and "background" in the
  message, while the stubbed builder runs on the job thread.
* `test_brain` no longer touches `config/session_state.json` (file mtime
  unchanged across a full run).

## Known issue found, not fixed

`config/session_state.json` was overwritten once by the old `test_brain` before
the isolation fix above, so it currently holds that run's fixture references
(`last_app: Chrome`, `last_project: ReviewBot`, ...). It is a regenerated
session cache; delete it to start from an empty session.
