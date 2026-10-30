# Skills

The capability layer. A **skill** is a contract over a capability that already
exists: what it takes, what it returns, what permission it needs, and how it was
proven. It is not a second implementation of a tool.

```
user text ──► /skills command (skills/commands.py)      — deterministic, no model
model      ──► skills tool   (skills/tools.py)          — one declared tool
                    │
                    ▼
             registry (skills/registry.py)  discovery · enable/disable · duplicate detection
                    │
                    ▼
             runner (skills/runner.py)      inputs · permission · timeout · retries · trace
                    │
                    ▼
             the tool that already exists  (core/tool_registry.py)
```

## Baseline — what existed before this layer

| Area | State |
|---|---|
| `skills/registry.py` | A static list of 16 skill *descriptions* and a prompt block. No execution, no manifests, no state, no tests. |
| `core/tool_registry.py` | 34 real tools, lazily imported. Working. |
| `core/tool_declarations.py` | The model-facing declarations for those tools. Working. |
| `brain/safety.py` | The authoritative permission gate (SAFE / MODERATE / DANGEROUS, with argument escalation). Working. |
| `plugins/` | Drop-in `*.py` tools registered after the core registry. Working. |
| Tests | `qa_artifacts/regression_tests/`, pytest. Working. |

Nothing was replaced. The static list became a loaded registry; the tools, the
safety layer and the plugin path are untouched.

## Files

| File | Job |
|---|---|
| `skills/manifest.py` | `SkillManifest` — fields, defaults, validation, `input_schema()` |
| `skills/registry.py` | Discovery of `skills/builtin/*.py`, declared imports, enable/disable state, execution entry point, prompt block |
| `skills/runner.py` | `SkillContext`, `SkillResult`, input validation, permission check, timeout, retries, tracing |
| `skills/orchestrator.py` | Deterministic scoring of a request against the registered skills |
| `skills/commands.py` | `/help` and `/skills …` |
| `skills/tools.py` | The `skills` tool the model calls |
| `skills/inventory.py` | Machine-readable inventory + the readable catalog, evidence-based statuses |
| `skills/catalog.py` | The target capability list, so what is missing stays visible |
| `skills/builtin/*.py` | One module per real skill |

State and evidence live in `config/`:

| Path | Contents |
|---|---|
| `config/skills_state.json` | Which skills are disabled |
| `config/skills_declared.json` | Imported manifests (declarations only — never code) |
| `config/skills_evidence.json` | What actually ran, and when |
| `config/skills_inventory.json` | Generated inventory |
| `config/skills_log.jsonl` | One line per execution (no outputs, so secrets stay out) |

## Adding a skill

1. **Check first.** `/skills search <query>` and `skills/orchestrator.select()`.
   If an existing skill covers it, change that skill instead — a rename is not a
   new capability.
2. **Find the real implementation.** Almost always a tool in
   `core/tool_registry.py`. If the tool does not exist, build the tool, not a
   skill that pretends to.
3. **Write the module** in `skills/builtin/<name>.py`:

```python
from skills.builtin._delegate import run_tool

SKILL = {
    "name": "my-skill",                 # a-z and dashes, unique
    "purpose": "One sentence a user would recognise.",
    "version": "1.0.0",
    "group": "software",
    "permission": "SAFE",               # least privilege; arguments escalate
    "tools": ["the_tool_that_does_it"],
    "instructions": "How to use it well.",
    "triggers": ["phrases a user would actually say"],
    "inputs": {"action": {"type": "string", "required": True}},
    "outputs": ["what the user gets"],
    "timeout": 60.0,
    "tags": ["words", "that", "help", "selection"],
}

def run(parameters, ctx):
    return run_tool("the_tool_that_does_it", parameters, ctx)

def verify():                            # optional but expected
    from skills.builtin._delegate import tool_ready
    ok, detail = tool_ready("the_tool_that_does_it")
    return ok, detail                    # add ", 'functional'" once it really runs
```

4. **Register it.** Drop the file in `skills/builtin/` — discovery is automatic,
   no import list to edit. Duplicate names are refused, not merged.
5. **Test it** in `qa_artifacts/regression_tests/test_skill_system.py` and record
   evidence after the test executes it:
   `inventory.record("my-skill", "TESTED", "test_skill_system: …")`.
6. **Verify it** where it can really run, then refresh the inventory:
   `python -m skills.inventory --check --write`.

## Statuses — evidence, not optimism

| Status | Meaning |
|---|---|
| `PLANNED` | Named in the target catalog with no implementation |
| `BLOCKED` | Implementation exists but is untrustworthy (bad manifest, missing dependency, import failure) |
| `REGISTERED` | Implemented and valid, never executed by a test |
| `TESTED` | A test executed it |
| `VERIFIED` | A live check exercised the real work here |

`verify()` may return `(ok, detail)` — wiring only, recorded as `TESTED` — or
`(ok, detail, "functional")` — recorded as `VERIFIED`. A later wiring-only check
**clears** an older `VERIFIED` claim. Nothing is marked verified because a file
exists.

Disabled is a separate axis (`enabled`), so the report distinguishes available,
disabled, incomplete, tested and verified.

## Commands

```
/skills                     list every skill and its status
/skills search <query>      find skills by name, purpose or trigger
/skills inspect <name>      manifest, inputs, tools, permission and state
/skills run <name> [k=v ..] run a skill now (asks first if it is not SAFE)
/skills enable|disable <n>  change what may run
/skills validate [name]     manifest and dependency problems
/skills test <name>         run that skill's own live check
/skills diagnose            counts, duplicates, load errors
/skills list-tools <name>   the registered tools a skill uses
/skills history             the last executions
/skills export <name>       print the manifest as JSON
/skills import <path.json>  install a manifest (never code)
/skills remove <name> --yes delete an imported manifest
/skills create <name> <p>   declare a capability that does not exist yet
/skills plan <request>      which skills would handle this request
/help                       the list
```

Typed commands are answered in `main.py::_on_text_command` before the model sees
the text, so they work with no live session.

## Security

- **Least privilege.** A manifest declares the permission of its *least*
  privileged action. `brain/safety.py` escalates by argument, so `/skills run
  files action=delete` is DANGEROUS even though listings are SAFE.
- **Approval is the user's, not the model's.** MODERATE and DANGEROUS skills
  refuse unless `approved=True`, which the engine sets from an explicit answer.
- **No code import.** `/skills import` accepts JSON manifests only; a `.py` file
  is refused because importing it would execute it. `/skills install` refuses
  remote packages and says why.
- **Logs keep no outputs.** `config/skills_log.jsonl` records skill, outcome,
  attempts and error — not the returned text, which can contain private data.
- **Skill output is untrusted.** A skill that read a web page returns content,
  not instructions; the orchestrator never re-parses output as commands.

## Limitations

- Selection is lexical (triggers, tags, names), not semantic. It is predictable
  and cheap; it will miss a paraphrase that shares no words with a skill.
- No automatic multi-skill execution yet: the orchestrator *proposes* a set of
  skills and a reason for each; running them in sequence is still the caller's
  step. `parallel_safe` is recorded in manifests but nothing schedules on it.
- No resume-from-saved-state; `task-resume` is listed as PLANNED.
- `verify()` for most skills proves wiring, not end-to-end behaviour, and the
  inventory says so. Only `globe` and `design-system` are `VERIFIED` today.
- 127 of the 137 catalogued capabilities have no implementation. They are listed
  in `docs/SKILL_CATALOG.md` rather than being faked.
