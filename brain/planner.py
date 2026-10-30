"""
Agentic planner (spec §9).

Breaks a complex request into concrete steps. Steps reference REGISTERED tools
only (never arbitrary Python). If the LLM is unavailable or the response can't
be parsed, it falls back to a single-step template from the router, so the
brain degrades gracefully.

Step schema (spec §10):
    {"id", "description", "tool", "arguments", "status", "result", "error"}
"""

from __future__ import annotations

import re

from brain.state import new_plan, new_step


class Planner:
    def __init__(self, provider, tool_registry, config):
        self._provider = provider
        self._tools    = tool_registry
        self._config   = config

    def create_plan(self, user_input: str, intent, resolved_text: str,
                    context_snapshot: str) -> dict | None:
        """Returns a plan dict {"summary", "steps": [...]} or None (chat)."""
        max_steps = int(self._config.get("max_iterations", 10))

        if self._provider is not None:
            try:
                plan = self._llm_plan(user_input, intent, resolved_text,
                                      context_snapshot, max_steps)
                if plan and plan.get("steps"):
                    return plan
            except Exception as e:
                print(f"[Brain][Planner] ⚠️ LLM plan failed, falling back: {e}")

        # ── template fallback: single deterministic step ─────────────────
        from brain.router import Router
        route = Router(self._tools, None).route(resolved_text, intent,
                                                resolved_text)
        if route.kind == "single_tool":
            plan = new_plan(user_input, intent.primary, "Single step")
            # User-facing description: prefer the user's own words (the
            # router supplies them for some routes), never the internal
            # route reason — this text lands in the confirmation question.
            plan["steps"].append(new_step(
                (route.arguments or {}).get("description")
                or f"use {route.tool}",
                route.tool, route.arguments))
            return plan
        return None

    # ── LLM plan ─────────────────────────────────────────────────────────
    def _llm_plan(self, user_input, intent, resolved_text, context_snapshot,
                  max_steps) -> dict | None:
        tools_desc = self._tools.descriptions(max_tools=60)
        prompt = f"""You are the planning engine of Keys.ai, a desktop AI operator.

Break the user's request into an ordered, minimal plan of concrete steps.
Each step MUST call one of the REGISTERED tools below with its arguments.
Never invent tools. Prefer the least number of steps that completes the task.
If the request is actually just a conversation or a simple question, return
{{"chat": true}} with no steps.

Registered tools:
{tools_desc}

RESOLVED USER REQUEST (pronouns already resolved):
{resolved_text}

ORIGINAL USER REQUEST:
{user_input}

INTENT: {intent.primary} {intent.tags}

RECENT CONTEXT:
{context_snapshot[:2500]}

Return JSON exactly like:
{{
  "summary": "one-line plan summary",
  "chat": false,
  "steps": [
    {{"description": "what this step does", "tool": "registered_tool_name",
      "arguments": {{...tool arguments...}}}}
  ]
}}
or {{"chat": true, "steps": []}} if no tools are needed.
Use at most {max_steps} steps. Keep each step self-contained; use the context
to avoid repeating already-known steps."""

        obj = self._provider.structured_output(prompt)
        if not isinstance(obj, dict):
            return None
        if obj.get("chat"):
            return None

        steps = obj.get("steps") or []
        if not isinstance(steps, list):
            return None

        plan = new_plan(user_input, intent.primary,
                        str(obj.get("summary", ""))[:200])
        for s in steps[:max_steps]:
            if not isinstance(s, dict):
                continue
            tool = str(s.get("tool", "") or "").strip()
            if not self._tools.has(tool):
                print(f"[Brain][Planner] Skipping unknown tool: {tool}")
                continue
            plan["steps"].append(new_step(
                str(s.get("description", tool)),
                tool,
                s.get("arguments") if isinstance(s.get("arguments"), dict)
                else {}))
        return plan if plan["steps"] else None
