"""KEYS.AI — risk-based permission policy for the coding agent.

The Crown Code bridge asks the app whether the agent may perform an action
(``permission_request`` events, and the app's own ``run_command`` path). Before
this module existed the answer was the literal ``True``: every request the model
made was approved by the code that was supposed to supervise it, so the agent
could approve its own file deletions, installs and shell commands.

The policy here is deliberately boring and deterministic:

    * the *app* decides, never the model — a request carries the tool name and
      its arguments, nothing that can be trusted as an approval;
    * reads and workspace-local writes are allowed without interrupting anyone;
    * installs, network access and commands that reach outside the workspace
      need a human;
    * destructive or credential-touching actions are refused even when a human
      callback is unavailable (fail closed), because a denied action must never
      silently execute through another path;
    * every decision carries a risk level and a human-readable reason, so the
      action log records *why* something ran.

Policy names come from ``config/crown_code.json`` and match the documented
``policy`` parameter of the ``crown_code`` tool:

    readonly  reads and searches only
    safe      reads, local writes, and ordinary build/test commands (default)
    all       everything except credential access and irreversible system
              destruction — the user has pre-authorised the disruptive tiers
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# ── risk tiers ────────────────────────────────────────────────────────────
LOW = "low"
MODERATE = "moderate"
HIGH = "high"
CRITICAL = "critical"

_ORDER = {LOW: 0, MODERATE: 1, HIGH: 2, CRITICAL: 3}

READONLY = "readonly"
SAFE = "safe"
ALL = "all"

_POLICIES = (READONLY, SAFE, ALL)


# ── tool families ─────────────────────────────────────────────────────────
_READ_TOOLS = {
    "read_file", "read", "view_file", "open_file", "list_files", "list_dir",
    "list_directory", "ls", "glob", "grep", "search", "search_files",
    "find_files", "inspect", "tree", "stat", "read_multiple_files",
    "code_search", "file_info",
}
_WRITE_TOOLS = {
    "write_file", "create_file", "edit_file", "apply_patch", "multi_edit",
    "replace_in_file", "append_file", "mkdir", "create_directory", "move_file",
    "rename_file", "copy_file",
}
_DELETE_TOOLS = {"delete_file", "remove_file", "rm", "rmdir", "delete_directory"}
_EXEC_TOOLS = {"terminal", "run_command", "shell", "bash", "exec", "execute",
               "execute_command", "run_shell"}
_NETWORK_TOOLS = {"fetch", "web_fetch", "http_request", "browse", "browser",
                  "download", "upload", "open_url"}

# Command fragments, checked on the lower-cased command text.
_DESTRUCTIVE = (
    r"\brm\s+-[a-z]*[rf]", r"\brm\s+-[a-z]*r", r"\brmdir\b", r"\bdel\s+/[sfq]",
    r"\bremove-item\b.*-recurse", r"\bformat\s+[a-z]:", r"\bmkfs\b",
    r"\bdiskpart\b", r"\bshutdown\b", r"\breboot\b",
    r"\breg\s+delete\b", r"\btaskkill\b", r"\bkillall\b", r"\bpkill\b",
    r"git\s+reset\s+--hard", r"git\s+clean\s+-[a-z]*f", r"git\s+push\s+--force",
    r"\bdrop\s+database\b", r"\btruncate\s+table\b", r">\s*/dev/sd",
    r"\bcipher\s+/w", r"\bvssadmin\b", r"\bbcdedit\b",
)
_INSTALLERS = (
    r"\bpip3?\s+install\b", r"\bpython\s+-m\s+pip\s+install\b",
    r"\bnpm\s+(install|i|ci|add)\b", r"\byarn\s+(add|install)\b",
    r"\bpnpm\s+(add|install)\b", r"\bnpx\b", r"\bwinget\s+install\b",
    r"\bchoco\s+install\b", r"\bscoop\s+install\b", r"\bapt(-get)?\s+install\b",
    r"\bbrew\s+install\b", r"\bcargo\s+install\b", r"\bgo\s+get\b",
    r"\bpoetry\s+add\b", r"\buv\s+(pip\s+)?add\b", r"\bdotnet\s+add\b",
    r"\bgem\s+install\b", r"\bcomposer\s+require\b",
)
_NETWORK = (
    r"\bcurl\b", r"\bwget\b", r"\binvoke-webrequest\b", r"\biwr\b",
    r"\bscp\b", r"\bsftp\b", r"\bssh\b", r"\btelnet\b", r"\bnc\s",
    r"\bftp\b", r"\bgit\s+(clone|fetch|pull|push)\b", r"\bdocker\s+(pull|push)\b",
)
# Reading or shipping a secret out of the machine.
_CREDENTIALS = (
    r"\.env\b", r"\bid_rsa\b", r"\bid_ed25519\b", r"\.pem\b", r"\.pfx\b",
    r"\bcredentials?\b", r"api_keys\.json", r"\bsecrets?\b", r"\.netrc\b",
    r"\bkeychain\b", r"\bconfig[/\\]certs\b", r"\btoken\.json\b",
    r"\bhistory\b.*\bcurl\b",
)
_ESCAPE = (
    r"(^|[\s;&|])\.\.([/\\]|$)", r"\bcd\s+\.\.", r"\bcd\s+/",
    r"\bcd\s+[a-z]:\\", r"\bpushd\s+\.\.",
)

_RX = {
    "destructive": [re.compile(p, re.I) for p in _DESTRUCTIVE],
    "install": [re.compile(p, re.I) for p in _INSTALLERS],
    "network": [re.compile(p, re.I) for p in _NETWORK],
    "credential": [re.compile(p, re.I) for p in _CREDENTIALS],
    "escape": [re.compile(p, re.I) for p in _ESCAPE],
}


def _match(kind: str, text: str) -> bool:
    return any(rx.search(text) for rx in _RX[kind])


# ── decision object ───────────────────────────────────────────────────────
@dataclass
class Decision:
    allow: bool
    risk: str = MODERATE
    reason: str = ""
    requires_approval: bool = False
    tool: str = ""
    target: str = ""
    command: str = ""
    redacted: dict = field(default_factory=dict)

    def describe(self) -> str:
        """One line for the approval card and the action log."""
        bits = [self.tool or "action"]
        if self.target:
            bits.append(self.target)
        if self.command:
            bits.append(f"$ {self.command[:160]}")
        return f"{' / '.join(bits)} — {self.reason}"

    def as_dict(self) -> dict:
        return {
            "allow": self.allow, "risk": self.risk, "reason": self.reason,
            "requires_approval": self.requires_approval,
            "tool": self.tool, "target": self.target,
        }


# ── helpers ───────────────────────────────────────────────────────────────
def _norm_policy(policy: str) -> str:
    p = (policy or SAFE).strip().lower()
    return p if p in _POLICIES else SAFE


def _param(event: dict, *names: str) -> str:
    """First non-empty string among ``names`` in event['input'] or the event."""
    src = event.get("input") if isinstance(event.get("input"), dict) else {}
    for bag in (src, event):
        for n in names:
            if not isinstance(bag, dict):
                continue
            v = bag.get(n)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def inside(path: str, workspace: str) -> bool:
    """True when ``path`` resolves inside ``workspace``.

    Resolves symlinks and ``..`` before comparing; a path that does not exist
    yet is compared on its normalised absolute form, so a write to
    ``ws/../../etc/passwd`` is still recognised as an escape.
    """
    if not path:
        return True
    try:
        ws = Path(workspace or ".").expanduser().resolve()
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = ws / p
        p = p.resolve() if p.exists() else Path(os.path.abspath(str(p)))
        ws = Path(os.path.abspath(str(ws)))
        return p == ws or ws in p.parents
    except Exception:
        return False            # unparseable path → treat as outside


def _absolute_target(event: dict, workspace: str) -> tuple[str, bool]:
    raw = _param(event, "path", "file", "file_path", "target", "dest",
                 "destination", "filename", "dir", "directory")
    if not raw:
        return "", True
    try:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = Path(workspace or ".") / p
        return str(p), inside(str(p), workspace)
    except Exception:
        return raw, False


def _command(event: dict) -> str:
    return _param(event, "command", "cmd", "script", "shell", "line")


# ── the policy ────────────────────────────────────────────────────────────
def classify(event: dict, *, workspace: str = "", policy: str = SAFE) -> Decision:
    """Risk-classify a permission request without calling any approver."""
    tool = str(event.get("tool") or event.get("name") or "").strip().lower()
    cmd = _command(event)
    target, in_ws = _absolute_target(event, workspace)
    pol = _norm_policy(policy)

    if not tool:
        return Decision(False, HIGH, "request named no tool", tool="", target=target)

    # 1. credential access is never allowed, at any policy level
    if tool in _READ_TOOLS and target and _match("credential", target):
        return Decision(False, CRITICAL, "reads a credential store", tool=tool, target=target)
    if cmd and _match("credential", cmd):
        return Decision(False, CRITICAL, "touches credentials or keys", tool=tool, command=cmd)

    # 2. read-only inspection
    if tool in _READ_TOOLS:
        if not in_ws:
            return Decision(False, HIGH, "reads outside the workspace",
                            requires_approval=True, tool=tool, target=target)
        return Decision(True, LOW, "read-only inspection", tool=tool, target=target)

    # 3. deletion — irreversible in or out of the workspace, so always the top
    # tier: an approved deletion of one file must not read as "safe" in the log.
    if tool in _DELETE_TOOLS:
        risk = CRITICAL if not in_ws else HIGH
        return Decision(False, risk, "deletes files or is irreversible",
                        requires_approval=True, tool=tool, target=target, command=cmd)

    # 4. shell execution
    if tool in _EXEC_TOOLS or cmd:
        if _match("destructive", cmd):
            return Decision(False, CRITICAL, "destructive or irreversible shell command",
                            requires_approval=True, tool=tool, command=cmd)
        if _match("escape", cmd) or (target and not in_ws):
            return Decision(False, HIGH, "reaches outside the workspace",
                            requires_approval=True, tool=tool, target=target, command=cmd)
        if _match("install", cmd):
            return Decision(pol == ALL, HIGH, "installs packages",
                            requires_approval=pol != ALL, tool=tool, command=cmd)
        if _match("network", cmd):
            return Decision(pol == ALL, HIGH, "uses the network",
                            requires_approval=pol != ALL, tool=tool, command=cmd)
        if pol == READONLY:
            return Decision(False, MODERATE, "policy is read-only", tool=tool, command=cmd)
        return Decision(True, MODERATE, "build/test command inside the workspace",
                        tool=tool, command=cmd)

    # 5. network-ish tools
    if tool in _NETWORK_TOOLS:
        return Decision(pol == ALL, HIGH, "uses the network",
                        requires_approval=pol != ALL, tool=tool, target=target)

    # 6. writes
    if tool in _WRITE_TOOLS:
        if not in_ws:
            return Decision(False, CRITICAL, "writes outside the workspace",
                            requires_approval=True, tool=tool, target=target)
        if pol == READONLY:
            return Decision(False, MODERATE, "policy is read-only", tool=tool, target=target)
        return Decision(True, MODERATE, "writes inside the workspace",
                        tool=tool, target=target)

    # 7. unknown tool: a new tool must be reviewed before it runs unattended
    if pol == ALL:
        return Decision(True, MODERATE, "unclassified tool, policy allows", tool=tool,
                        target=target)
    return Decision(False, MODERATE, "unclassified tool", requires_approval=True,
                    tool=tool, target=target)


def evaluate(event: dict, *, workspace: str = "", policy: str = SAFE,
             approve=None, session_allows=None) -> Decision:
    """Classify and, when the tier needs it, ask the human.

    ``approve`` is called as ``approve(decision) -> str|bool`` and must return
    ``"allow_once"``, ``"allow_task"``, ``"deny"`` or a boolean. Absent or
    raising approvers deny — the coding agent must not gain privileges from the
    failure of the interface that supervises it.
    """
    decision = classify(event, workspace=workspace, policy=policy)
    if decision.allow or not decision.requires_approval:
        return decision

    tool = decision.tool
    if session_allows is not None and tool and tool in session_allows:
        decision.allow = True
        decision.requires_approval = False
        decision.reason += " (approved for this task)"
        return decision

    if approve is None:
        decision.reason += " — no approval interface, so denied"
        return decision

    try:
        answer = approve(decision)
    except Exception as exc:                        # pragma: no cover - defensive
        decision.reason += f" — approver failed ({type(exc).__name__}), denied"
        return decision

    granted = False
    if isinstance(answer, bool):
        granted = answer
    elif isinstance(answer, str):
        granted = answer.strip().lower() in ("allow_once", "allow_task", "allow",
                                             "yes", "y", "true", "approved")
        if answer.strip().lower() == "allow_task" and session_allows is not None and tool:
            session_allows.add(tool)
    if granted:
        decision.allow = True
        decision.requires_approval = False
        decision.reason += " — approved by the user"
    else:
        decision.reason += " — denied by the user"
    return decision


def allows_command(command: str, *, workspace: str = "", policy: str = SAFE) -> Decision:
    """Classify a shell command the app is about to run itself."""
    return classify({"tool": "run_command", "command": command}, workspace=workspace,
                    policy=policy)


__all__ = ["Decision", "classify", "evaluate", "allows_command", "inside",
           "LOW", "MODERATE", "HIGH", "CRITICAL", "READONLY", "SAFE", "ALL"]
