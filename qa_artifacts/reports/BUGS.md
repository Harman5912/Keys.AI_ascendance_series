# Defect register — Keys.ai / Crown Code QA

Every entry was reproduced before being fixed, and each fix has a regression test
under `qa_artifacts/regression_tests/`. Severity is impact-on-user, not effort.

| ID | Severity | Area | Status |
| --- | --- | --- | --- |
| B01 | P1 | file_processor (docx/xlsx/pptx create) | **Fixed** |
| B02 | P2 | file_processor (open confirmation) | **Fixed** |
| B03 | P2 | file_processor (docx renderer) | **Fixed** |
| B04 | P1 | brain/providers (local inference) | **Fixed** |
| B05 | P1 | brain/providers (empty completion) | **Fixed** |
| B06 | P1 | file_processor (pptx content) | **Fixed** |
| B07 | P3 | file_processor (pptx placeholders) | **Fixed** |
| B08 | P1 | dashboard/server.py | **Fixed** |
| B09 | P1 | build output / secrets | **Fixed** |
| B10 | P2 | core/crown_bridge.py | **Fixed** |
| B11 | P2 | core/crown_bridge.py | **Fixed** |
| B12 | P2 | Crown Code model choice on 16 GB machines | Reported — needs decision |
| B13 | P3 | file_processor pptx `to_pdf` | Reported |
| B14 | P3 | PDF creation | Reported — feature gap |
| B15 | P3 | QA harness `gen_sites` (test tooling) | **Fixed** |
| B16 | P1 | core/crown_bridge.py (`verify_model` probe) | **Fixed** |
| B17 | P1 | core/site_builder.py (context window) | **Fixed** |
| B18 | P2 | actions/crown_code.py (blocking builds) | **Fixed** |
| B19 | P2 | core/crown_jobs.py (misleading ETA) | **Fixed** |
| B20 | P1 | Crown Code could not build a page unaided | **Fixed** |

---

## B01 — Explicit output path silently ignored when creating documents (P1)

**Symptom.** `file_processor({"action":"create","file_path":"…/qa/doc.docx", …})`
returned `Created Word document … Saved to: C:\…\qa\doc.docx` but nothing was
written there. The file went to `~/Desktop/keys_Creations/documents/…` instead.

**Reproduction.** `qa_artifacts/logs/gen_docx_D01.log` (pre-fix) plus
`ls qa_artifacts/generated_documents` → empty while the tool reported success.

**Cause.** `_create_document` unconditionally rewrote the path:
`if str(DOCS_DIR) not in str(path): path = _doc_save_dir(doc_type) / path.name`.

**Impact.** Any caller that supplies a path (API, automation, tests, another
agent) gets a success message and a file somewhere else.

**Fix.** Honour an explicitly supplied path; only fall back to the
`keys_Creations` default when the caller gave no path/directory.

**Test.** `test_file_ops.py::TestDocxCreation::test_explicit_output_path_is_honoured`.

---

## B02 — "Opened in Word/Excel/PowerPoint" claimed after a denied permission (P2)

**Symptom.** With a player that denies the open, the tool still returned
`Opened in Word.` and emitted `✓ Opened … in Word`.

**Cause.** `_open_file_default()` swallows every exception and the success path
was assumed regardless of `_ask_open_permission`.

**Fix.** Report `Not opened (no permission).` unless the open actually ran; the
creation event is only emitted on success.

**Test.** `test_file_ops.py::TestDocxCreation::test_no_open_claim_when_permission_denied`.

---

## B03 — Markdown `**bold**` written literally into DOCX (P2)

**Symptom.** 20 literal `**` markers inside `D01_business_proposal.docx`; `**Heading**`
lines were plain paragraphs, so the document had no outline.

**Cause.** The renderer copied model output line by line.

**Fix.** `_docx_add_markdown` / `_docx_rich_paragraph` convert `#`/`##`/`**…**`
into real heading styles and bold runs, and handle numbered/bulleted lists.

**Test.** `test_file_ops.py::TestDocxCreation::test_markdown_bold_becomes_bold_runs_not_asterisks`.

---

## B04 — Local Qwen3 spends minutes in hidden reasoning; no way to switch it off (P1)

