"""
INTELLIGENCE CORE — the pre/post processing pipeline for the Keys.ai brain.

PRE-PROCESS (before intent resolution):
    RAW INPUT
      → normalize
      → entity pre-scan (protect names from the corrector)
      → spell correct (SymSpell-style, context-guarded)
      → entity resolve (BLINK-style mention → candidates → best match;
        ambiguity → ask)
      → semantic parse (surface text → meaning)
      → situation probe (active window → context references)
      → resolved text for intent classification + routing

POST-PROCESS (after a response is built):
      → conversational humour filter (context-aware, gated, cooldown)

Everything is deterministic, local-first and fully guarded: any failure inside
falls back to the original text, so the intelligence layer can never break the
existing brain pipeline.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

from language.normalizer import normalize
from personality import PersonalitySystem

# control-command typos the spell corrector refuses (short-token guard) but
# that MUST still stop / pause / resume the assistant
_CONTROL_TYPOS = {
    "stp": "stop", "stpo": "stop", "stopp": "stop",
    "paus": "pause", "pauz": "pause", "pausse": "pause",
    "contine": "continue", "contnue": "continue",
    "resme": "resume", "resum": "resume",
}


@dataclass
class PreparedInput:
    original: str = ""
    normalized: str = ""
    corrected: str = ""
    entities: list = field(default_factory=list)
    semantic: str = ""
    resolved: str = ""
    ask: str | None = None
    intent_hint: str = ""


class IntelligenceCore:
    def __init__(self, config, context=None, logger=None):
        self._config = config
        self._context = context
        self._logger = logger
        lang = config.get("language") if config else None
        lang = lang or {}
        self._enabled = bool(lang.get("enabled", True))
        self._spell_enabled = bool(lang.get("spell", True))
        self._entity_enabled = bool(lang.get("entities", True))
        self._semantic_enabled = bool(lang.get("semantic", True))
        self._situation_enabled = bool(lang.get("situation", True))

        self._spell = None
        self._entities = None
        self._semantic = None
        if self._enabled:
            self._build_components()
        self._personality = PersonalitySystem(config)
        self._situation_cache: tuple = (0.0, None)
        self._last_prepared: PreparedInput | None = None
        # pending entity clarification ("Which Rahul — Sharma or Verma?") so
        # the user's follow-up answer ("Sharma") can complete the request
        self._pending_ask: dict | None = None

    def is_enabled(self) -> bool:
        return self._enabled

    # ── construction (guarded) ────────────────────────────────────────────
    def _build_components(self) -> None:
        try:
            from language.spell_corrector import SmartCorrector
            self._spell = SmartCorrector()
        except Exception as e:
            print(f"[Intelligence] ⚠️ spell corrector disabled: {e}")
            self._spell = None
        try:
            from language.entity_resolver import EntityResolver
            self._entities = EntityResolver()
            if self._spell is not None:
                for w in self._entities.protected_words():
                    try:
                        self._spell.learn_entity(w)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Intelligence] ⚠️ entity resolver disabled: {e}")
            self._entities = None
        try:
            from language.semantic_parser import SemanticParser
            self._semantic = SemanticParser()
        except Exception as e:
            print(f"[Intelligence] ⚠️ semantic parser disabled: {e}")
            self._semantic = None

    # ── pre-process ───────────────────────────────────────────────────────
    def preprocess(self, text: str) -> PreparedInput:
        user_text = (text or "").strip()
        if not self._enabled:
            return PreparedInput(original=user_text, resolved=user_text)
        try:
            # 0. follow-up answer to a pending clarification ("Sharma" after
            # "Which Rahul?") — rebuild the original request with the full
            # name and continue the pipeline on it.
            original = user_text
            if self._pending_ask is not None:
                rebuilt = self._resolve_followup(original)
                self._pending_ask = None
                if rebuilt:
                    original = rebuilt

            normalized = original
            protect: list[str] = []
            entities = []

            # 1. entity pre-scan → protection list for the corrector.
            # The scanned MENTION span (e.g. "sadhwni") is protected too, so
            # the spell corrector leaves the misspelled name alone and the
            # entity resolver's fuzzy path can resolve it.
            if self._entity_enabled and self._entities is not None:
                try:
                    for m in self._entities.scan(normalized):
                        protect.append(m.entity.name)
                        if m.mention:
                            protect.append(m.mention)
                except Exception:
                    pass

            # 2. spell correction (protected terms never corrected)
            corrected = normalized
            if self._spell_enabled and self._spell is not None:
                try:
                    corrected = self._spell.correct(
                        normalized, protected_words=protect).text
                except Exception:
                    corrected = normalized

            # 3. entity resolution (canonical substitution + ambiguity ask)
            ask: str | None = None
            new_text = corrected
            if self._entity_enabled and self._entities is not None:
                try:
                    res = self._entities.resolve(corrected)
                    if res.ask:
                        ask = res.ask
                        # remember the pending clarification so a follow-up
                        # answer ("Sharma") completes the original request
                        if res.ask_candidates:
                            self._pending_ask = {
                                "original": user_text,
                                "mention": res.ask_mention,
                                "candidates": res.ask_candidates,
                            }
                    else:
                        new_text = res.text
                        entities = res.matches
                        self._note_entity_references(entities)
                except Exception:
                    pass

            # 4. semantic parse (surface → meaning)
            semantic, hint = new_text, ""
            if self._semantic_enabled and self._semantic is not None:
                try:
                    sp = self._semantic.parse(new_text, entities=entities,
                                              context=self._context)
                    semantic = sp.semantic or new_text
                    hint = sp.intent_hint
                    if sp.ask and not ask:
                        ask = sp.ask
                except Exception:
                    semantic = new_text

            # 5. situation probe (active window → context, cached)
            if self._situation_enabled:
                try:
                    self._probe_situation()
                except Exception:
                    pass

            self._last_prepared = PreparedInput(
                original=user_text, normalized=normalized,
                corrected=corrected, entities=entities, semantic=semantic,
                resolved=semantic, ask=ask, intent_hint=hint)
            return self._last_prepared
        except Exception as e:
            if self._logger is not None:
                try:
                    self._logger.event("INTEL", f"preprocess fallback: {e}")
                except Exception:
                    pass
            return PreparedInput(original=user_text, resolved=user_text)

    # ── clarification follow-up (BLINK-style disambiguation completion) ──
    _ORDINALS = {"first": 0, "second": 1, "third": 2, "fourth": 3,
                 "1st": 0, "2nd": 1, "3rd": 2, "4th": 3,
                 "the first": 0, "the second": 1, "the third": 2,
                 "the last": -1}

    def _resolve_followup(self, answer: str) -> str | None:
        """Map a user's short answer onto the pending ambiguous mention and
        rebuild the full request. Accepts: a numbered pick ("1", "2nd",
        "first", "the second one"), an exact full name, or any name part
        that uniquely identifies one candidate. Returns None when the answer
        doesn't resolve uniquely."""
        pa = self._pending_ask
        if not pa or not pa.get("candidates"):
            return None
        a = normalize(answer)
        if not a:
            return None
        cands = pa["candidates"]

        # ── numbered / ordinal pick: "1", "2nd", "first one", "the last"
        for key, idx in self._ORDINALS.items():
            if a == key or a == key + " one" or a == "the " + key + " one":
                if idx == -1:
                    idx = len(cands) - 1
                if 0 <= idx < len(cands):
                    return self._rebuild_request(pa, cands[idx])
                return None
        if a.isdigit():
            idx = int(a) - 1
            if 0 <= idx < len(cands):
                return self._rebuild_request(pa, cands[idx])
            return None

        # exact full-name match
        for c in cands:
            if normalize(c) == a:
                return self._rebuild_request(pa, c)

        # any name-part match (first / middle / last) that uniquely
        # identifies one candidate
        tokens = [t for t in a.split() if len(t) >= 3]
        if tokens:
            matches = []
            for c in cands:
                parts = normalize(c).split()
                if not parts:
                    continue
                if any(t in parts for t in tokens):
                    matches.append(c)
            if len(matches) == 1:
                return self._rebuild_request(pa, matches[0])
        return None

    @staticmethod
    def _rebuild_request(pa: dict, candidate: str) -> str:
        original = pa.get("original", "")
        mention = pa.get("mention", "")
        if mention and mention.lower() in original.lower():
            idx = original.lower().find(mention.lower())
            return (original[:idx] + candidate +
                    original[idx + len(mention):])
        return f"{original} {candidate}".strip()

    # ── control-word typos (stop / pause / resume) ────────────────────────
    def control_correct(self, text: str) -> str:
        """Correct typo'd control commands so "stp" really stops the
        assistant. Short fast-path only; falls back to the spell corrector."""
        if not self._enabled or not text:
            return text
        t = text.strip()
        low = t.lower()
        if low in _CONTROL_TYPOS:
            return _CONTROL_TYPOS[low]
        if len(t.split()) <= 5:
            first = low.split(" ", 1)[0]
            if first in _CONTROL_TYPOS:
                return _CONTROL_TYPOS[first] + t[len(first):]
            if self._spell is not None:
                try:
                    return self._spell.correct(t).text
                except Exception:
                    return text
        return text

    def _note_entity_references(self, matches) -> None:
        if self._context is None:
            return
        try:
            for m in matches:
                kind = m.entity.category
                if kind == "people":
                    kind = "person"
                elif kind == "projects":
                    kind = "project"
                self._context.note_reference(kind, m.entity.name)
        except Exception:
            pass

    # ── situation awareness (conservative, cached) ────────────────────────
    def _probe_situation(self) -> None:
        now = time.monotonic()
        if now - self._situation_cache[0] < 10.0:
            return
        self._situation_cache = (now, None)
        if sys.platform != "win32":
            return
        title = ""
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            title = (buf.value or "").strip()
        except Exception:
            return
        if not title or self._context is None:
            return
        try:
            if not self._context.references.get("last_window"):
                self._context.note_reference("window", title)
            if not self._context.references.get("last_app"):
                guess = self._guess_app(title)
                if guess:
                    self._context.note_reference("app", guess)
        except Exception:
            pass

    @staticmethod
    def _guess_app(title: str) -> str | None:
        from language.dictionaries import APP_ALIASES
        tl = title.lower()
        for frag, canonical in (("google chrome", "Chrome"),
                                ("whatsapp", "WhatsApp"),
                                ("telegram", "Telegram"),
                                ("discord", "Discord"),
                                ("spotify", "Spotify"),
                                ("netflix", "Netflix"),
                                ("youtube", "YouTube"),
                                ("visual studio code", "VS Code"),
                                ("code -", "VS Code"),
                                ("microsoft word", "Word"),
                                ("microsoft excel", "Excel"),
                                ("powerpoint", "PowerPoint"),
                                ("notepad", "Notepad"),
                                ("outlook", "Outlook"),
                                ("slack", "Slack"),
                                ("zoom", "Zoom"),
                                ("microsoft teams", "Teams"),
                                ("file explorer", "File Explorer")):
            if frag in tl:
                return canonical
        return None

    # ── post-process ──────────────────────────────────────────────────────
    def postprocess(self, response, context=None, intent: str = "") -> None:
        """Apply the conversational humour filter (guarded, non-breaking)."""
        try:
            self._personality.humor.postprocess(response, context, intent)
        except Exception:
            pass

    def personality_block(self) -> str:
        try:
            return self._personality.system_block()
        except Exception:
            return ""
