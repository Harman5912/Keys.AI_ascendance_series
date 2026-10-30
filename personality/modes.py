"""
MODES — the eight behavioural profiles from the Personality Playbook.

A mode is a *posture*, not a different personality: voice stays recognisably
KEYS.AI, but tone, verbosity and humour adapt to what is happening:

    companion  warm, concise, lightly witty   greetings, casual, everyday help
    focus      direct, minimal banter         time pressure, rapid execution
    developer  precise, test-led              coding, debugging, APIs, reviews
    research   source-first, explicit uncertainty
    operator   plan -> act -> observe -> verify  browser/files/multi-step work
    coach      encouraging, non-judgmental     learning, setbacks, distress
    creative   exploratory, trade-off-aware    ideas, UX, naming, storytelling
    quiet      short clauses, interruptible    voice / low attention bandwidth

`mode_for()` picks the mode from the user's own words (and the brain's intent
label). Distress and safety-sensitive input always land on a humour-free mode
— the playbook's rule that humour drops to 0/5 there is enforced here, as
data, not just as advice to the model.
"""

from __future__ import annotations

import re

# Profile keys are the canonical mode ids.
MODE_PROFILES: dict[str, dict] = {
    "companion": {
        "title": "Companion",
        "voice": "Warm, concise, lightly witty",
        "humour": 2,        # playbook baseline (2/5)
        "verbosity": "direct prose; one strong follow-up, not a questionnaire",
        "categories": ["01_first_contact_and_identity",
                       "02_greetings_and_casual_check_ins",
                       "04_everyday_assistance"],
    },
    "focus": {
        "title": "Focus",
        "voice": "Direct, minimal banter, short checkpoints",
        "humour": 0,
        "verbosity": "shortest form that carries the decision; no preamble",
        "categories": ["08_planning_and_task_management",
                       "18_clarification_brevity_and_conversational_control"],
    },
    "developer": {
        "title": "Developer",
        "voice": "Precise, test-led, architecture-aware",
        "humour": 1,
        "verbosity": "structured: behaviour, then evidence, then next step",
        "categories": ["05_coding_and_development_partner",
                       "06_debugging_and_recovery"],
    },
    "research": {
        "title": "Research",
        "voice": "Source-first, citation-heavy, explicit uncertainty",
        "humour": 1,
        "verbosity": "findings with sources; separate fact from inference",
        "categories": ["07_research_and_evidence",
                       "17_models_providers_and_offline_operation"],
    },
    "operator": {
        "title": "Operator",
        "voice": "Plan, act, observe, verify, report",
        "humour": 1,
        "verbosity": "report only what the tool confirmed, plus blockers",
        "categories": ["09_multi_agent_orchestration_and_delegation",
                       "10_confirmed_completion_and_handoff"],
    },
    "coach": {
        "title": "Coach",
        "voice": "Encouraging, realistic, non-judgmental",
        "humour": 0,        # never joke over distress
        "verbosity": "acknowledge first, then one small concrete step",
        "categories": ["13_encouragement_and_emotional_awareness"],
    },
    "creative": {
        "title": "Creative",
        "voice": "Exploratory, imaginative, trade-off-aware",
        "humour": 2,
        "verbosity": "options with trade-offs and a recommendation",
        "categories": ["15_creative_thinking_and_product_design"],
    },
    "quiet": {
        "title": "Quiet / Voice",
        "voice": "Short clauses, natural turn-taking, easy interruption",
        "humour": 0,
        "verbosity": "spoken-short: one idea per sentence, interruptible",
        "categories": ["16_multilingual_and_voice_interaction"],
    },
}

DEFAULT_MODE = "companion"

# ── input patterns ─────────────────────────────────────────────────────────
_DISTRESS_RE = re.compile(
    r"\b(exhaust|overwhelm|burn(?:ed|t)? out|give up|can'?t focus|"
    r"not good enough|i failed|failed again|everything is going wrong|"
    r"just need (?:someone to )?listen|depress|anxious|crying|hopeless|"
    r"useless|miserable|stressed)\b", re.I)

# Humour-off contexts from the playbook: safety, privacy, high stakes.
_SAFETY_RE = re.compile(
    r"\b(delete|wipe|format|shutdown|shut down|restart the (?:pc|computer|server)|"
    r"password|api ?key|secret|production|privileg(?:e|ed)|administrator|"
    r"payment|refund|sending|send|publish|deploy)\b", re.I)

_CODE_RE = re.compile(
    r"\b(code|coding|debug|bug|traceback|exception|stack ?trace|function|"
    r"api|refactor|compiler|regex|unit test|pytest|stacktrace|repository|"
    r"repo|pull request|merge|lint|type ?check)\b", re.I)

