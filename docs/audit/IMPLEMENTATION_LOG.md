# Implementation log

Scope of this entry: the Crown Code action layer, the job registry, brief
classification, and the regression suite that covers them. Everything below was
changed in this repository and verified by running the tests named.

## 1. Job registry was resolved once, at import time

`actions/crown_code.py` did `_get_manager = crown_jobs._manager`, binding the
registry accessor at import. Consequences:

* `status` / `cancel` / `list` read `crown_jobs.<fn>` (the module-level
  singleton) while the build path used the frozen alias, so a host that swaps
  the manager could register a job and then read a different registry.
* Patching `crown_jobs._manager` (the documented test seam) had no effect.

Changed: `_get_manager()` is now a function that calls `crown_jobs._manager()`
at each use, and the three read-only actions go through it too, so one accessor
serves every job lookup.

## 2. The agent build path skipped the "nothing was written" guard

`_run_bridge()` owned the tool accounting (`writes`, `commands`, successful
tools) and the rule that a run which wrote no file is a failure, not a build.
The production target for the general coding path built its own `CrownBridge`
inline and returned the bridge result directly, so the guard — and the
`writes`/`commands` counters in the result — never ran for real builds.

Changed: the target now calls `_run_bridge(...)`. Every agent build goes through
one path that counts tool use and refuses to report an empty run as done.

## 3. `JobManager` accepted an empty result as success

`core/crown_jobs.py` decided `ok` purely from `result["ok"]`. A target could
report success with `writes: 0` and `commands: 0` and the job still finished as
`done`.

Changed: `_produced_anything()` is applied in the runner. When a result declares
its tool usage and both counts are zero, the job finishes as `failed` with the
message "Crown Code stopped without writing any file …". Results that report an
artifact (`path` / `bytes`) instead are not second-guessed.

## 4. File-processing tools were classified as plain tasks

`core/brief_spec.py` recognised applications by data/behaviour markers only, so
"a tool that converts a folder of PDFs to text" came back as `task`: the agent
was started with no questions about input, output or scope.

Changed: a file-processing tool is now an application (`is_file_tool()`), and it
is asked for `input`, `output`, `scope` instead of the chart-oriented slots. An
input is only counted as stated when the brief names where the files come from;
"to text" is a format, not a destination, so it does not answer `output`.

## 5. Tests that asserted instead of measuring

* `qa_artifacts/regression_tests/test_site_builder.py` had a corrupted method
  (two defs spliced together) that could not be imported. Rewritten; it now
  patches `cc._get_manager` and asserts the background-start contract.
* `test_brief_spec.py` patched `cc.crown_jobs` with a lambda or shim object,
  which no longer reached the accessor. It now patches `cc._get_manager`; the
  three tests that assumed dashboards stay on the agent path use briefs that
  genuinely do (MySQL stack, inventory system, plain refactor task).
* `test_brief_spec.NoWriteRunTest` asserted the no-write rule at the job level —
  now true, because of change 3.
* `test_file_ops` and `test_pdf_pipeline` still asserted the old "PDF creation
  is unsupported" gap. Replaced with assertions that the PDF is real: `%PDF`
  magic bytes, size, and a second parse through `pypdf`.
* `test_brain.py` wrote `config/session_state.json` through
  `KeysBrain.process()` → `ContextManager.save_state()`, leaving fixture
  references in the user's real session state. `TestBrain` now runs with
  `brain.context.SESSION_STATE_PATH` patched to a temporary file.

## Not done in this entry

The wider audit brief (provider abstraction, sandboxing, document verification,
browser/desktop control, WhatsApp, 3D globe, UI work) is not covered here. No
claim is made about those areas beyond what their own tests show.
