"""Skill selection — choose the smallest set of skills a request needs.

Deterministic on purpose: the orchestrator scores the request against the skills
that exist, and says so. It never invokes everything, never invents a skill, and
asks for clarification when nothing matches well enough — that is more useful
than a confident wrong plan.

Scores (each is small and explainable):

    3  the request literally contains one of the skill's triggers
    2  a word of the request appears in the skill's name or primary tool
    1  a word appears in its purpose, tags or capabilities
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_STOPWORDS = {
    "the", "a", "an", "to", "for", "of", "on", "in", "me", "my", "and", "with",
    "please", "can", "you", "this", "that", "it", "is", "at", "from", "show",
}


@dataclass
class Candidate:
    name: str
    score: int
    reason: str
    needs_approval: bool = False

    def as_dict(self) -> dict:
        return {"name": self.name, "score": self.score, "reason": self.reason,
                "needs_approval": self.needs_approval}


@dataclass
class Plan:
    request: str
    candidates: list[Candidate] = field(default_factory=list)
    clarification: str = ""
    note: str = ""

    @property
    def skills(self) -> list[str]:
        return [c.name for c in self.candidates]

    def as_dict(self) -> dict:
        return {"request": self.request,
                "skills": [c.as_dict() for c in self.candidates],
                "clarification": self.clarification, "note": self.note}


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9-]{2,}", str(text).lower())
            if w not in _STOPWORDS]


def score_skill(entry, text: str) -> Candidate | None:
    manifest = entry.manifest
    lowered = str(text).lower()
    score = 0
    reasons: list[str] = []

    for trigger in manifest.triggers:
        trigger = trigger.lower().strip()
        if trigger and trigger in lowered:
            score += 3
            reasons.append(f"phrasing matches '{trigger}'")
            break

    words = set(_words(text))
    name_words = set(_words(manifest.name))
    tool_words = set(_words(" ".join(manifest.tools)))
    if words & (name_words | tool_words):
        score += 2
        reasons.append("name or tool matches the request")

    rest = " ".join([manifest.purpose, " ".join(manifest.tags),
                     " ".join(manifest.capabilities)]).lower()
    hits = [w for w in words if w in rest]
    if hits:
        score += 1
        reasons.append("description mentions " + ", ".join(sorted(hits)[:4]))

    if not score:
        return None
    return Candidate(name=manifest.name, score=score,
                     reason="; ".join(reasons) or "weak match",
                     needs_approval=manifest.permission != "SAFE")


def select(registry, text: str, limit: int = 3) -> list[Candidate]:
    """The skills worth using for `text`, best first, at most `limit`."""
    scored: list[Candidate] = []
    for entry in registry.enabled():
        candidate = score_skill(entry, text)
        if candidate is not None:
            scored.append(candidate)
    scored.sort(key=lambda c: (-c.score, c.name))
    if not scored:
        return []
    best = scored[0].score
    # Keep the set small: only skills close to the best score are relevant.
    chosen = [c for c in scored if c.score >= max(2, best - 1)][:max(1, limit)]
    return chosen


def plan(registry, text: str, limit: int = 3) -> Plan:
    """A plan is the selected skills, each with a reason the user can audit."""
    result = Plan(request=str(text or "").strip())
    if not result.request:
        result.clarification = "What would you like me to do?"
        return result
    result.candidates = select(registry, result.request, limit=limit)
    if not result.candidates:
        result.clarification = (
            "I do not have a skill that covers that yet. Tell me what outcome "
            "you want and I will say which part is missing."
        )
        return result
    result.note = ("Skills are run one at a time, in this order; only the ones "
                   "marked as needing approval will ask first.")
    return result
