# Keys.ai — Phase 2 Defect Log

Every entry below was reproduced in this environment. "Fixed" means the cause
was changed and the check that exposed it was re-run; nothing is marked fixed on
the strength of a code edit alone.

---

## D-001 — The model silently overrode the user's explicit markdown · P2 · FIXED

**Reproduced by:** `test_markdown_bold_becomes_bold_runs_not_asterisks` failed
(exit 1) at baseline, having passed minutes earlier.

**Expected:** a `## Section` instruction becomes a Word "Heading 2" paragraph and
`**bold**` becomes a bold run, exactly as the user wrote it.

**Actual:** style set was `{'Normal','List Bullet','List Number','Heading 1',
'Title'}` — a model-generated *plan* had replaced the user's structure.

**Root cause:** `actions/file_processor._create_document` called
`_model_document_plan()` before `looks_like_markdown()`, so whenever a model was
reachable the user's own headings were discarded. It also made the test suite
depend on whether Ollama happened to be running (6.95 s with the model call,
0.94 s without).

**Fix:** explicit markdown is detected first and the model is not consulted for
it. `actions/file_processor.py`.

**Verification:** `test_file_ops.py` → 34 passed, 0.94 s. Full suite 194 passed.

---

## D-002 — Chat answers misread the prompt and gave no capability summary · P2 · OPEN

**Test:** C01 — "Hey Keys, can you help me create a small project?"

**Actual reply:** *"I can help with that, sir. Could you clarify what you mean
by a 'shall project'?"* — 13.9 s.

**Assessment:** natural acknowledgement is present, but the model invented the
word "shall", asked a pointless clarification, and never said what it can build.
Against the C01 acceptance criteria this is **PARTIAL**.

**Likely cause:** 8B local model quality on the free-form chat path plus no
capability preamble in the chat system prompt.

**Not fixed** — this is model/prompt quality, not a code defect, and changing the
chat system prompt was out of the audit's safe scope.

---

## D-003 — No version control in the project root · P1 · OPEN (environmental)

`git status` → *fatal: not a git repository*. No diff, no revert, no checkpoint
for any Phase 1 or Phase 2 change. Changes are enumerated by path instead.

**Recommendation:** `git init` and commit before further work.

---

## D-004 — A technical deck was padded with unrelated business slides · P2 · FIXED

**Reproduced by:** Stage 6, 12-slide technical deck for the inventory system.

**Actual titles:** slides 8–12 were *"Market context"*, *"What success looks
like"*, *"Risks and mitigations"*, *"Decisions needed"*, *"Next 30 days"* — none
requested — and the deck never stated the verified total (54,200.00), so it
contradicted the Word report.

**Root cause:** `actions/_office_builder.build_pptx` padded *any* deck to a
requested slide count using one hardcoded business filler list.

**Fix:** padding is applied only to genuinely business decks
(`_BUSINESS_DECK`), matched narrowly. First attempt at this regex matched
"testing **strategy**" and still padded — corrected and re-verified.

**Verification:** regenerated deck → 7 slides, all on-topic,
`business filler present: False`.

**Residual (D-004b, OPEN):** the deck now honestly has 7 slides instead of the
12 requested, because `_slide_outline()` has no coverage for *user interface,
security, testing, results, limitations, future, conclusion*. The brief named
~14 sections; only 7 exist. **Requested vs. delivered slide count can still
differ** — a real capability gap, now visible instead of hidden behind filler.

---

## D-005 — Spreadsheet is a generic template, not a report of the tested system · P2 · OPEN

**Reproduced by:** Stage 6 XLSX validation.

`inventory_test_report.xlsx` has 4 sheets (`Dashboard`, `Trend`, `Data`,
`Assumptions`), 69 formulas and 2 charts — structurally valid — but the sheets
are the generic template: the five inventory products and the 54,200.00 total are
not present. `has_54200_grid_value: False`.

Also recorded honestly: openpyxl stores formulas **without cached results**, so
"69 formulas" is not evidence that the totals compute. No calculation engine
(LibreOffice/Excel) is available here, so formula *values* are **unverified**.

---

## D-006 — An inventory management system was silently downgraded to a dashboard · P1 · FIXED

**Reproduced by:** Stage 3 agent attempt, brief:
*"Build a small inventory management system: Python + Flask + SQLite … dashboard
statistics and stock movement history."*

**Actual:** in 0.9 s the request produced a generic `events` dashboard
(`/api/kpis`, `/api/series`, `/api/breakdown`, `/api/status`, `/api/rows`) and
reported **"verified · 8 checks passed"**. All checks passed — on the wrong
artifact. No `products` table, no CRUD, no stock movements.

**Root cause:** `core/app_builder.app_kind_for` matched the word "dashboard" in
"dashboard statistics" and routed a data-management request to the read-only
dashboard recipe. The verification engine cannot catch this class of error
because it only checks that the artifact it was given works.

**Fix:** a `_CRUD_INTENT` guard — "management system", "crud", "full-stack",
"create/edit/delete" — keeps such requests off the recipe path.

**Verification:** new regression test
(`test_a_crud_app_is_not_downgraded_to_a_dashboard`) passes; a genuine
reporting request ("Build a fleet dashboard with charts") still routes to the
recipe. Full suite 194 passed.

**Residual:** the agent path is what such a request now uses, and it has no
verified CRUD capability (see Stage 3 result). **Correct routing, missing
capability** — reported, not hidden.

---

## D-007 — A question about what happened was routed as a command to act · P2 · OPEN

**Reproduced by:** C11 — *"Did you actually run my application, or did you only
write the code?"*

**Actual:** `INTENT` → coding intent → `TOOL_SELECTED live_code {action: start}`
→ `WAITING_FOR_USER 'live_code' needs your confirmation`.

The question was treated as an instruction to launch a coding session. It did
**not** execute (the confirmation gate held), which is good safety evidence, but
it also did not answer the question.

**Cause:** keyword "code" dominates intent classification over question form.

**Not fixed** — changing intent precedence is a behavioural change to the agent
core that needs its own regression pass.

---

## D-008 — Test suite was environment-dependent · P3 · FIXED (with D-001)

The baseline result changed depending on whether a local model was reachable.
Fixed as a consequence of D-001: the document path no longer calls a model when
the instruction is explicit markdown.

---

## Test-harness defects found and fixed (not product defects)

| ID | Problem | Fix |
|---|---|---|
| H-01 | Inventory test methods used hyphens (`def test_INV-DB-001_...`) → `SyntaxError` | renamed to underscores; the stable ID stays in the docstring |
| H-02 | Tests opened SQLite with `with sqlite3.connect(...)`, which never closes → `PermissionError` deleting temp DBs on Windows (4 errors) | `contextlib.closing` |
| H-03 | Two movement tests asserted an empty history, ignoring the opening-balance row seeding writes | assert against the seeded baseline instead of assuming zero |
| H-04 | Frontend test waited on `#movements li` count, which the placeholder row already satisfies → race | wait for the recorded reason text |
| H-05 | Frontend test counted a deliberate 400 as an unexpected console error | expected failures are collected separately and asserted on |
