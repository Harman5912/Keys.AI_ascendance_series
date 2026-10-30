# Universal Project Agent

Long-running work in Keys.AI — research, software builds, documents, spreadsheets,
image operations and read-only web inspection — behind one resumable task.

Open it from the left panel button **◈ PROJECT AGENT** (also listed in the
shortcuts/settings list as "Project Agent (research · build · documents)").
Everything below happens in that overlay; no other screen changed.

---

## 1. What it does

Type a request in plain language and press **START PROJECT**. The agent:

1. **Understands** the request and classifies it (research, software, documents,
   data, images, browser).
2. **Asks** only the questions it cannot proceed without (see §3).
3. **Plans** numbered steps, each owned by one worker, with acceptance criteria.
4. **Runs** the steps, logging real work as it goes.
5. **Verifies** every produced file by reopening it with a parser.
6. **Repairs** a failed verification once (bounded), then reports the failure.
7. **Delivers** files in the task workspace plus an honest report.

A worker saying "done" is not a completion: the task only becomes `COMPLETED`
after the artifact validators passed. If they did not, the task says `FAILED`
and names what could not be verified.

---

## 2. Starting a project

| You want | Example request |
|---|---|
| A cited report | `Research the current local LLM runtimes and write a cited report` |
| A repository review | `Research https://github.com/owner/repo — license, activity, how it works` |
| A website | `Build a portfolio website for a wildlife photographer called Ada` |
| A spreadsheet analysis | `Analyse C:\data\sales.xlsx and chart the monthly totals` |
| A deck or document | `Create a PowerPoint presentation about tidal energy` |
| An image edit | `Resize C:\pics\hero.png to 1600x900` |
| A page inspection | `Open https://example.com/pricing and read it` |

The **RECENT TASKS** list keeps every task; click one to re-open its plan,
activity log, artifacts and brief.

---

## 3. Answering its questions

If a required fact is missing (who the portfolio is for, which dataset, which
output format), the task pauses in **WAITING FOR USER** and the **QUESTIONS** tab
shows a form. Required questions are marked `REQUIRED`; each shows why it is
needed. Optional choices carry a recommended default.

* Answers already given are never asked again.
* Choices that are genuinely optional are recorded under **BRIEF → ASSUMPTIONS**
  instead of blocking the task.
* Submitting answers resumes the same task; nothing already done is repeated.
* The form and the task survive an application restart — reopen the task from
  RECENT TASKS and press **RESUME**.

---

## 4. Approving sensitive actions

A step that deletes, overwrites or acts outside the task (publishing, sending,
purchasing) stops in **WAITING FOR APPROVAL**. The QUESTIONS tab shows what is
being asked and why, with **APPROVE** / **REJECT**.

* Approval is per action, not per project.
* **REJECT** fails that step and the task, and is written to the audit log.
* If nobody answers within 5 minutes the step is declined, not assumed.
* The agent never signs in, submits a form, publishes, sends a message or buys
  anything on its own.

---

## 5. Where the files go

Every task gets its own workspace (same convention as Crown Code):

```
<app>/config/universal_agent/        task records per task + audit.jsonl
~/Desktop/keys_Creations/universal/<YYYYMMDD>-<slug>-<task id>/
    deliverable files …
```

The footer shows the workspace path; **📂 WORKSPACE** opens it. Each artifact in
the **ARTIFACTS** tab can be **OPEN**ed in its application, **REVEAL**ed in the
file manager, or its path **COPY**ed. The registry records size, SHA-256,
creation time and the validation detail for every file.

Research reports list every inspected source with its URL and retrieval time.
The **BRIEF** tab shows the goal, deliverables, acceptance criteria,
assumptions, warnings, planner note and any error.

---

## 6. Resuming and cancelling

* **RESUME** re-runs a task that was interrupted, failed or is waiting, skipping
  steps already completed and re-running the interrupted one.
* **CANCEL** stops new work immediately (confirmation required). Files already
  delivered are kept; nothing new is started.
* Closing the application cancels running tasks safely.

Progress is shown as states and completed steps, not a fabricated percentage.
The bar reflects steps verified out of planned steps.

---

## 7. What needs separate configuration

| Capability | Requirement |
|---|---|
| All model-driven steps | A provider configured in **AI Settings** (Gemini, OpenAI-compatible, Anthropic, NVIDIA, OpenRouter) or a local Ollama model |
| Software builds | The existing **Crown Code** coding agent and the local model it uses |
| Image generation | **AI Image Studio** → a running local ComfyUI and one installed model |
| Image inspect/resize/crop/convert | Nothing beyond Pillow (bundled) |
| Web research | The app's configured search backend |
| Browser inspection | Playwright + Chromium (bundled with the app's browser tooling) |
| GitHub inspection | Public repositories work unauthenticated; an optional `github_token` in the app config raises the API rate limit |
| Documents, spreadsheets | Bundled `python-docx`, `python-pptx`, `openpyxl`, `pypdf` |

If a capability is unavailable, the task says so and stops at that step — it does
not substitute a cloud service you did not configure.

---

## 8. What it cannot do (current limits)

* **Browser**: read-only. It navigates, reads the rendered page, screenshots it
  and downloads a linked file. It does **not** sign in, fill or submit forms,
  click consequential controls, follow pagination beyond the first page, or
  handle a human takeover.
* **Image editing with AI**: background removal, inpainting and similar edits
  are not implemented; the worker reports the operation as unsupported instead
  of silently inspecting the image. Deterministic resize/crop/rotate/convert are.
* **Image generation** was verified against an injected backend and a real
  saved file, not against a GPU/ComfyUI run in this environment.
* **Research** reads public pages and GitHub repositories. It does not ingest
  local documents into a research task, does not cluster competing claims, and
  cannot verify a claim beyond quoting the source it came from.
* **Spreadsheets**: no formula evaluation (needs Excel/LibreOffice), no
  forecasting or statistical tests. `data_only` reads cached values only.
* **Presentations/documents**: no PowerPoint→PDF conversion, and no visual
  render check (text overflow is not detected here).
* **Code isolation**: generated code is confined to the task workspace by path
  checks and Crown Code's own command policy — not by a VM or container.
* **Per-worker model routing** is not implemented: workers use the app's
  configured provider.
* **Skills** are encoded as planner step templates and worker procedures, not as
  a separate versioned skill registry.

---

## 9. Where the code lives

| Piece | Module |
|---|---|
| Task record, statuses, persistence, audit | `universal_agent/models.py` |
| Path/secret/permission primitives | `universal_agent/security.py` |
| Requirements interview and brief | `universal_agent/intake.py` |
| Planning (deterministic + model-assisted) | `universal_agent/planner.py` |
| Orchestration, approvals, repair, resume | `universal_agent/service.py` |
| Artifact verification | `universal_agent/validation.py` |
| Research + GitHub API inspection | `universal_agent/workers/research.py`, `universal_agent/tools/github.py` |
| Software builds via Crown Code | `universal_agent/workers/software.py` |
| Documents / data / images / browser | `universal_agent/workers/{documents,data,images,browser}.py` |
| The overlay | `universal_agent/studio_ui.py` |
| Launcher, menu entry, shutdown | `ui.py` (`_open_project_agent`, `_shutdown_image_studio`) |

Tests: `qa_artifacts/regression_tests/test_ua_*.py` and
`test_universal_agent_*.py`. The full report, test matrix and limitations are in
`qa_artifacts/reports/UNIVERSAL_AGENT_TEST_REPORT.md`.
