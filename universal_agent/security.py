"""Security primitives for the Universal Project Agent.

Everything a model or a request asks for is treated as untrusted: paths,
filenames, output locations and external URLs all pass through this module
before a tool touches disk or the network.

The rules are deliberately simple and testable:

* a task may write only inside its own workspace; the only read access outside
  it is an explicit user-supplied input file, which is never modified;
* ``..`` segments, absolute paths and symlinks that escape the workspace are
  rejected after resolution, not by string inspection;
* deletions and replacing an existing file require an approval decision;
* audit lines and error text are scrubbed of credential-shaped strings.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

MAX_FILENAME = 80
MAX_INPUT_BYTES = 50 * 1024 * 1024          # 50 MB for a supplied input file
ALLOWED_ARTIFACT_SUFFIXES = {
    ".md", ".txt", ".json", ".csv", ".html", ".pdf", ".docx", ".pptx",
    ".xlsx", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".py", ".js", ".ts",
    ".tsx", ".jsx", ".css", ".zip", ".log", ".yaml", ".yml", ".toml",
}


class SecurityError(PermissionError):
    """A path or action was refused. The message is user-facing."""


def _resolved(path) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except Exception as exc:
        raise SecurityError(f"Invalid path: {exc}") from exc


def is_within(path, root) -> bool:
    p, r = _resolved(path), _resolved(root)
    return p == r or r in p.parents


def resolve_within(root, candidate, *, must_exist: bool = False) -> Path:
    """Resolve ``candidate`` and refuse anything outside ``root``."""
    root_p = _resolved(root)
    target = _resolved(candidate)
    if target != root_p and root_p not in target.parents:
        raise SecurityError(
            f"Refused: '{target.name}' resolves outside the task workspace.")
    if must_exist and not target.exists():
        raise SecurityError(f"Path does not exist: {target.name}")
    return target


def safe_filename(name: str, default: str = "output", suffix: str = "") -> str:
    """A single, portable filename with no directories and no control chars."""
    raw = str(name or "").strip()
    raw = os.path.basename(raw.replace("\\", "/"))
    raw = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "", raw)
    raw = raw.strip(". ")
    if suffix and not raw.lower().endswith(suffix.lower()):
        raw = f"{raw}{suffix}" if raw else f"{default}{suffix}"
    if not raw:
        raw = f"{default}{suffix}"
    if len(raw) > MAX_FILENAME:
        stem, dot, ext = raw.rpartition(".")
        if dot and len(ext) <= 8:
            raw = f"{stem[:MAX_FILENAME - len(ext) - 1]}.{ext}"
        else:
            raw = raw[:MAX_FILENAME]
    return raw


def unique_path(directory: Path, filename: str) -> Path:
    """Never overwrite: append -2, -3 … when the name is taken."""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / safe_filename(filename)
    n = 1
    while candidate.exists():
        n += 1
        stem = candidate.stem
        base = re.sub(r"-\d+$", "", stem)
        candidate = directory / f"{base}-{n}{candidate.suffix}"
    return candidate


def validate_input_file(path) -> Path:
    """A user-supplied read-only input: exists, reasonable size, safe suffix."""
    p = _resolved(path)
    if not p.is_file():
        raise SecurityError(f"Input file not found: {p.name}")
    size = p.stat().st_size
    if size <= 0:
        raise SecurityError(f"Input file is empty: {p.name}")
    if size > MAX_INPUT_BYTES:
        raise SecurityError(
            f"Input file is {size / 1e6:.1f} MB — the limit is "
            f"{MAX_INPUT_BYTES / 1e6:.0f} MB.")
    if p.suffix.lower() not in ALLOWED_ARTIFACT_SUFFIXES:
        raise SecurityError(f"Unsupported input type: {p.suffix or 'no extension'}")
    return p


def validate_output_suffix(path, allowed=None) -> Path:
    p = Path(path)
    allowed = allowed or ALLOWED_ARTIFACT_SUFFIXES
    if p.suffix.lower() not in allowed:
        raise SecurityError(f"Refusing to write unsupported file type: {p.suffix}")
    return p


def sha256_file(path: Path, limit: int | None = None) -> str:
    h = hashlib.sha256()
    read = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 256)
            if not chunk:
                break
            h.update(chunk)
            read += len(chunk)
            if limit and read >= limit:
                break
    return h.hexdigest()


def requires_approval(action: str, *, destructive: bool = False,
                      external: bool = False) -> bool:
    """Which actions need the user's explicit decision.

    Creating a new file in the task workspace does not; deleting, overwriting
    an existing file or performing an externally visible action does.
    """
    return bool(destructive or external or str(action).lower() in {
        "delete", "overwrite", "publish", "purchase", "send", "submit",
        "modify-account",
    })


_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\bnvapi-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"\bghp_[0-9A-Za-z]{20,}"),
    re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[=:]\s*[^\s,;]{6,}"),
]


def redact_secrets(text: str) -> str:
    """Remove credential-shaped substrings from logs, reports and errors."""
    out = str(text or "")
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(lambda m: (
            f"{m.group(1)}=***" if m.groups() else "***REDACTED***"), out)
    return out


def audit_line(action: str, detail: str = "", outcome: str = "") -> dict:
    import time
    return {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "action": redact_secrets(action)[:120],
        "detail": redact_secrets(detail)[:400],
        "outcome": redact_secrets(outcome)[:200],
    }


__all__ = [
    "SecurityError", "is_within", "resolve_within", "safe_filename",
    "unique_path", "validate_input_file", "validate_output_suffix",
    "sha256_file", "requires_approval", "redact_secrets", "audit_line",
    "ALLOWED_ARTIFACT_SUFFIXES", "MAX_INPUT_BYTES",
]