**Symptom.** A 10-slide deck request through `actions/file_processor.py` ran for
>8 minutes at ~11 tok/s without producing a file; the same request through
Ollama's native endpoint with `think:false` finished in 41–57 s. A 7-slide
deck that eventually completed took 6–8 minutes.

**Cause.** `OpenAICompatProvider` used `/v1/chat/completions`, which has no
reasoning switch, so Qwen3 emitted a multi-thousand-token private scratchpad on
every call.

**Fix.** For local endpoints the provider now calls Ollama's `/api/chat` with
`"think": false` and falls back to the OpenAI endpoint (marking the runtime as
non-Ollama) when `/api/chat` returns 404/405. The `/no_think` soft switch is
still appended on the OpenAI fallback path for Qwen3 only.

**Measured.** P01 deck: >480 s (killed) → 47.9 s, with the same model and prompt.
Full 9-deck batch: ~40 s each.

**Test.** `test_openai_compat.py::TestNativeOllamaPath` (5 tests) and
`::TestQwenSoftSwitch` (4 tests).

---

## B05 — Empty completion returned as `""` (P1)

**Symptom.** A short prompt returned an empty string; the document path then
wrote an empty document and reported success.

**Cause.** `_post` returned `content.strip()` with no empty check; nothing above
it validates the result.

**Fix.** Empty local completions are retried once, then raise `ProviderError`
with the model and endpoint. Hosted providers raise immediately (no retry).

**Test.** `test_openai_compat.py::TestEmptyCompletion`.

---

## B06 — PPTX generation silently fell back to a canned template (P1)

**Symptom.** Every deck built from a real prompt came out as the same generic
"Prepared by Keys.ai / TAM: $50B by 2027" deck, unrelated to the request, and
still reported success. A seed-pitch request produced "Our Mission / Our Team /
Products & Services".

**Cause (three stacked).**
1. `re.search(r'\[\s*\{.*?\}\s*\]')` cannot match an array of objects, so the
   parse always failed and `except Exception:` swapped in `_default_pptx_slides`.
2. `json.loads` rejects the literal newlines local models put inside JSON
   strings.
3. Models emit small damage (`""title":`, smart quotes, trailing commas) that
   plain JSON rejects.

**Fixes.**
* `_extract_json()` — fence stripping + `json.loads(strict=False)` +
  `raw_decode` from each bracket + a repair pass (smart quotes, doubled key
  quotes, trailing commas).
* `_salvage_slides()` — last-resort title/content pairing so a structurally
  broken array still yields the model's content.
* The fallback now emits a visible `! AI slide generation failed (…); using
  generic template` event instead of pretending the deck is AI-generated.

**Evidence.** `qa_artifacts/fixtures/pptx_model_output.txt` and
`pptx_model_output_2.txt` are real qwen3:8b captures that previously failed;
both now yield 10 slides. Deck size went 32 823 B (template) → 36 974 B (model
content), and the validator's `not_fallback_template` check passes.

**Test.** `test_file_ops.py::TestJsonExtraction` (8 tests) including the captured
fixtures.

---

## B07 — Title slides shipped with `[Your Name]` / `[Your Organization]` (P3)

**Symptom.** P07 and P08 decks opened with `Presenter: [Your Name]`,
`Affiliation: [Your Institution]`, `Presented by [Your Organization]`.

**Fix.** The prompt forbids placeholders, and `_strip_placeholder_lines()` drops
whole `Label: [placeholder]` lines without touching real prose (verified: a
citation like `[1]` survives).

**Test.** `test_file_ops.py::TestJsonExtraction::test_placeholder_lines_are_stripped`.

---

## B08 — Dashboard listened on all interfaces with unauthenticated command execution (P1)

**Symptom.** `dashboard/server.py` defaulted to `host="0.0.0.0"`, and its
endpoints execute assistant commands. Anyone on the same LAN could drive the app.

**Fix.** Default host is `127.0.0.1`; `KEYSAI_DASHBOARD_HOST` still allows an
explicit opt-in for trusted networks.

**Test.** `test_security.py` (`test_dashboard_defaults_to_loopback`,
`test_dashboard_host_env_opt_in`).

---

## B09 — Live Gemini API key shipped inside build output (P1)

