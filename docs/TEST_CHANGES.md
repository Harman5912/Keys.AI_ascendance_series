# TEST_CHANGES.md — Approved Changes to Tests

Every entry records a test that was changed, why, and who approved it
(AGENTS.md rule R12: a failing test is never loosened or rewritten silently).

---

## 2026-10-30 — Research Browser default search engine

**Test:** `qa_artifacts/regression_tests/test_browser_workspace.py::TestBrowserAndTabs::test_a13_text_input_becomes_a_search_not_a_url`
**Change:** assertion `assertIn("duckduckgo.com", target)` → `assertIn("google.com", target)`
**Reason:** the requirement for this change is that the Research Browser
defaults to Google, not DuckDuckGo. The code default (`urls.normalise_input`,
`paths.DEFAULTS["search_engine"]`) is already `google`, and the workspace
toolbar previously preselected DuckDuckGo. The old assertion encoded the
previous default and was failing against the required behaviour.
**Approved by:** user, 2026-10-30 (asked and confirmed before the edit).
