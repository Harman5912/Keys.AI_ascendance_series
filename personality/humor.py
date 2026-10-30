"""
HUMOUR ENGINE (conversational) — context-aware humour for normal responses.

Distinct from agent_control/humour.py (which only fires on Agent-Control
events): this engine post-processes ANY final response text and decides
whether a short humorous remark is appropriate, then appends one.

Decision model:
    HUMOR_NOT_APPROPRIATE — errors, code, safety, confirmation dialogs,
                            sensitive topics, questions to the user, ...
    HUMOR_ALLOWED         — successful actions (open, run, send, ...)
    HUMOR_OPTIONAL        — normal conversation / Q&A

Hygiene rules:
    * humour never changes the information content — it only appends
    * a cooldown prevents two remarks in consecutive turns
    * lines are never repeated (LRU) and categories are varied
    * intensity follows Agent Control humour_level (OFF/LOW/MEDIUM/HIGH) and
      professional_mode is a hard kill switch, so one knob rules all humour
    * failures are swallowed — humour can never break a response

Categories: DRY | WITTY | PLAYFUL | SARCASTIC_LIGHT | TECH_HUMOR | SITUATIONAL | NONE
"""

from __future__ import annotations

import random
import re
import threading

from personality.config import load_personality_config

# ── categories & pools (short, technical, personality-consistent) ───────────
_CATEGORIES = ("TECH_HUMOR", "SITUATIONAL", "WITTY", "DRY", "PLAYFUL",
               "SARCASTIC_LIGHT")

_POOLS: dict[str, list[str]] = {
    "TECH_HUMOR": [
        "VS Code is open. Time to make some bugs feel unemployed.",
        "Done. No computers were harmed in the making of that task.",
        "Task complete. The code now behaves like it was written on purpose.",
        "It worked. I'm as surprised as you are.",
        "That's not a bug — that's the code expressing its boundaries.",
        "Consider it handled. Suspiciously smoothly, even.",
    ],
    "SITUATIONAL": [
        "Opening {app}. Let's unleash the internet chaos.",
        "{app} loading. This is the part where I hold my breath.",
        "Summoning {app}…",
        "Fingers crossed and CPUs caffeinated.",
        "Ah, {app}. Where bugs go to reproduce.",
    ],
    "WITTY": [
        "Because apparently your semicolon decided to take a vacation.",
        "The error has been located. It was inside the code all along. One of the two.",
        "That error message has the confidence of someone who knows absolutely nothing.",
        "I found it. It was hiding in plain sight. Classic.",
        "Somewhere, a rubber duck is getting blamed for this.",
    ],
    "DRY": [
        "Everything is fine. Which is exactly what people say right before it isn't.",
        "The code works. Please don't ask what I had to sacrifice.",
        "I have decided not to investigate why it worked.",
        "Executed. Results may vary. They didn't.",
        "It's not a problem. It's an undocumented feature.",
    ],
    "PLAYFUL": [
        "Words are being typed. Try not to blink.",
        "One click, coming up.",
        "Opening the thing. The thing being opened is the target. Obviously.",
        "The cursor moved with intent. Mission accomplished.",
    ],
    "SARCASTIC_LIGHT": [
        "The compiler has chosen violence today.",
        "The server is thinking about it. Emphasis on 'about'.",
        "Your machine is negotiating with reality. Give it a second.",
        "Waiting on the CPU. It's doing its best.",
    ],
}

_STYLE_PREFERENCE = {
    "dry": ("DRY", "TECH_HUMOR"),
    "witty": ("WITTY", "TECH_HUMOR"),
    "playful": ("PLAYFUL", "SITUATIONAL"),
    "sarcastic_light": ("SARCASTIC_LIGHT", "WITTY"),
    "tech_humor": ("TECH_HUMOR", "SITUATIONAL"),
    "situational": ("SITUATIONAL", "TECH_HUMOR"),
    "auto": None,
}

# gates — never add humour when these appear in the response
_NEVER_MARKERS = re.compile(
    r"\b(couldn'?t|could not|failed|failure|error|exception|traceback|"
    r"password|passwords|api ?key|secret|token|credit card|medical|legal|"
    r"financial|surgery|diagnos|shutdown|shutting down|kill|wipe|reformat|"
    r"uninstall|refus|denied|invalid|cannot|can'?t|not possible)\b",
    re.IGNORECASE)
_NEVER_STARTS = ("i need your confirmation", "which ", "i'm still waiting",
                 "i don't know what", "i couldn't", "i could not")
_ACTION_INTENTS = ("COMPUTER_ACTION", "APP_CONTROL", "COMMAND", "CODING",
                   "FILE_OPERATION", "SYSTEM_TASK", "REMINDER",
                   "MULTI_STEP_TASK", "WEB_RESEARCH")

_EMOJI = re.compile(r"[😏😎🙂🤖🚀✨]")

_PROB_ALLOWED = {"LOW": 0.25, "MEDIUM": 0.45, "HIGH": 0.7}
_PROB_OPTIONAL = {"LOW": 0.08, "MEDIUM": 0.18, "HIGH": 0.35}


