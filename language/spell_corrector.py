"""
SPELL CORRECTOR — SymSpell-style dictionary correction, context-guarded.

Adapts the core SymSpell ideas (dictionary candidate scoring by edit distance
with a frequency prior and a strict safety threshold) into a local-only,
dependency-free module for Keys.ai.

The pipeline contract (spec): correction runs BEFORE intent resolution when
needed, but never blindly:
    * tokens inside protected terms (entity names, recent app/file references,
      glossary apps) are never corrected
    * title-cased tokens that look like proper nouns are left alone unless the
      best candidate is a known app name within edit distance 1
    * a correction is only applied when the best dictionary candidate wins by
      a clear margin (confidence >= threshold), so "open Vinayak" stays
      "Vinayak" even though some dictionary word is phonetically closer

After token correction, a multi-word alias pass maps "vs code" → "VS Code",
"file explorer" → "File Explorer", etc., so the router feeds canonical names
to open_app.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from language.dictionaries import APP_ALIASES, APP_NAMES, build_dictionary
from language.normalizer import normalize, strip_vowels


@dataclass
class Correction:
    original: str
    fixed: str
    confidence: float


@dataclass
class Corrected:
    text: str
    corrections: list = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.corrections)


def damerau_levenshtein(a: str, b: str, max_dist: int = 3) -> int:
    """Optimal-string-alignment edit distance with early exit."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > max_dist:
        return max_dist + 1
    prev2 = list(range(lb + 1))
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            v = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and \
                    a[i - 2] == b[j - 1]:
                v = min(v, prev2[j - 2] + 1)
            curr[j] = v
        prev2, prev = prev, curr
    return prev[lb]


class SpellCorrector:
    """Dictionary + frequency model. SymSpell-style candidate scoring."""

    def __init__(self, extra_words=(), extra_freq: dict | None = None):
        words, freq = build_dictionary()
        for w in extra_words or ():
            words.add(w.lower())
        if extra_freq:
            for w, f in extra_freq.items():
                freq[w] = max(freq.get(w, 0), f)
        self._words: set[str] = words
        self._freq: dict[str, int] = freq

    # ── API ───────────────────────────────────────────────────────────────
    def add(self, word: str, weight: int = 1) -> None:
        key = normalize(word)
        if len(key) >= 3:
            self._words.add(key)
            self._freq[key] = max(self._freq.get(key, 0), weight)

    def add_words(self, words) -> None:
        for w in words:
            self.add(w)

    def candidate(self, word: str) -> tuple[str, float]:
        """Best (fixed, confidence) for a single token. (word, 0.0) = no fix."""
        key = normalize(word)
        if not key or len(key) < 3:
            return word, 0.0
        if key in self._words:
            return word, 0.0
        best, best_score = None, float("inf")
        for cand in self._words:
            if abs(len(cand) - len(key)) > 2:
                continue
            d = damerau_levenshtein(key, cand, max_dist=3)
            if d > 2:
                continue
            # consonant-skeleton guard: reject far-field jumps (candidates
            # sharing almost no consonants with the typo). 'mesage'→'message'
            # shares m,s,g so it passes; 'vinayak'→'vintage' fails on distance
            # anyway, this is a secondary safety net.
            sk = strip_vowels(key)
            sc = strip_vowels(cand)
            if sk and sc and len(sk) >= 3 and len(sc) >= 3:
                common = set(sk) & set(sc)
                if len(common) < 2:
                    continue
            score = d * 10.0 - min(self._freq.get(cand, 1), 100) / 20.0
            # tie-break: prefer the candidate that is a prefix of the typo
            # ('prefere' → 'prefer', not 'prefers') and the shorter one
            # ('thsi' → 'this' over 'thine' at equal score).
            tie_wins = False
            if score == best_score and best is not None:
                prefix_wins = (key.startswith(cand) and
                               not key.startswith(best))
                shorter_wins = len(cand) < len(best)
                tie_wins = prefix_wins or shorter_wins
            if score < best_score or tie_wins:
                best_score = score
                best = cand
        if best is None:
            return word, 0.0
        conf = max(0.0, min(0.98, 1.0 - best_score / 26.0))
        if conf < 0.62:
            return word, 0.0
        return best, round(conf, 2)


