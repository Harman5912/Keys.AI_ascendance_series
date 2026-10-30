"""
core/agent_coordinator.py — Lightweight coordinator for KEYS.AI agents.

Classifies requests as simple (direct answer) vs complex (multi-step plan).
Routes to specialist: developer, researcher, browser_operator, data, reviewer.
Inspired by CrewAI role-based agents and the KEYS_AI_Personality_Playbook spec.
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


# ── Task lifecycle ─────────────────────────────────────────────────────────────

@dataclass
class TaskPlan:
    request_id: str
    task_id: str
    goal: str
    assigned_agent: str          # coordinator | researcher | developer | browser | data | reviewer
    dependencies: list[str] = field(default_factory=list)
    risk_level: str = "normal"  # normal | high | destructive
    input_refs: list[str] = field(default_factory=list)
    expected_output: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    status: str = "pending"      # pending | running | done | failed | blocked


@dataclass
class AgentResult:
    request_id: str
    task_id: str
    agent_id: str
    status: str                  # success | failure | partial
    summary: str
    evidence_refs: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    verification: str = ""
    elapsed_ms: int = 0
    provider: str = ""


@dataclass
class PermissionDecision:
    action: str
    resource: str
    risk: str
    decision: str                # allow | deny | needs_confirmation
    reason: str
    policy_id: str = "default"


# ── Permission policy ──────────────────────────────────────────────────────────

_DESTRUCTIVE_PATTERNS = [
    r'\bdelete\b', r'\bremove\b', r'\boverwrite\b', r'\bformat\b',
    r'\bdrop\b', r'\bpurge\b', r'\bwipe\b', r'\btruncate\b',
]

_EXTERNAL_PATTERNS = [
    r'\bsend\b.*\bemail\b', r'\bsend\b.*\bmessage\b', r'\bpost\b.*\btwitter\b',
    r'\bpublish\b', r'\bcommit\b.*\bpush\b',
]

_PRIVILEGED_PATTERNS = [
    r'\badmin\b', r'\bsudo\b', r'\belevat\b', r'\broot\b', r'\bregistry\b',
]


def evaluate_permission(action: str, resource: str = "") -> PermissionDecision:
    """
    Evaluate whether an action is allowed, needs confirmation, or is denied.
    Policy is in application code — not solely in prompts.
    """
    combined = f"{action} {resource}".lower()

    for pat in _DESTRUCTIVE_PATTERNS:
        if re.search(pat, combined):
            return PermissionDecision(
                action=action, resource=resource, risk="destructive",
                decision="needs_confirmation",
                reason="Destructive action requires explicit user confirmation.",
                policy_id="L4_destructive",
            )

    for pat in _EXTERNAL_PATTERNS:
        if re.search(pat, combined):
            return PermissionDecision(
                action=action, resource=resource, risk="external_send",
                decision="needs_confirmation",
                reason="External message/send requires explicit user confirmation.",
                policy_id="L4_external",
            )

    for pat in _PRIVILEGED_PATTERNS:
        if re.search(pat, combined):
            return PermissionDecision(
                action=action, resource=resource, risk="privileged",
                decision="needs_confirmation",
                reason="Privileged action requires elevated permission.",
                policy_id="L4_privileged",
            )

    return PermissionDecision(
        action=action, resource=resource, risk="normal",
        decision="allow", reason="Normal action within current permissions.",
        policy_id="L0_L3",
    )


# ── Request complexity classifier ─────────────────────────────────────────────

_COMPLEX_INDICATORS = [
    r'\band\b.*\band\b', r'\bmultiple\b', r'\bsteps?\b', r'\bfirst.*then\b',
    r'\bbuild\b', r'\bcreate\b.*\bfull\b', r'\bproject\b', r'\bapp\b',
    r'\bpipeline\b', r'\bworkflow\b', r'\bintegrat\b',
]

_SIMPLE_INDICATORS = [
    r'^(what|who|when|where|why|how)\b', r'^(explain|define|describe)\b',
    r'^(hello|hi|hey|good\s+morning)\b',
]


def classify_request(user_text: str) -> str:
    """Return 'simple' or 'complex'."""
    ut = user_text.strip().lower()
    for pat in _SIMPLE_INDICATORS:
        if re.match(pat, ut):
            return "simple"
    score = sum(1 for pat in _COMPLEX_INDICATORS if re.search(pat, ut))
    return "complex" if score >= 2 else "simple"


def select_agent(task_description: str) -> str:
    """Select the best specialist agent for a task."""
    td = task_description.lower()
    if any(w in td for w in ("build", "code", "implement", "write", "refactor", "test", "debug", "fix")):
        return "developer"
    if any(w in td for w in ("research", "find", "search", "compare", "sources", "github")):
        return "researcher"
    if any(w in td for w in ("browse", "click", "navigate", "screenshot", "website", "open url")):
        return "browser"
    if any(w in td for w in ("data", "spreadsheet", "csv", "chart", "calculate", "table")):
        return "data"
    if any(w in td for w in ("review", "verify", "check", "validate", "security", "audit")):
        return "reviewer"
    return "coordinator"


class AgentCoordinator:
    """
    Lightweight coordinator: classify → plan → authorize → dispatch → collect → compose.
    """

    def plan(self, user_text: str, request_id: Optional[str] = None) -> list[TaskPlan]:
        """Break a request into task plans with stable IDs."""
        rid = request_id or str(uuid.uuid4())[:8]
        complexity = classify_request(user_text)

        if complexity == "simple":
            return [TaskPlan(
                request_id=rid,
                task_id=f"{rid}_t1",
                goal=user_text,
                assigned_agent="coordinator",
                status="pending",
                acceptance_criteria=["Response delivered to user."],
            )]

        # Complex: split into research + develop + review
        plans = []
        agent = select_agent(user_text)

        if agent in ("developer",):
            plans.append(TaskPlan(
                request_id=rid, task_id=f"{rid}_t1",
                goal=f"Research context and requirements for: {user_text[:100]}",
                assigned_agent="researcher", status="pending",
                acceptance_criteria=["Research dossier complete."],
            ))
            plans.append(TaskPlan(
                request_id=rid, task_id=f"{rid}_t2",
                goal=user_text, assigned_agent="developer", status="pending",
                dependencies=[f"{rid}_t1"],
                acceptance_criteria=["Code compiles.", "Tests pass."],
            ))
            plans.append(TaskPlan(
                request_id=rid, task_id=f"{rid}_t3",
                goal="Review and verify the output.",
                assigned_agent="reviewer", status="pending",
                dependencies=[f"{rid}_t2"],
                acceptance_criteria=["Acceptance criteria met."],
            ))
        else:
            plans.append(TaskPlan(
                request_id=rid, task_id=f"{rid}_t1",
                goal=user_text, assigned_agent=agent, status="pending",
                acceptance_criteria=["Task complete."],
            ))
        return plans

    def authorize(self, action: str, resource: str = "") -> PermissionDecision:
        return evaluate_permission(action, resource)

    def format_status(self, plans: list[TaskPlan], results: list[AgentResult]) -> str:
        """Format a status update for the user."""
        done = [p for p in plans if p.status == "done"]
        running = [p for p in plans if p.status == "running"]
        blocked = [p for p in plans if p.status == "blocked"]
        lines = [
            f"Status: {len(done)}/{len(plans)} tasks complete.",
        ]
        if running:
            lines.append(f"In progress: {', '.join(p.goal[:40] for p in running)}.")
        if blocked:
            lines.append(f"Blocked: {', '.join(p.goal[:40] for p in blocked)}.")
        for r in results:
            if r.errors:
                lines.append(f"Errors: {'; '.join(r.errors[:2])}.")
        return " ".join(lines)


# Singleton
_coordinator = AgentCoordinator()


def plan_request(user_text: str) -> list[TaskPlan]:
    return _coordinator.plan(user_text)


def authorize_action(action: str, resource: str = "") -> PermissionDecision:
    return _coordinator.authorize(action, resource)


def classify(user_text: str) -> str:
    return classify_request(user_text)
