"""
NORMALIZER — input text normalization.

Prepares raw user input before intent resolution: case-folding, whitespace
control, optional unaccenting, punctuation guard and de-correction. Small and
deterministic — never rewrites semantics, only cleans the surface form.
"""

from __future__ import annotations

import re
import unicodedata

# Turkish-specific characters we may want to preserve vs fold.
_TR_MAP = str.maketrans(
    "çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def fold_turkish(text: str) -> str:
    """Fold Turkish case variants to ASCII-ish lowercase (for matching only)."""
    return (text or "").translate(_TR_MAP).lower()


def normalize(text: str, fold: bool = True) -> str:
    """Canonical normalized form used for pattern matching & entity lookup."""
    if not text:
        return ""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if not fold:
        return t.lower()
    t = t.lower()
    # Optionally drop accents (keep Turkish mapping — safer for names).
    t = "".join(ch for ch in unicodedata.normalize("NFKD", t)
                if not unicodedata.combining(ch))
    return t


def strip_vowels(word: str) -> str:
    """Consonant-skeleton, e.g. 'repositry' -> 'rpstr', 'repository' -> 'rpstr'.
    Robust to vowel-dropping typos."""
    return re.sub(r"[aeiouyAEIOUY]", "", word)


def is_misspelling_candidate(word: str) -> bool:
    """True when a token plausibly needs correction: >2 chars and not
    obviously a proper noun / code token / known short word."""
    if not word or len(word) < 3:
        return False
    if word.isdigit():
        return False
    if re.fullmatch(r"[a-z]{1,2}", word):
        return False
    return True
