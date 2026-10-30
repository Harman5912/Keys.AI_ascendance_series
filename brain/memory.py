"""
Smart Brain memory layer (spec §7, §8).

Two levels:
  * short-term memory — lives in the ContextManager (conversation, task state)
  * long-term memory  — this layer, backed by the existing
                        memory/memory_manager.py JSON store (reused, not
                        duplicated).

Implements the memory DECISION (SAVE / DO NOT SAVE / UPDATE / FORGET):
the brain never auto-saves every conversation — decide_and_store() extracts
only genuinely useful facts using deterministic rules (optionally LLM-refined).
Extraction runs against the ORIGINAL user text (case preserved), so
"I prefer Python" stores "Python", not "python".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from brain.providers.base import parse_json


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


STOPWORDS = {
    "a", "an", "the", "to", "of", "in", "on", "at", "for", "with", "and",
    "or", "my", "i", "me", "it", "that", "this", "is", "are", "was", "were",
    "do", "does", "please", "can", "you", "your", "about", "from", "by",
    "as", "be", "have", "has", "will", "would", "should", "could", "etc",
}

# Letters allowed inside captured values (ASCII + Turkish, both cases).
_LETTERS = r"a-zA-ZğüşöçıĞÜŞÖÇİ"


class MemoryLayer:
    def __init__(self, enabled: bool = True, long_term: bool = True,
                 llm_extract: bool = False, provider=None,
                 memory_path: Path | None = None):
        self.enabled     = enabled
        self.long_term   = long_term
        self.llm_extract = llm_extract
        self.provider    = provider
        self._path       = memory_path

    # ── storage ──────────────────────────────────────────────────────────
    def _store(self):
        import memory.memory_manager as mm
        if self._path is not None:
            mm.MEMORY_PATH = self._path
        return mm

    def _memory(self) -> dict:
        if not self.enabled or not self.long_term:
            return {}
        return self._store().load_memory()

    def remember(self, key: str, value: str, category: str = "notes") -> str:
        if not self.enabled:
            return "Memory is disabled."
        if not key or not value:
            return "Nothing to remember."
        try:
            return self._store().remember(key, value, category)
        except Exception as e:
            print(f"[Brain][Memory] ⚠️ remember failed: {e}")
            return f"Could not save memory: {e}"

    def forget(self, key: str, category: str = "notes") -> str:
        if not self.enabled:
            return "Memory is disabled."
        try:
            return self._store().forget(key, category)
        except Exception as e:
            print(f"[Brain][Memory] ⚠️ forget failed: {e}")
            return f"Could not forget memory: {e}"

    # ── retrieval (spec §7 recall/search) ────────────────────────────────
    def search(self, query: str, top_k: int = 8) -> list[dict]:
        """Keyword-overlap search across all memory entries."""
        memory = self._memory()
        terms = [w for w in re.findall(r"[a-zA-Z0-9ığüşöçİĞÜŞÖÇ]+",
                                       (query or "").lower())
                 if w not in STOPWORDS and len(w) > 1]
        entries = []
        for cat, items in memory.items():
            if not isinstance(items, dict):
                continue
            for key, entry in items.items():
                if not isinstance(entry, dict):
                    continue
                val = str(entry.get("value", ""))
                hay = f"{cat} {key} {val}".lower()
                score = sum(1 for w in terms if w in hay)
                if score > 0:
                    entries.append({
                        "category": cat, "key": key, "value": val,
                        "score": score, "updated": entry.get("updated", ""),
                    })
        entries.sort(key=lambda e: (e["score"], e.get("updated", "")),
                     reverse=True)
        return entries[:top_k]

    def recall(self, query: str, top_k: int = 8) -> str:
        found = self.search(query, top_k=top_k)
        if not found:
            return ""
        lines = []
        for e in found:
            lines.append(f"- ({e['category']}/{e['key']}) {e['value']}")
        return "\n".join(lines)

    def format_for_prompt(self) -> str:
        return self._store().format_memory_for_prompt(self._memory())

    # ── memory decision (spec §7) ────────────────────────────────────────
    def decide_and_store(self, user_input: str,
                         assistant_response: str = "") -> dict:
        """Returns {"saved": [...], "updated": [...], "forgotten": [...],
        "handled": bool} — what was stored this turn (if anything)."""
        if not self.enabled:
            return {"saved": [], "updated": [], "forgotten": [], "handled": False}
        orig = (user_input or "").strip()
        low  = " " + orig.lower() + " "
        out  = {"saved": [], "updated": [], "forgotten": [], "handled": False}

        def _find(pattern: str):
            return re.search(pattern, orig, re.IGNORECASE)

        # ── forget ───────────────────────────────────────────────────────
        if re.search(r"\b(forget|remove from memory|unlearn)\b", low):
            m = re.search(r"\b(forget|remove from memory|unlearn)\s+"
                          r"(?:the\s+|my\s+)?(.{2,60}?)(?:\s*$|\.)", low)
            if m:
                target = m.group(2).strip().strip("?.")
                if "everything" in target or target in ("all", "all memory"):
                    # explicit clear-all — forget every stored entry
                    memory = self._memory()
                    for cat, items in list(memory.items()):
                        for key in list(items.keys()):
                            self.forget(key, cat)
                            out["forgotten"].append(f"{cat}/{key}")
                else:
                    hits = self.search(target, top_k=3)
                    for e in hits:
                        self.forget(e["key"], e["category"])
                        out["forgotten"].append(f"{e['category']}/{e['key']}")
                    if not hits:
                        memory = self._memory()
                        first = target.split()[0]
                        for cat, items in memory.items():
                            for key in list(items.keys()):
                                if first in key.lower() or \
                                        target in key.lower():
                                    self.forget(key, cat)
                                    out["forgotten"].append(f"{cat}/{key}")
            out["handled"] = bool(out["forgotten"])
            return out

        # ── identity ─────────────────────────────────────────────────────
        m = _find(r"\b(?:my name is|call me)\s+([a-zA-Z0-9" + _LETTERS +
                  r" \-']{2,40})(?:\s*$|[.,!?])")
        if m and ("my name is" in low or "call me" in low):
            self._store().remember("name", m.group(1).strip(), "identity")
            out["saved"].append("identity/name")
            out["handled"] = True

        m = _find(r"\b(?:i speak|my language is|my native language is|"
                  r"respond in|reply in)\s+([a-zA-Z0-9" + _LETTERS +
                  r" ]{2,30})(?:\s*$|[.,!?])")
        if m:
            self._store().remember("language", m.group(1).strip(), "identity")
            out["saved"].append("identity/language")
            out["handled"] = True

        m = _find(r"\bmy birthday (?:is|:)\s*([0-9/.\- ]{4,20})")
        if m:
            self._store().remember("birthday", m.group(1).strip(), "identity")
            out["saved"].append("identity/birthday")
            out["handled"] = True

        m = _find(r"\b(?:i am|i'm)\s+(\d{1,3})\s*(?:years? old|y/o)")
        if m:
            self._store().remember("age", m.group(1), "identity")
            out["saved"].append("identity/age")
            out["handled"] = True

        m = _find(r"\b(?:i live in|my city is|i'm from|i am from)\s+"
                  r"([a-zA-Z0-9" + _LETTERS + r" \-]{2,40})(?:\s*$|[.,!?])")
        if m:
            self._store().remember("city", m.group(1).strip(), "identity")
            out["saved"].append("identity/city")
            out["handled"] = True

        # ── preferences ──────────────────────────────────────────────────
        m = _find(r"\bmy favorite\s+([a-zA-Z0-9" + _LETTERS +
                  r" ]{1,30})\s+is\s+([a-zA-Z0-9" + _LETTERS +
                  r" ]{1,60})(?:\s*$|[.,!?])")
        if m:
            key = _slug(m.group(1))
            self._store().remember(f"favorite_{key}", m.group(2).strip(),
                                   "preferences")
            out["saved"].append(f"preferences/favorite_{key}")
            out["handled"] = True

        m = _find(r"\bi prefer\s+([a-zA-Z0-9" + _LETTERS +
                  r" ]{1,60})(?:\s*$|[.,!?])")
        if m:
            value = m.group(1).strip()
            self._store().remember(_slug(value) or "preference", value,
                                   "preferences")
            out["saved"].append("preferences/" + (_slug(value) or "preference"))
            out["handled"] = True

        m = _find(r"\b(?:i like|i love)\s+([a-zA-Z0-9" + _LETTERS +
                  r" ]{1,60})(?:\s*$|[.,!?])")
        if m:
            value = m.group(1).strip()
            self._store().remember(_slug(value) or "likes",
                                   "likes: " + value, "preferences")
            out["saved"].append("preferences/" + (_slug(value) or "likes"))
            out["handled"] = True

        m = _find(r"\bi (?:use|work with)\s+([a-zA-Z0-9" + _LETTERS +
                  r" ]{1,40})(?:\s*$|[.,!?])")
        if m:
            value = m.group(1).strip()
            self._store().remember(_slug(value) or "tool", value,
                                   "preferences")
            out["saved"].append("preferences/" + (_slug(value) or "tool"))
            out["handled"] = True

        # ── projects ─────────────────────────────────────────────────────
        m = _find(r"\b(?:i (?:am )?working on|my project (?:is|:)|i develop|"
                  r"i built)\s+([a-zA-Z0-9" + _LETTERS + r"_.\- ]{1,50})"
                  r"(?:\s*$|[.,!?])")
        if m:
            value = m.group(1).strip()
            self._store().remember(_slug(value) or "project", value,
                                   "projects")
            out["saved"].append("projects/" + (_slug(value) or "project"))
            out["handled"] = True

        # ── generic remember X (only when no specific rule already fired,
        # so "remember that I prefer Python" isn't saved twice) ──────────
        if not out["handled"]:
            m = re.search(r"\b(?:remember that|remember|don't forget|do not "
                          r"forget|always remember|keep in mind)\s+"
                          r"(?:that\s+)?(.{4,200})", low)
            if m:
                # re-map the captured span back to the original (cased)
                value = _original_case(orig, m.group(1)).strip().strip(".")
                if value:
                    key = _slug(value[:32]) or \
                        f"note_{len(self._memory().get('notes', {}))}"
                    self._store().remember(key, value, "notes")
                    out["saved"].append(f"notes/{key}")
                    out["handled"] = True

        # ── optional LLM extraction (off by default) ─────────────────────
        if out["handled"] or not self.provider or not self.llm_extract:
            return out
        try:
            prompt = (
                "Decide if the user said something worth remembering.\n"
                "Return JSON: {\"save\": true/false, \"category\": "
                "\"identity|preferences|projects|relationships|wishes|notes\", "
                "\"key\": \"short label\", \"value\": \"fact\"} "
                "or {\"save\": false}.\n"
                f"User: {user_input}"
            )
            obj = self.provider.structured_output(prompt)
            if isinstance(obj, dict) and obj.get("save"):
                self._store().remember(
                    str(obj.get("key", "note"))[:60],
                    str(obj.get("value", ""))[:380],
                    str(obj.get("category", "notes")))
                out["saved"].append(
                    f"{obj.get('category', 'notes')}/{obj.get('key', 'note')}")
                out["handled"] = True
        except Exception as e:
            print(f"[Brain][Memory] ⚠️ LLM extraction failed: {e}")
        return out


def _original_case(original: str, token: str) -> str:
    """Find `token` (case-insensitively) inside `original` and return the
    original-cased substring, so stored values keep the user's casing."""
    if not token:
        return token
    idx = original.lower().find(token.lower())
    if idx != -1:
        return original[idx:idx + len(token)]
    return token


def _slug(value: str) -> str:
    value = re.sub(r"[^a-zğüşöçı0-9]+", "_", value.lower()).strip("_")
    return value[:40]
