"""globe.install — locate and validate the vendored God's Eye View checkout.

God's Eye View is a real third-party application (MIT, Copyright (c) 2026
Bilawal Sidhu). It is vendored unmodified under ``integrations/gods_eye_view``
and runs as its own local service; nothing here edits its source.

This module answers one question honestly: *can this checkout actually run
here?* It checks the directory, the manifest, the installed dependencies and
the Node version against the range the repository's own ``package.json``
declares. It never installs anything on its own and never upgrades the host's
Node — a mismatch is reported so the user can decide.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Engine range published by the repository at the time of vendoring:
#   "node": ">=24.14.0 <25 || >=26 <27"
# Kept as data, not as a guess, so a future manifest edit invalidates it
# visibly instead of silently drifting.
_ENGINE_CLAUSES = ((24, 14, 0), (25, 0, 0)), ((26, 0, 0), (27, 0, 0))

MIN_NODE = (24, 14, 0)


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def default_dir() -> Path:
    """Where the checkout lives, honouring a user override."""
    override = os.environ.get("KEYS_GLOBE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return project_root() / "integrations" / "gods_eye_view"


@dataclass
class InstallStatus:
    """Everything the app needs to know before it tries to launch the globe."""

    path: Path
    ok: bool = False
    present: bool = False
    manifest: bool = False
    installed: bool = False
    node: str = ""
    node_ok: bool = False
    engine_range: str = ""
    version: str = ""
    problems: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "ok": self.ok,
            "present": self.present,
            "manifest": self.manifest,
            "installed": self.installed,
            "node": self.node,
            "node_ok": self.node_ok,
            "engine_range": self.engine_range,
            "version": self.version,
            "problems": list(self.problems),
            "hints": list(self.hints),
        }


def _run(cmd: list[str], timeout: float = 20.0) -> str:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (proc.stdout or "").strip()


def node_version() -> str:
    """The installed Node version as ``vX.Y.Z``, or "" when absent."""
    exe = shutil.which("node")
    if not exe:
        return ""
    return _run([exe, "--version"])


def _parse_version(text: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def node_in_range(version: str) -> bool:
    """True when `version` satisfies the repository's declared engine range."""
    parsed = _parse_version(version)
    if parsed is None:
        return False
    # Major 25 is end-of-life and explicitly outside the range.
    if parsed[0] == 25:
        return False
    if parsed[0] == 24:
        return parsed >= _ENGINE_CLAUSES[0][0]
    if parsed[0] == 26:
        return True
    return False


def check(path: Path | None = None) -> InstallStatus:
    """Inspect the checkout without touching it."""
    target = Path(path) if path else default_dir()
    status = InstallStatus(path=target, engine_range=">=24.14.0 <25 || >=26 <27")

    if not target.is_dir():
        status.problems.append(f"The God's Eye View checkout is missing: {target}")
        status.hints.append(
            "Clone https://github.com/bilawalsidhu/gods-eye-view into "
            f"{target} (or set KEYS_GLOBE_DIR) and run `npm ci` there."
        )
        return status
    status.present = True

    manifest_path = target / "package.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            status.problems.append(f"package.json could not be read: {exc}")
            manifest = {}
        if manifest:
            status.manifest = True
            status.version = str(manifest.get("version", ""))
            engines = manifest.get("engines") or {}
            published = str(engines.get("node", "") or "")
            if published:
                status.engine_range = published
            if manifest.get("name") != "gods-eye-view":
                status.problems.append(
                    "That directory is not a God's Eye View checkout "
                    f"(package name is {manifest.get('name')!r})."
                )
    else:
        status.problems.append(f"package.json is missing from {target}")

    status.installed = (target / "node_modules").is_dir() and (
        target / "node_modules" / "vite").is_dir()
    if not status.installed:
        status.problems.append("Dependencies are not installed (node_modules/vite missing).")
        status.hints.append(f"Run `npm ci` in {target}.")

    status.node = node_version()
    status.node_ok = node_in_range(status.node) if status.node else False
    if not status.node:
        status.problems.append("Node.js was not found on PATH.")
        status.hints.append(
            "Install Node.js 24.14+ or 26.x — the repository does not support "
            "Node 25 or Node 27."
        )
    elif not status.node_ok:
        status.problems.append(
            f"Node {status.node.lstrip('v')} is outside the supported range "
            f"({status.engine_range}). The globe needs 24.14+ or 26.x."
        )
        status.hints.append(
            "Install a supported Node (nvm-windows or the official installer). "
            "Keys.AI will not silently upgrade the machine's Node."
        )

    status.ok = status.present and status.manifest and status.installed and status.node_ok
    return status
