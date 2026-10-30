"""
DIALOGUE CORPUS — loads config/keysai_dialogue_corpus.json and retrieves a
handful of relevant examples for the prompt.

The corpus (146 original dialogues in 18 scenario families) is *calibration
material*: it shows the model the house style. It is never a pool of canned
replies — `format_examples()` says so explicitly in the prompt text it emits.

Design rules from the integration brief:
  * schema validation with helpful errors (CorpusError names the problem and
    where it was found);
  * a *small* relevant sample per turn (1-4 examples, default 3);
  * deterministic selection — the same turn gets the same examples, so
    prompts are reproducible and tests are stable;
  * indexes for intent / mode / language / risk are derived from the authored
    ids and text, never by rewriting the dialogue itself.

If the file is missing or malformed the corpus degrades to "no examples"
instead of breaking prompt assembly.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from personality.modes import MODE_PROFILES


class CorpusError(ValueError):
    """The corpus file exists but does not match the expected schema."""


def _base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def corpus_path() -> Path:
    return _base_dir() / "config" / "keysai_dialogue_corpus.json"


# ── schema validation ──────────────────────────────────────────────────────

_REQUIRED_TOP = ("title", "categories")
_REQUIRED_CATEGORY = ("id", "title", "examples")
_REQUIRED_EXAMPLE = ("id", "user", "assistant")


def _validate(data: object, source: Path) -> dict:
    where = source.name
    if not isinstance(data, dict):
        raise CorpusError(f"{where}: top level must be a JSON object, "
                          f"got {type(data).__name__}")
    for key in _REQUIRED_TOP:
        if key not in data:
            raise CorpusError(f"{where}: missing required key '{key}'")
    categories = data["categories"]
    if not isinstance(categories, list) or not categories:
        raise CorpusError(f"{where}: 'categories' must be a non-empty list")
    seen_ids: set[str] = set()
    for ci, category in enumerate(categories):
        if not isinstance(category, dict):
            raise CorpusError(f"{where}: categories[{ci}] must be an object")
        for key in _REQUIRED_CATEGORY:
            if key not in category:
                raise CorpusError(f"{where}: categories[{ci}] missing '{key}'")
        cid = str(category["id"])
        if cid in seen_ids:
            raise CorpusError(f"{where}: duplicate category id '{cid}'")
        seen_ids.add(cid)
        examples = category["examples"]
        if not isinstance(examples, list) or not examples:
            raise CorpusError(f"{where}: category '{cid}' has no examples")
        for ei, example in enumerate(examples):
            if not isinstance(example, dict):
                raise CorpusError(
                    f"{where}: '{cid}' examples[{ei}] must be an object")
            for key in _REQUIRED_EXAMPLE:
                value = example.get(key)
                if not isinstance(value, str) or not value.strip():
                    raise CorpusError(
                        f"{where}: '{cid}' examples[{ei}] needs a non-empty "
                        f"string '{key}'")
    return data


_cache: dict[str, dict] = {}


def load_corpus(path: Path | None = None, validate: bool = True) -> dict:
    """The validated corpus, cached per path. Empty dict when unavailable."""
    path = path or corpus_path()
    key = str(path)
    if key in _cache:
        return _cache[key]
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CorpusError(f"{path.name}: not valid JSON — {exc}") from exc
    if validate:
        data = _validate(data, path)
    _cache[key] = data
    return data


def clear_cache() -> None:
    _cache.clear()


# ── retrieval ──────────────────────────────────────────────────────────────

# Scenario-family id -> the modes that should see it.
_CATEGORY_MODES: dict[str, tuple[str, ...]] = {}
for _mode, _profile in MODE_PROFILES.items():
    for _cid in _profile["categories"]:
        _CATEGORY_MODES.setdefault(_cid, []).append(_mode)
_CATEGORY_MODES["11_failures_limits_and_honest_recovery"] = (
    "developer", "operator", "research", "coach")
_CATEGORY_MODES["12_memory_and_personalisation"] = ("companion", "focus")
_CATEGORY_MODES["14_privacy_permissions_and_boundaries"] = (
    "operator", "focus", "developer")

# English keyword overlap is the fallback relevance signal.
_WORD = re.compile(r"[a-z]{3,}")
_STOP = {"the", "and", "for", "you", "your", "this", "that", "with", "what",
         "how", "can", "please", "about", "into", "from", "should", "would"}


def _keywords(text: str) -> set[str]:
    return {w for w in _WORD.findall(str(text or "").lower()) if w not in _STOP}


def _score(example: dict, query: set[str]) -> int:
    # Match on the *user* line only: that is what the current turn resembles.
    return len(query & _keywords(example.get("user", "")))


# Romanised Hindi/Hinglish: the corpus writes Hindi in Latin script, so a
# script check alone would never match. Two independent signals: strong
# Hindi words, or the characteristic verb endings (-unga/-runga/-hunga).
_HI_WORDS = re.compile(
    r"\b(bilkul|haan|aap|aapka|zaroori|dhanyavad|theek|nahi|kaise|"
    r"namaste|samjhaunga|dunga|karo|karunga|hain|mein)\b", re.I)
_HI_ENDINGS = re.compile(r"\b\w*(?:unga|runga|hunga)\b", re.I)
_DEVANAGARI = re.compile(r"[\u0900-\u097f]")


def _language_of(example: dict) -> str:
    """'hi' for Hindi/Hinglish replies (Devanagari or Romanised), else 'en'."""
    answer = str(example.get("assistant", ""))
    if _DEVANAGARI.search(answer):
        return "hi"
    if len(_HI_WORDS.findall(answer)) >= 2 or _HI_ENDINGS.search(answer):
        return "hi"
    return "en"


def select_examples(text: str = "", mode: str = "", intent: str = "",
                    risk: str = "normal", language: str = "",
                    k: int = 3) -> list[dict]:
    """Up to k examples relevant to this turn. Deterministic.

    Filters, in order: mode (via scenario family), language (Hindi/Hinglish
    examples only when the user writes in one), risk class (high-risk turns
    get the boundary/confirmation families), then keyword overlap with the
    user's own words as the tie-breaker.
    """
    try:
        k = max(1, min(4, int(k)))
    except Exception:
        k = 3
    data = load_corpus()
    categories = data.get("categories") or []
    if not categories:
        return []

    candidates: list[tuple[int, dict]] = []
    query = _keywords(text)
    for category in categories:
        cid = str(category.get("id") or "")
        allowed = _CATEGORY_MODES.get(cid)
        mode_ok = (not mode) or (allowed is None or mode in allowed)
        for example in category.get("examples") or []:
            if not mode_ok:
                continue
            if language and _language_of(example) != language:
                continue
            score = _score(example, query)
            if mode and cid in (MODE_PROFILES.get(mode) or {}).get("categories", []):
                score += 2          # exact family for this mode
            if risk == "high" and "14_privacy" in cid:
                score += 3          # boundaries first when stakes are high
            if risk == "high" and "10_confirmed" in cid:
                score += 2
            candidates.append((score, example))

    # Deterministic: sort by score desc, then example id — no randomness.
    candidates.sort(key=lambda pair: (-pair[0], str(pair[1].get("id", ""))))
    picked: list[dict] = []
    seen: set[str] = set()
    for _, example in candidates:
        eid = str(example.get("id", ""))
        if eid in seen:
            continue
        seen.add(eid)
        picked.append(example)
        if len(picked) >= k:
            break
    return picked


def format_examples(examples: list[dict]) -> str:
    """Prompt block for the selected examples (calibration, never scripts)."""
    if not examples:
        return ""
    lines = ["STYLE EXAMPLES (calibration only — match this voice and "
             "honesty, never copy these lines verbatim):"]
    for example in examples:
        lines.append(f'- User: {example.get("user", "")}')
        lines.append(f'  KEYS.AI: {example.get("assistant", "")}')
    return "\n".join(lines)