**Symptom.** The 53-character key from `config/api_keys.json` was byte-identical
in `dist/config/api_keys.json` and `dist/KeysAI/config/api_keys.json`.

**Fix.** Both packaged copies were scrubbed (value emptied, `_scrubbed_by_qa`
marker added). The source config keeps the user's key; a packaged app should
require configuration rather than carry the developer's credentials.

**Note.** `test_agent_control.py` contains one `AIza…` literal, but it is a
42-character fake used by a log-scrubbing test — it does **not** match the live
key. The scan reports it as a pattern match, not a leak.

**Follow-up (recommended).** Add `dist/**/api_keys.json` to release packaging
exclusions so a rebuild cannot re-introduce the key.

---

## B10 — Bridge treated an empty model reply as a verified model (P2)

**Symptom.** `verify_model()` returned `(True, "")` when Ollama answered with an
empty message, so the UI claimed a working model while inference was broken.

**Fix.** An empty reply is a failure: `(False, "model returned an empty response")`.

**Test.** `test_crown_bridge.py::TestModelVerification::test_empty_reply_is_not_a_verified_model`.

---

## B11 — Silent switch to a cloud provider when the local runtime is down (P2)

**Symptom.** With Ollama unreachable, the bridge could start a run against a
remote provider without telling the user, changing where their code and prompts
were sent.

**Fix.** No implicit remote fallback; the run fails with an actionable message.

**Test.** `test_crown_bridge.py::TestConfig::test_no_silent_remote_fallback_when_ollama_unreachable`.

---

## B12 — The app's "verified tool-calling" default model fails in the agent loop (P2, open)

**Symptom.** `recommend_model()` prefers `qwen3:8b` (pinned by
`test_auto_pick_prefers_verified_tool_calling_model`). In live runs against
Crown Code, `qwen3:8b` produced **no tool call at all** for a website build
(263 s, `tools=[]`, no file), while `qwen2.5-coder:7b` completed the same task
in 77.5 s with `tools=['write_file']`.

**Reproduction.** `qa_artifacts/logs/batch_websites.log` (first run) vs the
re-run after switching the model.

**Not fixed in code** because the right answer is a product decision (change the
auto-pick list, or detect "no tool call" and retry with a coder model). Recorded
in `BLOCKERS.md`.

---

## B13 — `to_pdf` for PPTX is documented but not implemented (P3)

The module docstring advertises `pptx → to_pdf`; `_process_pptx` returns
`Unknown PPTX action: 'to_pdf'.` Pinned by
`test_pdf_pipeline.py::TestPdfReadPipeline::test_pptx_to_pdf_is_advertised_but_missing`
so the test fails loudly when the feature lands.

---

## B14 — No PDF creation path (P3, feature gap)

`action=create` with `.pdf` returns
`Cannot create '.pdf' files. Supported: .docx (Word), .xlsx (Excel), .pptx (PowerPoint).`
No writer dependency exists in the project. See `pdf_capability.md`.

---

## B15 — QA harness wrote artifact folders with spaces and capitals (P3, test tooling)

`gen_sites._slug()` produced `01_saas_landing_SaaS product landing page/`.
Now `01_saas_landing/`; paths are stable for audits and reports.

## B16 — A working reasoning model was reported as broken, blocking every run (P1)

**Symptom.** `crown_code(...)` returned
`Crown Code cannot start: Model 'qwen3:8b' failed a test inference: model returned an empty response`
on a machine where `ollama run qwen3:8b` answers fine. Nothing could be built.

**Reproduction.**
```
curl -s http://localhost:11434/api/chat -d '{"model":"qwen3:8b","messages":[{"role":"user",
  "content":"Reply with exactly: OK"}],"stream":false,"options":{"num_predict":8}}'
→ {"message":{"content":"","thinking":"Okay, the user wants me…"},"done_reason":"length"}
```

**Cause.** `verify_model()` probed with `num_predict: 8` and thinking enabled.
Qwen3-class models answer inside their hidden reasoning block, so the visible
content is empty; the probe then declared a healthy model unusable and
`ensure_local_model()` refused to start Crown Code.

**Fix.** The probe now switches thinking off (`"think": false` on the native
endpoint, `/no_think` on the OpenAI-compatible one), allows 24 tokens, and
distinguishes "empty because the answer was hidden in reasoning" from "empty
because inference is broken" in the message it returns.

