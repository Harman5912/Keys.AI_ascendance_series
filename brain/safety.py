"""
Tool safety & permission layer (spec §15, §16).

Permission levels:
    SAFE      — reads, screenshots, opening apps, searches  → auto-execute
    MODERATE  — edits, sending messages, installing packages → confirm (config)
    DANGEROUS — deletes, destructive shell, system changes, financial →
                always confirm (unless explicitly disabled in config)

Dangerous ACTION keywords (delete/remove/format/shutdown/...) escalate a
tool's level at runtime, so e.g. file_controller is DANGEROUS on 'delete'
even when the tool itself is listed as SAFE. The LLM can never bypass this.
"""

from __future__ import annotations

import re
from enum import Enum


class SafetyLevel(str, Enum):
    SAFE     = "SAFE"
    MODERATE = "MODERATE"
    DANGEROUS = "DANGEROUS"


class Decision(str, Enum):
    ALLOW = "ALLOW"      # execute immediately
    ASK   = "ASK"        # pause and ask the user first
    BLOCK = "BLOCK"      # refuse regardless


# Action-level escalation keywords (matched against the serialized arguments)
_DANGEROUS_ACTIONS = [
    "delete", "remove", "erase", "wipe", "rm ", "rmdir", "format", "partition",
    "shutdown", "restart", "reboot", "power off", "sleep", "hibernate",
    "uninstall", "registry", "reg add", "reg delete", "diskpart", "format ",
    "net user", "del /", "rd /", "taskkill /f", "reset this pc", "reinstall os",
    "overclock", "bios", "secure erase",
]
_MODERATE_ACTIONS = [
    "send", "submit", "post", "publish", "purchase", "buy", "pay", "order",
    "transfer", "install", "pip install", "npm install", "delete cookie",
    "clear browsing data", "sign out", "logout", "send email", "reply email",
]


class SafetyLayer:
    def __init__(self, config):
        perms = (config.get("permissions") if config else None) or {}
        self._level_map: dict[str, SafetyLevel] = {}
        for level in SafetyLevel:
            for tool in perms.get(level.value, []) or []:
                self._level_map[str(tool).lower()] = level
        self._blocked = set(str(t) for t in
                            ((config.get("blocked_tools") if config else None)
                             or []))

    def permission_for(self, tool: str, arguments: dict | None) -> SafetyLevel:
        t = (tool or "").lower()
        if t in self._blocked:
            return SafetyLevel.DANGEROUS
        level = self._level_map.get(t, SafetyLevel.MODERATE)
        arg_str = json_dumps(arguments or {}).lower()
        if any(k in arg_str for k in _DANGEROUS_ACTIONS):
            level = SafetyLevel.DANGEROUS
        elif level != SafetyLevel.DANGEROUS and \
                any(k in arg_str for k in _MODERATE_ACTIONS):
            level = SafetyLevel.MODERATE
        return level

    def decision(self, tool: str, arguments: dict | None, config=None) -> Decision:
        t = (tool or "").lower()
        if t in self._blocked:
            return Decision.BLOCK
        level = self.permission_for(tool, arguments)
        if level == SafetyLevel.SAFE:
            return Decision.ALLOW
        if level == SafetyLevel.MODERATE:
            confirm = bool(config.get("confirm_moderate", True)) if config else True
            return Decision.ASK if confirm else Decision.ALLOW
        # DANGEROUS
        confirm = bool(config.get("confirm_dangerous", True)) if config else True
        return Decision.ASK if confirm else Decision.ALLOW

    def needs_confirmation(self, tool: str, arguments: dict | None,
                           config=None) -> bool:
        return self.decision(tool, arguments, config) == Decision.ASK


def json_dumps(data) -> str:
    try:
        import json
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return str(data)
