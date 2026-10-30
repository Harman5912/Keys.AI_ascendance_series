"""
Context engine (spec §6, §22, §23).

Combines:
  * current context  — the active request, current app/file/project, tool state
  * recent context   — recent conversation turns and tool outputs
  * long-term context — injected by the MemoryLayer (prompt-formatted)

Only relevant context is sent to the LLM. The manager also resolves
references and pronouns ("it", "that app", "the previous file", "run it")
against what the user last mentioned, so follow-up commands make sense.
"""

from __future__ import annotations

import json
import re
import sys
from collections import deque
from pathlib import Path


def _config_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "config"
    return Path(__file__).resolve().parent.parent / "config"


SESSION_STATE_PATH = _config_dir() / "session_state.json"

# noun kind → reference key (shared by the reference-resolution patterns)
_KIND_TO_REF = {
    "file": "last_file", "project": "last_project", "app": "last_app",
    "application": "last_app", "window": "last_window", "tab": "last_topic",
    "repo": "last_project", "repository": "last_project",
}


class ContextManager:
    def __init__(self, max_history: int = 12):
        self.max_history = max_history
        self.history: deque = deque(maxlen=max_history)   # {role, text}
        self.references: dict = {}     # last_app / last_file / last_project / ...
        self.tool_memory: dict = {}    # transient key/values from tools (set_context)
        self.current_request: str = ""

    # ── conversation history ─────────────────────────────────────────────
    def add_user(self, text: str) -> None:
        self.current_request = text
        self.history.append({"role": "user", "text": text})

    def add_assistant(self, text: str) -> None:
        if text:
            self.history.append({"role": "assistant", "text": text})

    def add_tool_result(self, tool: str, result: str) -> None:
        self.history.append({"role": "tool", "tool": tool,
                             "text": str(result)[:500]})

    # ── references (spec §23) ────────────────────────────────────────────
    def note_reference(self, kind: str, value: str) -> None:
        """kind: app | file | project | topic | window"""
        if value:
            self.references[f"last_{kind}"] = str(value)

    def remember_tool_value(self, key: str, value: str) -> None:
        if value:
            self.tool_memory[key] = str(value)

    def last_reference(self) -> str | None:
        for kind in ("file", "project", "app", "topic", "window"):
            val = self.references.get(f"last_{kind}")
            if val:
                return f"{kind}={val}"
        return None

    def resolve_references(self, text: str) -> str:
        """
        Rewrite pronouns / vague references using the last referenced item.
        Returns the (possibly rewritten) text and records what was resolved.
        """
        t = text.strip()
        noun = self.references.get("last_file") or \
               self.references.get("last_project") or \
               self.references.get("last_app") or \
               self.references.get("last_topic")

        # "run it", "open that", "fix this", "close it" ...
        m = re.match(
            r"^(open|run|start|launch|close|stop|fix|edit|type|send|check|"
            r"test|review|delete|remove)\s+(it|that|this|there)\s*$",
            t, re.IGNORECASE)
        if m:
            if noun:
                return f"{m.group(1)} {noun}"
            return t  # no reference known — caller decides

        # "the file from earlier" / "the project we were on" / "that app
        # we had open" — temporal follow-ups after the noun (verb-prefixed
        # and bare forms both resolve to the last known item). Runs BEFORE
        # the unanchored "previous|same|that|this" re.search below so the
        # temporal suffix isn't left dangling ("that app we had open" must
        # resolve to the app alone, not "app we had open").
        m = re.match(r"^(open|run|start|launch|close|stop|fix|edit|save|"
                     r"review|check|show)\s+(?:the|that|this|my)\s+" +
                     r"(file|project|app|application|repo|repository)" +
                     r"\s+(?:from\s+)?(?:earlier|before|last\s+time|we\s+"
                     r"were(?:\s+working(?:\s+on)?|\s+on)?|we\s+had"
                     r"(?:\s+open)?|we\s+used)(?:\s+earlier)?\s*$",
                     t, re.IGNORECASE)
        if m:
            val = self.references.get(_KIND_TO_REF.get(m.group(2)))
            if val:
                return f"{m.group(1)} {val}"
        m = re.match(r"^(?:the|that|this|my)\s+" +
                     r"(file|project|app|application|repo|repository)" +
                     r"\s+(?:from\s+)?(?:earlier|before|last\s+time|we\s+"
                     r"were(?:\s+working(?:\s+on)?|\s+on)?|we\s+had"
                     r"(?:\s+open)?|we\s+used)(?:\s+earlier)?\s*$",
                     t, re.IGNORECASE)
        if m:
            val = self.references.get(_KIND_TO_REF.get(m.group(1)))
            if val:
                return val

        # "the previous file" / "that file" / "same project" / "that app"
        if re.search(r"\b(previous|same|that|this)\s+(file|project|app|"
                     r"application|window|tab)\b", t, re.IGNORECASE):
            kind = re.search(
                r"\b(previous|same|that|this)\s+(file|project|app|"
                r"application|window|tab)\b", t, re.IGNORECASE).group(2)
            key = _KIND_TO_REF.get(kind)
            val = self.references.get(key) if key else None
            if val:
                return re.sub(
                    r"\b(previous|same|that|this)\s+(file|project|app|"
                    r"application|window|tab)\b",
                    val, t, flags=re.IGNORECASE)

        # "the project" / "my project" / "current project" / "the repo"
        # → last known project/app (situation-aware follow-ups)
        m = re.match(r"^(open|run|start|launch|close|stop|fix|build|test|"
                     r"save|review|check)\s+(?:the|my|this|current)\s+"
                     r"(?:project|repo|repository)\s*$",
                     t, re.IGNORECASE)
        if m:
            ref = self.references.get("last_project") or \
                self.references.get("last_app") or \
                self.references.get("last_file")
            if ref:
                return f"{m.group(1)} {ref}"

        # bare "it" / "that" mid-sentence when nothing else is concrete
        if noun and re.search(r"\b(it|that|this)\b", t, re.IGNORECASE) and \
           not re.search(r"\b(it's|that's|this is)\b", t, re.IGNORECASE):
            return re.sub(r"\b(it|that|this)\b", noun, t,
                          flags=re.IGNORECASE)
        return t

    # ── situation awareness ───────────────────────────────────────────────
    def note_situation(self, app: str | None = None,
                       window: str | None = None,
                       project: str | None = None) -> None:
        """Record the active application/window/project WITHOUT clobbering
        explicit references set by tools or the router (conservative)."""
        if app and not self.references.get("last_app"):
            self.note_reference("app", app)
        if window and not self.references.get("last_window"):
            self.note_reference("window", window)
        if project and not self.references.get("last_project"):
            self.note_reference("project", project)

    # ── session persistence (spec: "continue what we were doing") ────────
    def save_state(self, path: Path | None = None) -> None:
        """Persist references + tool memory (NOT raw conversation history,
        for privacy). Loaded again by a fresh ContextManager on restart."""
        try:
            path = path or SESSION_STATE_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps({
                "references": self.references,
                "tool_memory": dict(list(self.tool_memory.items())[:20]),
                "saved_at": __import__("time").time(),
            }, indent=2, ensure_ascii=False)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            import os as _os
            _os.replace(tmp, path)
        except Exception:
            pass

    def restore_state(self, path: Path | None = None) -> bool:
        """Restore references from a previous session. Returns True when any
        state was recovered."""
        try:
            path = path or SESSION_STATE_PATH
            if not path.exists():
                return False
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return False
            refs = data.get("references") or {}
            tm = data.get("tool_memory") or {}
            if isinstance(refs, dict):
                for k, v in refs.items():
                    self.references.setdefault(str(k), str(v))
            if isinstance(tm, dict):
                for k, v in list(tm.items())[:20]:
                    self.tool_memory.setdefault(str(k), str(v))
            return bool(refs or tm)
        except Exception:
            return False

    # ── snapshot for the LLM (short-term + injected long-term) ───────────
    def snapshot(self, long_term_text: str = "") -> str:
        lines = []

        if self.references:
            parts = []
            for kind in ("app", "file", "project", "window", "topic"):
                val = self.references.get(f"last_{kind}")
                if val:
                    parts.append(f"{kind}: {val}")
            if parts:
                lines.append("[RECENT REFERENCES] " + " | ".join(parts))

        if self.tool_memory:
            tm = "; ".join(f"{k}={v}" for k, v in
                           list(self.tool_memory.items())[:10])
            lines.append("[TOOL STATE] " + tm)

        if self.history:
            recent = list(self.history)[-6:]
            turns = []
            for item in recent:
                if item["role"] == "user":
                    turns.append(f"User: {item['text']}")
                elif item["role"] == "assistant":
                    turns.append(f"Keys.ai: {item['text'][:300]}")
                else:
                    turns.append(f"Tool {item.get('tool', '')}: "
                                 f"{item['text'][:200]}")
            lines.append("[RECENT CONVERSATION]\n" + "\n".join(turns))

        if long_term_text:
            lines.append(long_term_text.rstrip())

        return "\n\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "history": list(self.history),
            "references": dict(self.references),
            "tool_memory": dict(self.tool_memory),
        }

    def clear(self) -> None:
        self.history.clear()
        self.references.clear()
        self.tool_memory.clear()
