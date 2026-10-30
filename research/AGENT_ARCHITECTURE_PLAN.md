# Agent architecture plan — research-first Crown Code

## Goal
Make Crown Code able to build anything the user asks for using the local model, with a deterministic research step before the build prompt is assembled.

## Current state
- `actions/crown_code.py` is the existing coding-agent entry point.
- It has a requirements gate in `core/brief_spec.py` (`analyse_brief`, `questions_text`, `refusal_text`, `merge_brief`).
- It has recipe builders for dashboard, Python desktop and game.
- It already has `research_mode == "browser"` wiring that hands the agent the real Research Browser actions.
- It does NOT yet have an explicit planning/research step for the general agent path: the user wants their request → brains think → ask missing details → research browser collects references/pictures/examples → assembled prompt → crown_code builds.

## Target flow
1. User asks to build X.
2. Brief analyzer reads the request and lists missing slots.
3. If missing slots exist, ask the user those questions (one at a time) and collect answers.
4. Research step:
   - For each concrete sub-part of the request, use the research browser (and web_search when needed) to gather examples, screenshots, docs, and usable assets.
   - Save collected references into the build workspace as planning evidence.
5. Assemble the final build prompt from: original request + confirmed requirements + research evidence + design tokens + recipe block when applicable.
6. Pass that prompt to crown_code for the actual build.
7. Verify the built artifact before opening it.

## First implementation pass
- Implement the orchestration in the app layer first, not by rewriting crown_code internals.
- New module: `actions/build_orchestrator.py`
  - Entry: `orchestrate_build(task, /, *, workspace=None, project_name=None, requirements=None, confirmed=False, research=True)`
  - Uses `core.brief_spec.analyse_brief` to find missing slots.
  - Uses `core.crown_code` questions/refusal semantics when appropriate.
  - Uses the existing research tools to collect references when `research=True`.
  - Composes the final brief and calls `crown_code` with it.
- Keep crown_code’s existing recipe path and requirements gate intact.
- Do not remove the local-model check; only require the model when the general agent path is used.

## What "best of the three" means here
- OpenHands: strong agent-loop and tool structure.
- OpenCode: developer-workflow ergonomics.
- Goose: task-oriented agent behavior.
- For Crown, the useful parts are: explicit planning/research before building, tool-gated builds, and verifiable artifacts. The repo already has most of the infrastructure; the missing piece is the orchestration layer that chains thinking, requirements, research, prompt assembly, build, and verification.

## Scope for the next step
- Start with the plan and one concrete orchestration interface.
- Do not yet rewrite the whole agent; prove the flow end-to-end on one request first.