**Regression test.** `qa_artifacts/regression_tests/test_crown_bridge.py`
(`TestVerifyModel`) — asserts the probe payload disables thinking for qwen3,
that hidden-reasoning-only output is reported as such, and that a real answer
still verifies.

---

## B17 — Page writes silently lost their brief to a 4096-token context (P1)

**Symptom.** A 25,757-byte `index.html` containing 1,066 lines of CSS and no
`<body>`: the model never reached the markup and hit the token cap inside
`<style>`.

**Reproduction.** `qa_artifacts/logs/live_site_build.log` (run 1), then
`grep -c "<body" qa_artifacts/live_build/portfolio_lena/index.html` → 0 while
`ollama ps` showed `CONTEXT 4096`.

**Cause.** Ollama's default context is 4096 tokens. The plan JSON plus the
writing rules plus the model's own long answer do not fit, so the instruction
block was truncated away and the model improvised CSS.

**Fix.** The site provider requests `num_ctx: 8192`; the write rules cap the
file (≤700 lines, ≤230 lines of CSS, body before line 320); the write is
streamed so a truncated file is visible while it happens; and
`_finish_truncated()` asks the model to continue from its own last characters
instead of paying for a whole second attempt.

---

## B18 — A build made the assistant deaf (P2)

**Symptom.** Asking "how's it going?" during a build produced no answer until
the build finished; a second request queued behind the first.

**Cause.** `crown_code()` ran the agent synchronously inside the brain's task
lock, so every later message — including a progress question — waited for it.

**Fix.** Builds run as jobs (`core/crown_jobs.py`) on their own thread and the
call returns immediately with a job id; `brain.process()` answers progress
questions from the job record *before* taking the task lock; `action="status"`
reports phase, percent, ETA, files and recent log lines; `action="cancel"` and
the workspace Stop button set the cancel flag.

**Regression test.** `qa_artifacts/regression_tests/test_crown_jobs.py`.

---

## B19 — Confidently wrong ETA (P2)

**Symptom.** `~43m left` shown 10 minutes into a build that was already past its
longest phase, because the estimate came from phase weights only.

**Fix.** No ETA is shown before 45 s or below 12% progress, and streamed writes
report real file progress ("Writing index.html — 42% of the file") so the
number that is shown is derived from actual output.

---

## B20 — Crown Code could not build a single portfolio page unaided (P1)

**Symptom.** Repeated runs ended with
`FAIL … problems=['the model called no tool (it only produced text)', 'index.html was not created']`,
or produced a file that failed the page checks.

**Cause.** The page path depended on a local 8B model issuing native tool calls
and finishing a 700-line file in one shot — two things it does not do reliably,
with no fallback.

**Fix.** `core/site_builder.py` (plan → write → verify → repair with a
plan-rendered floor) plus `core/site_checks.py` (structural rules, mechanical
repair, Chromium audit). A page request now always ends in a page: either the
model's verified file or an honest `used_fallback: true` render of the approved
plan.

**Regression tests.** `qa_artifacts/regression_tests/test_site_builder.py`;
end-to-end `qa_artifacts/live_site_build.py` (real model, real Chromium) →
`PASS`.

---

## B21 — A page build blocked on a 12-minute model write (P1)

**Symptom.** `build_site()` asked the 8B model to write the whole page before
the user got anything: 12–19 minutes per portfolio, and the file frequently
failed verification (truncated inside `<style>`), so the run ended in the
plan-render fallback after all that waiting.

**Cause.** The pipeline was ordered write-first. On an ~8 tok/s local model the
write dominates the build, and nothing the user could see happened until it
finished.

**Fix.** Render-first: the built-in plan is rendered and verified in seconds,
the planner's copy is fetched with the fastest installed model (measured:
19 s for `qwen2.5-coder:3b` vs 88 s for `qwen3:8b`) and swapped in only when it
passes the same checks. Truncated planner JSON is continued rather than
discarded. `speed="custom"` keeps the old bespoke-design path as an optional,
verified second stage.

**Measured.** First working page 15.5 s; full build 105 s, PASS
(`qa_artifacts/reports/live_site_build.json`).
