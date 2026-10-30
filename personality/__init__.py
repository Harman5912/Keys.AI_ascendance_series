"""
PERSONALITY package — Keys.ai's identity, communication style, behavioral
rules and conversational humour engine.

    soul.py         identity + boundaries (+ optional workspace/SOUL.md)
    personality.py  communication style block
    behavior.py     standing behavioral rules (+ optional workspace/AGENTS.md)
    humor.py        context-aware humour post-processor for responses
    config.py       config/personality.json loader
    workspace.py    loader for the user-editable workspace/*.md docs

`build_system_block()` assembles the whole personality layer into one block
that is injected into LLM system prompts (brain chat path + Gemini Live path)
so the model's own language is personality-consistent.
"""

from __future__ import annotations

from personality.behavior import Behavior
from personality.config import PersonalityConfig, load_personality_config
from personality.humor import ConversationalHumor
from personality.modes import mode_block, mode_for as select_mode
from personality.personality import Personality
from personality.soul import Soul
from personality.workspace import load_workspace_block, workspace_dir

__all__ = [
    "PersonalityConfig", "load_personality_config", "Personality", "Soul",
    "Behavior", "ConversationalHumor", "build_system_block",
    "PersonalitySystem", "load_workspace_block", "workspace_dir",
    "select_mode", "mode_block",
]


def persona_block(config: PersonalityConfig | None = None) -> str:
    """Versioned persona core: identity version, tool-truth rules, language
    policy and the humour baseline — rendered as data from config."""
    config = config or load_personality_config()
    persona = config.persona()
    if not persona:
        return ""
    lines = []
    version = persona.get("version")
    if version:
        lines.append(f"PERSONA VERSION {version} (behaviour spec, "
                     "Personality Playbook).")
    truth = persona.get("tool_truth") or []
    if truth:
        lines.append("TOOL TRUTH (completion language standard):")
        lines += [f"- {rule}" for rule in truth]
    language = persona.get("language_policy")
    if language:
        lines.append(f"LANGUAGE: {language}")
    dial = persona.get("humour_dial")
    if dial is not None:
        lines.append(f"HUMOUR DIAL: {dial}/5 baseline; never higher in "
                     "safety, privacy, high-stakes or distress contexts.")
    return "\n".join(lines)


def mode_and_examples_block(config: PersonalityConfig | None = None,
                            user_text: str = "", intent: str = "",
                            voice: bool = False) -> str:
    """The per-turn part: current mode + a few retrieved dialogue examples.

    With no user_text (session-level composition) this emits the mode
    *listing* instead, so the model can still switch naturally mid-session.
    Bounded by persona.example_count (hard-capped at 4 by the corpus).
    """
    from personality import corpus as _corpus
    from personality import modes as _modes

    config = config or load_personality_config()
    persona = config.persona()
    parts: list[str] = []
    mode = ""
    if persona.get("modes", True):
        if user_text:
            mode = _modes.mode_for(user_text, intent=intent, voice=voice)
            block = _modes.mode_block(mode)
        else:
            block = _modes.all_modes_block()
        if block:
            parts.append(block)
    if user_text and persona.get("examples", True):
        try:
            examples = _corpus.select_examples(
                text=user_text, mode=mode, intent=intent,
                k=int(persona.get("example_count", 3)))
            block = _corpus.format_examples(examples)
            if block:
                parts.append(block)
        except Exception:
            pass  # a corpus problem must never break prompt assembly
    return "\n\n".join(parts)


def build_system_block(config: PersonalityConfig | None = None,
                       include_skills: bool = True,
                       include_workspace: bool = True,
                       include_features: bool = True,
                       user_text: str = "", intent: str = "",
                       voice: bool = False) -> str:
    """Assemble identity + persona + style + behavior (+ per-turn mode and
    dialogue examples, + optional skills block, workspace docs, and features
    knowledge) into a single prompt block.
    Returns "" when the personality is disabled."""
    config = config or load_personality_config()
    if not config.get("enabled", True):
        return ""
    parts = [
        Soul(config).block(),
        persona_block(config),
        Personality(config).block(),
        Behavior(config).block(),
    ]
    try:
        block = mode_and_examples_block(config, user_text=user_text,
                                        intent=intent, voice=voice)
        if block:
            parts.append(block)
    except Exception:
        pass
    if include_skills:
        try:
            from skills.registry import skills_block
            block = skills_block()
            if block:
                parts.append(block)
        except Exception:
            pass
    if include_workspace:
        try:
            block = load_workspace_block()
            if block:
                parts.append(block)
        except Exception:
            pass
    if include_features:
        try:
            from core.features_knowledge import WHAT_CAN_I_DO
            if WHAT_CAN_I_DO:
                parts.append(WHAT_CAN_I_DO)
        except Exception:
            pass
    return "\n\n".join(p for p in parts if p)


class PersonalitySystem:
    """Runtime facade used by the brain and app: builds prompt blocks and
    owns the conversational humour engine."""

    def __init__(self, brain_config=None):
        self.config = load_personality_config()
        self.soul = Soul(self.config)
        self.personality = Personality(self.config)
        self.behavior = Behavior(self.config)
        self.humor = ConversationalHumor(brain_config)

    def system_block(self, user_text: str = "", intent: str = "") -> str:
        return build_system_block(self.config, user_text=user_text,
                                  intent=intent)

    def postprocess_response(self, response, context=None, intent: str = ""):
        self.humor.postprocess(response, context, intent)
