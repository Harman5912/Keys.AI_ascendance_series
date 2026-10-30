"""
core/persona.py — KEYS.AI Personality Subsystem v1.0

Implements versioned personality, mode profiles, corpus-based example selection,
and system-prompt injection for KEYS.AI. Based on KEYS_AI_Personality_Playbook.
"""
from __future__ import annotations
import json
import random
import re
from pathlib import Path
from typing import Optional

PERSONA_VERSION = "1.0.0"

# ─── Trait stack (compact for injection) ─────────────────────────────────────
_TRAIT_STACK = """You are KEYS.AI — a capable digital co-pilot: warm, sharp, calm under pressure, curious, accountable, and privacy-aware.
Core traits: competence (verify before claiming), warmth (acknowledge naturally), dry wit (use sparingly), curiosity (ask only what changes the result), initiative (offer the next step), honesty (separate fact from inference), resilience (recover methodically), accountability (own errors plainly).
Address the user as "sir". Lead with the answer or next action. Natural contractions. One strong follow-up question when needed, not a questionnaire. Never claim sent/done/fixed unless a tool confirmed it."""

# ─── Mode profiles ────────────────────────────────────────────────────────────
MODES = {
    "companion": {
        "label": "Companion",
        "voice": "Warm, concise, lightly witty.",
        "humour_dial": 3,
        "verbosity": "concise",
        "extra": "Be personable. A short, warm reply is better than a long one.",
    },
    "focus": {
        "label": "Focus",
        "voice": "Direct, minimal banter, short checkpoints.",
        "humour_dial": 0,
        "verbosity": "concise",
        "extra": "Time-pressure mode. No small talk. One task, one outcome.",
    },
    "developer": {
        "label": "Developer",
        "voice": "Precise, test-led, architecture-aware.",
        "humour_dial": 1,
        "verbosity": "thorough",
        "extra": "Prioritise correctness, tests, and maintainability. Distinguish proposed from implemented, tested from untested.",
    },
    "research": {
        "label": "Research",
        "voice": "Source-first, citation-heavy, explicit uncertainty.",
        "humour_dial": 0,
        "verbosity": "thorough",
        "extra": "Always cite sources and dates. Separate verified facts from interpretation. Flag contradictions.",
    },
    "operator": {
        "label": "Operator",
        "voice": "Plan → act → observe → verify → report.",
        "humour_dial": 0,
        "verbosity": "structured",
        "extra": "Multi-step mode. Each action needs a verification step. Never claim success unverified.",
    },
    "coach": {
        "label": "Coach",
        "voice": "Encouraging, realistic, non-judgmental.",
        "humour_dial": 1,
        "verbosity": "concise",
        "extra": "Acknowledge feelings without diagnosing. Offer small, concrete next steps. Do not rush into solutions.",
    },
    "creative": {
        "label": "Creative",
        "voice": "Exploratory, imaginative, trade-off-aware.",
        "humour_dial": 2,
        "verbosity": "moderate",
        "extra": "Propose options; explain trade-offs. Label bold bets as such. Turn inspiration into something buildable.",
    },
    "quiet": {
        "label": "Quiet/Voice",
        "voice": "Short clauses, natural turn-taking, easy to interrupt.",
        "humour_dial": 0,
        "verbosity": "minimal",
        "extra": "Voice-friendly. Short sentences. Let user interrupt. Never narrate internal steps.",
    },
}

# ─── Intent → category mapping ───────────────────────────────────────────────
_INTENT_CATEGORY_MAP = {
    "greet":       "02_greetings_and_casual_check_ins",
    "identity":    "01_first_contact_and_identity",
    "wit":         "03_dry_wit_and_playful_banter",
    "daily":       "04_everyday_assistance",
    "code":        "05_coding_and_development_partner",
    "debug":       "06_debugging_and_recovery",
    "research":    "07_research_and_evidence",
    "plan":        "08_planning_and_task_management",
    "agent":       "09_multi_agent_orchestration_and_delegation",
    "complete":    "10_confirmed_completion_and_handoff",
    "fail":        "11_failures_limits_and_honest_recovery",
    "memory":      "12_memory_and_personalisation",
    "emotion":     "13_encouragement_and_emotional_awareness",
    "privacy":     "14_privacy_permissions_and_boundaries",
    "creative":    "15_creative_thinking_and_product_design",
    "multilang":   "16_multilingual_and_voice_interaction",
    "model":       "17_models_providers_and_offline_operation",
    "clarify":     "18_clarification_brevity_and_conversational_control",
}

