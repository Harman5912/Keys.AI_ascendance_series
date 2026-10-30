"""
Reasoning engine (spec §33 fallback path + general Q&A).

Produces plain conversational answers when the request doesn't need tools,
and can polish a tool-execution result into a natural final message.
Never exposes chain-of-thought — only the final safe response.
"""

from __future__ import annotations

from pathlib import Path
import sys


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


class ReasoningEngine:
    def __init__(self, provider, config, system_prompt: str = ""):
        self._provider = provider
        self._config   = config
        self._system_prompt = system_prompt or self._load_default_prompt()

    def _load_default_prompt(self) -> str:
        path = _base_dir() / "core" / "prompt.txt"
        try:
            system = path.read_text(encoding="utf-8")
        except Exception:
            system = ("You are Keys.ai, a premium desktop AI assistant. "
                      "Be concise, direct and helpful. Use tools for actions.")

        # Append the features knowledge base so the model can answer
        # "what can you do?" / "what features do you have?" questions
        # from a single authoritative source.
        try:
            from core.features_knowledge import WHAT_CAN_I_DO
            if WHAT_CAN_I_DO and WHAT_CAN_I_DO not in system:
                system = system + "\n\n" + WHAT_CAN_I_DO
        except Exception:
            pass

        return system

    @staticmethod
    def _with_personality(system: str, question: str = "") -> str:
        """Append the personality / SOUL / skills block so the model's own
        phrasing matches Keys.ai's identity. When the current question is
        known, the block also carries this turn's mode profile and a few
        retrieved dialogue examples (calibration, bounded).
        Guarded & non-breaking."""
        try:
            from personality import build_system_block
            block = build_system_block(user_text=question or "")
            if block and block not in system:
                return system + "\n\n" + block
        except Exception:
            pass
        return system

    def answer(self, question: str, context_text: str = "") -> str:
        """Return the answer text, or "" when the provider is unavailable so
        the caller can fall back to the normal conversational path (spec §33)."""
        if self._provider is None:
            return ""
        system = self._with_personality(self._system_prompt, question)
        if context_text:
            system = system + "\n\n" + context_text
        try:
            text = self._provider.generate(question, system=system,
                                           temperature=0.4)
            return (text or "").strip()
        except Exception as e:
            print(f"[Brain][Reasoning] ⚠️ {e}")
            return ""

    def polish(self, raw: str, user_request: str) -> str:
        """Optionally rephrase a tool result naturally (off by default)."""
        if self._provider is None or not raw:
            return raw
        try:
            return self._provider.generate(
                f"User asked: {user_request}\n\nTool result:\n{raw[:1500]}\n\n"
                "Respond naturally and concisely to the user as Keys.ai, "
                "stating what was done. Do NOT mention internal tools or "
                "plan steps.")
        except Exception:
            return raw