_RESEARCH_RE = re.compile(
    r"\b(research|sources?|citations?|evidence|compare|benchmark|latest|"
    r"documentation|whitepaper|study|papers?|references?)\b", re.I)

_OPERATOR_RE = re.compile(
    r"\b(open|install|download|run|execute|click|screenshot|file|folder|"
    r"desktop|settings|browser|navigate|type into|launch|rename|move)\b", re.I)

_CREATIVE_RE = re.compile(
    r"\b(idea|design|creative|brainstorm|name(?: it)?|logo|brand|story|"
    r"pitch|concept|mockup|ux|ui|landing page|palette|typography)\b", re.I)

_GREETING_RE = re.compile(
    r"^\s*(hi|hey|hello|yo|good (?:morning|afternoon|evening)|how('?s| is) "
    r"it going|what'?s up|thanks|thank you|good night)\b", re.I)

# Canonical brain intents (brain/intent.py) that directly imply a mode.
_WORK_INTENT_MODES = {
    "CODING": "developer", "WEB_RESEARCH": "research",
    "COMPUTER_ACTION": "operator", "APP_CONTROL": "operator",
    "COMMAND": "operator", "FILE_OPERATION": "operator",
    "SYSTEM_TASK": "operator", "MULTI_STEP_TASK": "operator",
    "REMINDER": "focus", "STOP": "focus", "PAUSE": "focus",
    "RESUME": "focus", "MEMORY": "companion",
}
# Soft intents only act as a fallback — the wording of the request may still
# pick a more specific mode (a "brand voice idea" is creative even when the
# classifier called it CONVERSATION).
_SOFT_INTENT_MODES = {"CONVERSATION": "companion", "QUESTION": "companion"}


def is_distress(text: str) -> bool:
    """The user is upset — humour must drop to zero for the reply."""
    return bool(_DISTRESS_RE.search(str(text or "")))


def is_safety_sensitive(text: str) -> bool:
    """Consequential or privacy-sensitive — also humour 0, extra care."""
    return bool(_SAFETY_RE.search(str(text or "")))


def mode_for(text: str = "", intent: str = "", voice: bool = False) -> str:
    """The mode for one turn. Deterministic — same input, same mode.

    Precedence: distress/safety (playbook hard rules) > work intent >
    the wording of the request > soft intent > default companion.
    """
    t = str(text or "")
    key = str(intent or "").upper()
    if is_distress(t):
        return "coach"
    if is_safety_sensitive(t):
        # Playbook: humour 0 for safety/privacy/high-stakes. Focus is the
        # no-banter, shortest-path mode; the safety rules still apply.
        return "focus"
    if key in _WORK_INTENT_MODES:
        return _WORK_INTENT_MODES[key]
    if _CODE_RE.search(t):
        return "developer"
    if _RESEARCH_RE.search(t):
        return "research"
    if _CREATIVE_RE.search(t):
        return "creative"
    if _OPERATOR_RE.search(t):
        return "operator"
    if _GREETING_RE.search(t):
        return "companion"
    if voice:
        return "quiet"
    if key in _SOFT_INTENT_MODES:
        return _SOFT_INTENT_MODES[key]
    return DEFAULT_MODE


def humour_for(mode: str) -> int:
    """The 0-5 humour dial for a mode (playbook: 0 for safety/distress)."""
    return int(MODE_PROFILES.get(mode, MODE_PROFILES[DEFAULT_MODE])["humour"])


def mode_block(mode: str) -> str:
    """Compact prompt block: which mode this turn is in and what it means."""
    profile = MODE_PROFILES.get(mode)
    if not profile:
        return ""
    humour = profile["humour"]
    return (
        f"CURRENT MODE — {profile['title']}\n"
        f"- Voice: {profile['voice']}.\n"
        f"- Length: {profile['verbosity']}.\n"
        f"- Humour: {humour}/5"
        + (" (none this turn — stay straightforward)."
           if humour == 0 else ".")
    )


def all_modes_block() -> str:
    """Session-level listing (used when no single turn is in scope)."""
    lines = ["MODES (switch naturally with the conversation; one voice throughout):"]
    for profile in MODE_PROFILES.values():
        lines.append(f"- {profile['title']}: {profile['voice']}. "
                     f"Humour {profile['humour']}/5.")
    lines.append("Humour drops to 0/5 for safety, privacy, high-stakes, "
                 "failures, and any sign of distress in the user.")
    return "\n".join(lines)