# Risk classes that disable humour
_HIGH_RISK = {"destructive", "external_send", "privileged", "distress", "security"}


class PersonaEngine:
    """Central personality and example-retrieval engine for KEYS.AI."""

    def __init__(self, corpus_path: Optional[Path] = None):
        self._corpus: dict[str, list[dict]] = {}
        self._load_corpus(corpus_path)

    def _load_corpus(self, corpus_path: Optional[Path]) -> None:
        """Load keysai_dialogue_corpus.json and index by category id."""
        if corpus_path is None:
            # Search relative to this file and common locations
            candidates = [
                Path(__file__).parent / "keysai_dialogue_corpus.json",
                Path(__file__).parent.parent / "data" / "keysai_dialogue_corpus.json",
                Path(__file__).parent.parent / "keysai_dialogue_corpus.json",
            ]
            for p in candidates:
                if p.exists():
                    corpus_path = p
                    break

        if corpus_path and Path(corpus_path).exists():
            try:
                with open(corpus_path, encoding="utf-8") as f:
                    data = json.load(f)
                for cat in data.get("categories", []):
                    cid = cat.get("id", "")
                    self._corpus[cid] = cat.get("examples", [])
            except Exception as e:
                print(f"[Persona] Corpus load error: {e}")
        else:
            print("[Persona] Corpus not found — operating without example retrieval.")

    # ── Public API ──────────────────────────────────────────────────────────

    def get_mode(self, mode: str) -> dict:
        """Return the mode profile dict (fallback: companion)."""
        return MODES.get(mode.lower(), MODES["companion"])

    def infer_mode(self, task_description: str, default: str = "companion") -> str:
        """Heuristically infer the best mode from a task description."""
        td = task_description.lower()
        if any(w in td for w in ("build", "code", "debug", "fix", "refactor", "test", "api", "function", "class")):
            return "developer"
        if any(w in td for w in ("research", "find", "search", "compare", "source", "report")):
            return "research"
        if any(w in td for w in ("browse", "click", "navigate", "automate", "open", "fill", "form")):
            return "operator"
        if any(w in td for w in ("tired", "exhausted", "stuck", "motivation", "struggling", "failing")):
            return "coach"
        if any(w in td for w in ("idea", "design", "creative", "ux", "brand", "product", "concept")):
            return "creative"
        if any(w in td for w in ("quick", "hurry", "fast", "urgent", "deadline")):
            return "focus"
        if any(w in td for w in ("plan", "organise", "organize", "schedule", "priorit")):
            return "operator"
        return default

    def infer_intent(self, user_text: str) -> str:
        """Map user text to an intent key for example retrieval."""
        ut = user_text.lower()
        if any(w in ut for w in ("hello", "hey", "morning", "night", "back", "thanks for")):
            return "greet"
        if any(w in ut for w in ("who are you", "what are you", "your name", "different", "jarvis")):
            return "identity"
        if any(w in ut for w in ("code", "build", "refactor", "pull request", "review", "test", "api", "function")):
            return "code"
        if any(w in ut for w in ("error", "bug", "crash", "fix", "fail", "broken", "debug")):
            return "debug"
        if any(w in ut for w in ("research", "find", "sources", "report", "latest")):
            return "research"
        if any(w in ut for w in ("plan", "task", "organise", "milestone", "schedule")):
            return "plan"
        if any(w in ut for w in ("agent", "delegate", "parallel", "specialist", "team")):
            return "agent"
        if any(w in ut for w in ("done", "saved", "sent", "complete", "finish", "tomorrow")):
            return "complete"
        if any(w in ut for w in ("failed", "mistake", "wrong", "didn't", "limit", "can't", "try again")):
            return "fail"
        if any(w in ut for w in ("remember", "forget", "memory", "personalise", "preference")):
            return "memory"
        if any(w in ut for w in ("tired", "exhausted", "proud", "motivation", "listen", "struggle")):
            return "emotion"
        if any(w in ut for w in ("delete", "send", "admin", "private", "api key", "monitor")):
            return "privacy"
        if any(w in ut for w in ("idea", "bold", "creative", "futuristic", "design", "brand")):
            return "creative"
        if any(w in ut for w in ("hindi", "hinglish", "translate", "language", "voice", "microphone")):
            return "multilang"
        if any(w in ut for w in ("slow", "model", "offline", "local", "provider", "api quota")):
            return "model"
        if any(w in ut for w in ("just give", "shorter", "repeat", "clarify", "options", "three")):
            return "clarify"
        return "daily"

    def select_examples(self, intent: str, mode: str = "companion",
                         risk: str = "normal", n: int = 3) -> list[dict]:
        """Return up to n relevant dialogue examples for prompt injection."""
        # Never inject examples for high-risk / distress — just use plain voice
        if risk in _HIGH_RISK:
            return []
        cat_id = _INTENT_CATEGORY_MAP.get(intent, "")
        examples = self._corpus.get(cat_id, [])
        if not examples:
            return []
        # Pick a small random sample (deterministic by shuffling with seed)
        sample = examples[:]
        random.shuffle(sample)
        return sample[:n]

    def build_persona_block(self, mode: str = "companion", intent: str = "daily",
                             risk: str = "normal", lang: str = "en",
                             humour: Optional[int] = None,
                             verbosity: Optional[str] = None) -> str:
        """Return a compact persona block to prepend to any system prompt."""
        m = self.get_mode(mode)
        effective_humour = humour if humour is not None else m["humour_dial"]
        if risk in _HIGH_RISK:
            effective_humour = 0
        effective_verbosity = verbosity or m["verbosity"]

        lines = [
            _TRAIT_STACK,
            f"\nCurrent mode: {m['label']} — {m['voice']}",
            m["extra"],
            f"Humour dial: {effective_humour}/5. Verbosity: {effective_verbosity}.",
        ]
        if lang not in ("en", "english"):
            lines.append(f"Respond in {lang} unless the user switches language.")

        examples = self.select_examples(intent, mode, risk, n=2)
        if examples:
            ex_block = "\n".join(
                f"  USER: {e['user']}\n  KEYS.AI: {e['assistant']}"
                for e in examples
            )
            lines.append(f"\nTone reference (adapt, do not copy literally):\n{ex_block}")

        return "\n".join(lines)

    def get_system_prompt_addon(self, mode: str = "companion",
                                task_description: str = "") -> str:
        """Full injectable persona block derived from a task description."""
        inferred_mode = self.infer_mode(task_description, default=mode)
        intent = self.infer_intent(task_description)
        risk = "destructive" if any(
            w in task_description.lower()
            for w in ("delete", "remove", "overwrite", "format", "send all", "admin")
        ) else "normal"
        return self.build_persona_block(
            mode=inferred_mode, intent=intent, risk=risk
        )


# ── Singleton ──────────────────────────────────────────────────────────────────
_engine: Optional[PersonaEngine] = None


def _get_engine() -> PersonaEngine:
    global _engine
    if _engine is None:
        # Try to find corpus relative to this file
        corpus = Path(__file__).parent.parent / "data" / "keysai_dialogue_corpus.json"
        _engine = PersonaEngine(corpus_path=corpus if corpus.exists() else None)
    return _engine


def build_persona_block(mode: str = "companion", intent: str = "daily",
                         risk: str = "normal", lang: str = "en",
                         humour: Optional[int] = None,
                         verbosity: Optional[str] = None) -> str:
    return _get_engine().build_persona_block(mode, intent, risk, lang, humour, verbosity)


def get_system_prompt_addon(mode: str = "companion", task: str = "") -> str:
    return _get_engine().get_system_prompt_addon(mode, task)


def infer_mode(task: str) -> str:
    return _get_engine().infer_mode(task)


def infer_intent(text: str) -> str:
    return _get_engine().infer_intent(text)


def select_examples(intent: str, mode: str = "companion",
                     risk: str = "normal", n: int = 3) -> list[dict]:
    return _get_engine().select_examples(intent, mode, risk, n)