class SmartCorrector:
    """Context-aware corrector: protects entities/apps/recent terms and
    applies the multi-word app-alias pass."""

    def __init__(self):
        self._core = SpellCorrector()
        self._protected: set[str] = set()   # normalized protected tokens
        for app in APP_NAMES:
            self._core.add(app, 10)

    # ── learning ──────────────────────────────────────────────────────────
    def learn_entity(self, word: str) -> None:
        norm = normalize(word)
        if norm and len(norm) >= 3:
            self._protected.add(norm)
            self._core.add(norm, 12)

    def learn_glossary(self, word: str) -> None:
        self._core.add(word, 6)

    # ── correction ────────────────────────────────────────────────────────
    # tokens sitting in a NAME position are never corrected to an unrelated
    # dictionary word: the receiver after messaging verbs, and the owner
    # before a possessive 's ("message kasim", "open rishab's repo").
    _NAME_VERBS = (r"message|email|call|text|tell|contact|ping|dm|whatsapp|"
                   r"remind|invite|notify")

    @classmethod
    def _name_position_tokens(cls, text: str) -> set:
        found = set()
        pat = re.compile(
            r"\b(?:" + cls._NAME_VERBS + r")\s+([^\W_]+)", re.IGNORECASE)
        for m in pat.finditer(text):
            n = normalize(m.group(1))
            if n and len(n) >= 3:
                found.add(n)
        pat2 = re.compile(r"([^\W_]+)['’]s\b", re.IGNORECASE)
        for m in pat2.finditer(text):
            n = normalize(m.group(1))
            if n and len(n) >= 3:
                found.add(n)
        return found

    def correct(self, text: str, protected_words=(),
                proper_guard: bool = True) -> Corrected:
        if not text:
            return Corrected(text)
        protect = set(self._protected)
        protect |= self._name_position_tokens(text)
        for pw in protected_words or ():
            n = normalize(pw)
            if n:
                protect.add(n)
                for part in n.split():
                    protect.add(part)

        corrections: list[Correction] = []
        # 0. alias-completion pass BEFORE token correction: "vs cod" → the
        # known phrase "vs code" should win over any single-word candidate
        text = self._alias_completion_pass(text, corrections)
        parts = re.split(r"([^\W_]+(?:['’][^\W_]+)?)", text)
        out = []
        for token in parts:
            if not re.fullmatch(r"[^\W_]+(?:['’][^\W_]+)?", token):
                out.append(token)
                continue
            bare = re.sub(r"['’]$", "", token)
            suffix = token[len(bare):]
            w = bare
            key = normalize(w)
            if not key or len(key) < 3 or key in self._words_fast():
                out.append(token)
                continue
            if key in protect:
                out.append(token)
                continue
            upper = w[0].isupper()
            # proper-noun guard: capitalized tokens stay untouched unless the
            # best candidate is an app name within distance 1
            fixed, conf = self._core.candidate(w)
            if fixed and fixed != key and conf >= 0.62:
                is_app = fixed in APP_NAMES
                # short tokens (3-4 chars) are only ever corrected to real
                # app names — correcting them to arbitrary words mangles
                # common terms like 'can'→'fan'
                if len(w) <= 4 and not is_app:
                    out.append(token)
                    continue
                if upper and not (is_app and conf >= 0.8):
                    out.append(token)
                    continue
                fixed_cased = fixed if is_app else (
                    fixed.title() if upper else fixed)
                out.append(fixed_cased + suffix)
                corrections.append(Correction(token, fixed_cased + suffix, conf))
            else:
                out.append(token)

        corrected = "".join(out)
        # multi-word alias pass (longest first)
        for alias in sorted(APP_ALIASES, key=len, reverse=True):
            pat = re.compile(r"(?<![A-Za-z])" + re.escape(alias) +
                             r"(?![A-Za-z])", re.IGNORECASE)
            if pat.search(corrected):
                corrected = pat.sub(APP_ALIASES[alias], corrected)
                corrections.append(Correction(alias, APP_ALIASES[alias], 1.0))
        return Corrected(corrected, corrections)

    @staticmethod
    def _alias_completion_pass(text: str, corrections: list) -> str:
        """Fuzzy multi-word alias completion: when the text contains a known
        alias prefix followed by a near-miss last word ("vs cod"), replace
        the whole phrase with the canonical display name ("VS Code")."""
        for alias in sorted((k for k in APP_ALIASES if len(k.split()) >= 2),
                            key=len, reverse=True):
            parts = alias.split()
            for cut in range(len(parts) - 1):
                head = " ".join(parts[:cut + 1])
                tail = parts[cut + 1]
                pat = re.compile(r"(?<![A-Za-z])" + re.escape(head) +
                                 r"\s+([^\W_]+)", re.IGNORECASE)
                for m in pat.finditer(text):
                    nxt = m.group(1)
                    if damerau_levenshtein(nxt.lower(), tail,
                                           max_dist=2) <= 2:
                        text = (text[:m.start()] + APP_ALIASES[alias] +
                                text[m.end():])
                        corrections.append(Correction(
                            f"{head} {nxt}", APP_ALIASES[alias], 0.95))
                        return text
        return text

    def _words_fast(self):
        return self._core._words
