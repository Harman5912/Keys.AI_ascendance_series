"""
PHONETICS — pronunciation-aware name matching (Metaphone-style, local-first).

Used by the entity resolver as a LAST-RESORT fallback: when a contact's
spelling is not understood (no exact / fuzzy edit-distance match), Keys.ai
finds people whose names SOUND like what the user typed and offers them as
options — e.g. "message Harmen" → "Did you mean 1) Harman Sadhwani ...?"

The encoder is a compact Metaphone variant adapted for Indic and global
name spellings: consonant digraphs (ph/bh/dh/gh/kh/th/sh/zh/ch) are folded
to their phonetic sound, common letter exchanges (v↔b, w↔v, z↔j, q→k, x→ks)
are normalised, vowels are dropped (including leading ones — the leading
letter is not preserved as an anchor), and doubled letters collapse.
Equal pronunciation → equal (or near-equal) keys.

No external dependencies; deterministic; never sends anything to an LLM.
"""

from __future__ import annotations

import re

# consonant digraphs → the sound they represent
_DIGRAPHS = {
    "ph": "f", "bh": "b", "dh": "d", "gh": "g", "kh": "k", "th": "t",
    "sh": "s", "zh": "z", "ch": "c", "ck": "k", "ng": "n",
}

# single letters → equivalent pronunciation sound
_SINGLES = {
    "v": "b",      # Verma/Berma
    "w": "v",      # Wani/Vani
    "z": "j",      # Zaheer/Jaheer
    "q": "k",
    "x": "ks",
    "c": "k",
    "y": "i",
}

_VOWELS = "aeiou"
_NON_ALPHA = re.compile(r"[^a-z]")


def phonetic_key(text: str, max_len: int = 6) -> str:
    """Return a compact pronunciation key for a name or word.

    Two names that sound alike produce identical or near-identical keys
    (compare with Damerau-Levenshtein distance <= 1 for fuzzy pronunciation
    matching). Empty input or all-symbol input yields "".
    """
    s = _NON_ALPHA.sub("", (text or "").lower())
    if not s:
        return ""
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        pair = s[i:i + 2]
        if pair in _DIGRAPHS:
            ch = _DIGRAPHS[pair]
            i += 2
        else:
            ch = s[i]
            i += 1
        if ch in _SINGLES:
            ch = _SINGLES[ch]
        if ch in _VOWELS:
            continue  # vowels after the leading consonant are dropped
        if out and ch == out[-1]:
            continue  # doubled letters collapse
        out.append(ch)
        if len(out) >= max_len:
            break
    return "".join(out)