class ConversationalHumor:
    def __init__(self, brain_config=None):
        self._cfg = brain_config
        self._personality = load_personality_config()
        self._lock = threading.Lock()
        self._used_lines: set[str] = set()
        self._turn = 0
        self._last_humor_turn = -100
        self._last_category: str | None = None

    # ── master switches ───────────────────────────────────────────────────
    def _agent_settings(self) -> dict:
        try:
            from agent_control.settings import get_settings
            return get_settings().snapshot()
        except Exception:
            return {}

    def enabled(self) -> bool:
        if not (self._personality.humor().get("enabled", True)):
            return False
        s = self._agent_settings()
        if s.get("professional_mode"):
            return False
        return s.get("humour_level", "OFF") != "OFF"

    def _level(self) -> str:
        """Effective intensity: personality humor.intensity if explicit,
        otherwise Agent Control humour_level (the single master knob)."""
        intensity = str(self._personality.humor().get("intensity", "auto"))
        if intensity.upper() in ("OFF", "LOW", "MEDIUM", "HIGH"):
            return intensity.upper()
        s = self._agent_settings()
        return s.get("humour_level", "MEDIUM")

    def _cooldown(self) -> int:
        try:
            return max(1, int(self._personality.humor().get("cooldown", 2)))
        except Exception:
            return 2

    # ── decision ──────────────────────────────────────────────────────────
    def decide(self, response, status: str = "", intent: str = "") -> str:
        """HUMOR_ALLOWED | HUMOR_OPTIONAL | HUMOR_NOT_APPROPRIATE."""
        if not self.enabled():
            return "HUMOR_NOT_APPROPRIATE"
        if self._level() == "OFF":
            return "HUMOR_NOT_APPROPRIATE"

        text = (response or "")
        if not text or len(text) < 6:
            return "HUMOR_NOT_APPROPRIATE"

        # control / failure / waiting states stay clean
        if status in ("FAILED", "STOPPED", "PAUSED", "WAITING_FOR_USER",
                      "IDLE"):
            return "HUMOR_NOT_APPROPRIATE"
        if intent in ("STOP", "PAUSE", "RESUME", "MEMORY"):
            return "HUMOR_NOT_APPROPRIATE"

        low = text.lower().strip()
        # questions to the user are never joked around
        if low.endswith("?") or low.startswith(_NEVER_STARTS):
            return "HUMOR_NOT_APPROPRIATE"
        # errors / sensitive topics / code / structured output
        if _NEVER_MARKERS.search(text):
            return "HUMOR_NOT_APPROPRIATE"
        if "```" in text or text.lstrip().startswith(("{", "[")):
            return "HUMOR_NOT_APPROPRIATE"
        if re.search(r"[✓⚠️❌]", text):
            return "HUMOR_NOT_APPROPRIATE"

        if status == "COMPLETED" and intent in _ACTION_INTENTS:
            return "HUMOR_ALLOWED"
        return "HUMOR_OPTIONAL"

    # ── generation ────────────────────────────────────────────────────────
    def generate(self, text: str, decision: str, app: str = "") -> str | None:
        level = self._level()
        prob = (_PROB_ALLOWED if decision == "HUMOR_ALLOWED"
                else _PROB_OPTIONAL).get(level, 0.0)
        if random.random() > prob:
            return None

        with self._lock:
            # cooldown: keep a real gap between remarks
            if self._turn - self._last_humor_turn < self._cooldown():
                return None

            category = self._pick_category(intent_hint=decision)
            pool = [l for l in _POOLS.get(category, []) if l not in
                    self._used_lines]
            if not pool:
                return None
            line = random.choice(pool)
            self._used_lines.add(line)
            if len(self._used_lines) > 40:
                self._used_lines = set(list(self._used_lines)[-24:])
            self._last_humor_turn = self._turn
            self._last_category = category

        try:
            line = line.format(app=app or "it")
        except Exception:
            line = line.replace("{app}", app or "it")
        if not self._personality.style().get("emoji", True):
            line = _EMOJI.sub("", line).strip()
        return line

    def _pick_category(self, intent_hint: str) -> str:
        style = str(self._personality.humor().get("style", "auto"))
        pref = _STYLE_PREFERENCE.get(style.lower())
        if pref:
            for c in pref:
                if c != self._last_category:
                    return c
            return pref[0]
        # auto: weight by intent context
        weights = [("TECH_HUMOR", 3), ("SITUATIONAL", 3), ("WITTY", 2),
                   ("DRY", 1), ("PLAYFUL", 1), ("SARCASTIC_LIGHT", 1)]
        total = sum(w for _, w in weights)
        r = random.uniform(0, total)
        acc = 0.0
        for cat, w in weights:
            acc += w
            if r <= acc and cat != self._last_category:
                return cat
        return "TECH_HUMOR"

    # ── response post-processor ───────────────────────────────────────────
    def postprocess(self, response, context=None, intent: str = "") -> None:
        """Append a short remark to a BrainResponse when appropriate.
        Never raises; never alters information content."""
        try:
            text = getattr(response, "text", None)
            if not text:
                return
            # Playbook hard rule: humour is 0/5 over distress and in
            # safety/privacy/high-stakes turns, whatever the master knob says.
            try:
                from personality.modes import is_distress, is_safety_sensitive
                user_text = str(getattr(context, "current_request", "") or "")
                if user_text and (is_distress(user_text)
                                  or is_safety_sensitive(user_text)):
                    return
            except Exception:
                pass
            status = getattr(response, "status", "") or ""
            with self._lock:
                self._turn += 1
            decision = self.decide(text, status, intent)
            if decision == "HUMOR_NOT_APPROPRIATE":
                return
            app = ""
            if context is not None:
                try:
                    app = context.references.get("last_app", "") or ""
                except Exception:
                    app = ""
            remark = self.generate(text, decision, app=app)
            if remark:
                response.text = text.rstrip() + " " + remark
        except Exception:
            pass
