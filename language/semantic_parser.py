"""
SEMANTIC PARSER — understand what the user MEANS, not just the surface text.

Example transforms (surface_text → semantic_meaning):
    "Can you get VS Code open?"            → "open VS Code"
    "Why don't you open VS Code for me?"   → "open VS Code"
    "I need to work on ReviewBot"          → "open ReviewBot"
    "Please open Chrome"                   → "open Chrome"
    "Open my repository"                   → "open <last project>" (or ask)

Output:
    SemanticParse(semantic, intent_hint, entities, context_references,
                  required_action, ask)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class SemanticParse:
    semantic: str = ""                    # actionable meaning (or original)
    intent_hint: str = ""                 # OPEN_APPLICATION | WEB_SEARCH | ...
    required_action: str = ""             # e.g. "open VS Code"
    entities: list = field(default_factory=list)
    context_references: list = field(default_factory=list)
    ask: str | None = None                # clarification to surface to the user

    @property
    def meaning(self) -> str:
        return self.semantic


_ACTION_VERBS = ("open", "run", "start", "launch", "close", "shut down",
                 "restart", "stop", "type", "send", "play", "call", "show",
                 "tell me", "search", "scroll", "copy", "paste", "check",
                 "find", "create", "delete", "install", "uninstall",
                 "download", "read", "write", "edit", "fix", "set", "switch",
                 "turn", "mute", "unmute", "open the", "run the")

_INTENT_HINTS = {
    "open": "OPEN_APPLICATION", "launch": "OPEN_APPLICATION",
    "start": "OPEN_APPLICATION", "run": "RUN_APPLICATION",
    "send": "SEND_MESSAGE", "search": "WEB_SEARCH",
    "play": "PLAY_MEDIA",
    "create": "CREATE_FILE", "write": "WRITE_FILE", "edit": "EDIT_FILE",
    "fix": "FIX_CODE", "delete": "DELETE", "install": "INSTALL",
    "download": "DOWNLOAD", "read": "READ", "check": "CHECK",
    "set": "SET", "switch": "SWITCH", "close": "CLOSE_APP",
    "restart": "RESTART", "stop": "STOP_APP", "type": "TYPE",
    "show": "SHOW", "tell me": "TELL", "copy": "COPY", "paste": "PASTE",
    "scroll": "SCROLL", "find": "FIND", "mute": "MUTE", "unmute": "UNMUTE",
}


class SemanticParser:
    def parse(self, text: str, entities=None, context=None) -> SemanticParse:
        t = (text or "").strip()
        if not t:
            return SemanticParse(semantic=t)
        low = t.lower().strip()

        ask = None
        semantic, verb, obj = t, "", ""

        def rewrite(action: str, o: str):
            nonlocal semantic, verb, obj
            verb = action.strip()
            obj = o.strip().strip("?.").strip()
            semantic = f"{verb} {obj}".strip()
            if verb == "shut down":
                semantic = f"shutdown {obj}"
            elif verb == "tell me":
                semantic = f"tell {obj}"

        # ── 1. polite "can you get X open?" ───────────────────────────────
        m = re.match(r"^(?:can|could|would|will|do you think you can)\s+"
                     r"(?:you\s+)?(?:please\s+)?(?:get|make|have)\s+"
                     r"(.+?)\s+(?:open|opened|launch|launched|start|started|"
                     r"running|up)\s*\??$", low)
        if m:
            rewrite("open", _original_case(t, m.group(1).strip()))

        # ── 2. polite "can you open X?" ───────────────────────────────────
        if not semantic or semantic == t:
            m = re.match(r"^(?:can|could|would|will|do you think you can)\s+"
                         r"(?:you\s+)?(?:please\s+)?(" +
                         "|".join(_ACTION_VERBS) +
                         r")\s+(.+?)\s*\??$", low)
            if m:
                rewrite(m.group(1), _original_case(t, m.group(2).strip()))

        # ── 3. "why don't you open X?" ────────────────────────────────────
        if not semantic or semantic == t:
            m = re.match(r"^why (?:don'?t|dont|not|wouldn'?t) you\s+(" +
                         "|".join(_ACTION_VERBS) + r")\s+(.+?)\s*\??$", low)
            if m:
                rewrite(m.group(1), _original_case(t, m.group(2).strip()))

        # ── 4. "i need to / want to work on X" ────────────────────────────
        if not semantic or semantic == t:
            m = re.match(r"^i (?:need to|want to|would like to|'?d like to|"
                         r"wanna|am going to|'?m going to)\s+(?:you\s+)?(" +
                         "|".join(_ACTION_VERBS) + r")\s+(.+?)\s*$", low)
            if m:
                rewrite(m.group(1), _original_case(t, m.group(2).strip()))

        # ── 5. "i need to work on X" / "i'm working on X" → open X ────────
        if not semantic or semantic == t:
            m = re.match(r"^i (?:need to|want to|would like to)\s+work on\s+"
                         r"(.+?)\s*$", low)
            if m:
                rewrite("open", _original_case(t, m.group(1).strip()))

        # ── 6. "please / pls / plz open X" ────────────────────────────────
        if not semantic or semantic == t:
            m = re.match(r"^(?:please|pls|plz)\s+(.+?)\s*$", low)
            if m:
                semantic = _original_case(t, m.group(1).strip())

        # ── 7. "i want you to X" / "would you mind X-ing" / "do me a favor" ─
        if not semantic or semantic == t:
            m = re.match(r"^i want you to\s+(.+?)\s*$", low)
            if m:
                semantic = _original_case(t, m.group(1).strip())
        if not semantic or semantic == t:
            m = re.match(r"^would you mind\s+(.+?)\s*$", low)
            if m:
                v = _original_case(t, m.group(1).strip())
                v = re.sub(r"\b(\w+)ing\b", lambda mm: mm.group(1), v)
                semantic = v
        if not semantic or semantic == t:
            m = re.match(r"^do me a favor and\s+(.+?)\s*$", low)
            if m:
                semantic = _original_case(t, m.group(1).strip())

        # ── 8. "open my/the repository/project" → context or ask ──────────
        if not semantic or semantic == t:
            m = re.match(r"^(?:open|launch|start)\s+(?:my|the|this)\s+"
                         r"(?:repo|repository|project)\s*$", low)
            if m:
                ref = context_reference(context, ("last_project",
                                                  "last_file"))
                if ref:
                    semantic = f"open {ref[1]}"
                else:
                    semantic = t
                    ask = ("I don't know which project you mean yet — tell "
                           "me the project name and I'll open it.")

        # ── 8b. "open <name>'s repo/project" → project entity or keep ────
        if not semantic or semantic == t:
            m = re.match(r"^(?:open|launch|start)\s+(.+?)'s\s+(?:repo|"
                         r"repository|project)\s*$", low)
            if m:
                name = _original_case(t, m.group(1).strip())
                project = _project_entity(name, entities)
                if project:
                    semantic = f"open {project}"
                # else: leave the text untouched (not a known project)

        # ── 9. "make it work" / "get it working" ──────────────────────────
        if not semantic or semantic == t:
            m = re.match(r"^(?:make|get)\s+it\s+(?:to\s+)?work(?:ing)?\s*$",
                         low)
            if m:
                ref = context_reference(context, ("last_project", "last_file",
                                                  "last_app"))
                if ref:
                    semantic = f"run {ref[1]}"
                else:
                    semantic = t
                    ask = ("I don't know what 'it' is yet — point me at the "
                           "file or project and I'll run it.")

        # ── trailing politeness ───────────────────────────────────────────
        semantic = re.sub(r"\s+(?:please|if you don'?t mind|when you get a "
                          r"chance)\s*$", "", semantic, flags=re.IGNORECASE)

        hint = _INTENT_HINTS.get(verb.split()[0] if verb else "", "")
        return SemanticParse(
            semantic=semantic, intent_hint=hint,
            required_action=f"{verb} {obj}".strip(),
            entities=[e.to_dict() if hasattr(e, "to_dict") else e
                      for e in (entities or [])],
            context_references=context_references(context),
            ask=ask)


def _project_entity(name: str, entities) -> str | None:
    """Return the canonical project name when `name` matches a project entity
    (case-insensitive, prefix or fuzzy), else None."""
    if not entities:
        return None
    low_name = name.lower().strip()
    for e in entities:
        e = e.to_dict() if hasattr(e, "to_dict") else e
        if isinstance(e, dict) and e.get("category") == "projects":
            cand = e.get("name", "").lower()
            if low_name and (low_name == cand or
                             cand.startswith(low_name) or
                             low_name.startswith(cand)):
                return e["name"]
    return None


def context_reference(context, kinds):
    """Return (kind, value) for the first known reference, else None."""
    if context is None:
        return None
    try:
        refs = getattr(context, "references", {}) or {}
        for kind in kinds:
            val = refs.get(kind)
            if val:
                return kind, str(val)
    except Exception:
        pass
    return None


def context_references(context) -> list:
    if context is None:
        return []
    try:
        refs = getattr(context, "references", {}) or {}
        return [f"{k.replace('last_', '')}={v}" for k, v in refs.items()]
    except Exception:
        return []


def _original_case(text: str, token: str) -> str:
    if not token:
        return token
    idx = (text or "").lower().find(token.lower())
    if idx != -1:
        return text[idx:idx + len(token)]
    return token
