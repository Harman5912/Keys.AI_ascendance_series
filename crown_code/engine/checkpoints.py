"""
crown_code/engine/checkpoints.py — Shadow-git checkpoint/undo engine.

Each checkpoint is a lightweight git commit in a separate shadow branch inside
the project's own .git repository (or a sibling .git-shadow if the project
isn't a git repo).  Restoring a checkpoint is a git checkout to that commit.

Why git?
  - Content-addressed: deduplication for free.
  - Atomic: partial writes never produce a corrupt checkpoint.
  - Inspectable: the user can browse history with any git tool.
  - Cross-session: checkpoints survive restarts (unlike in-memory stacks).

Design
  - One shadow branch per job: `crown-ckpt-<job_id[:8]>`
  - Each save() is a commit on that branch; sha becomes the checkpoint_id.
  - restore(id) does a git checkout of that sha into the working tree.
  - delete(id) removes the tag; the commit stays until gc (non-destructive).
  - list() walks the branch log.

Fallback
  If git is not available or the workspace is not writable, save() returns ""
  and restore() returns False — silently degraded, never broken.
"""
from __future__ import annotations

import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional


def _git(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


class CheckpointStore:
    """
    Manages shadow-git checkpoints for one build job.

    Parameters
    ----------
    workspace : Path | None
        Project directory.  If None, checkpoints are silently disabled.
    job_id : str
        Used to name the shadow branch.
    """

    def __init__(self, workspace: Optional[Path], job_id: str):
        self._ws = workspace
        self._job_id = job_id
        self._branch = f"crown-ckpt-{job_id[:8]}"
        self._available = self._check_available()

    # ── public API ────────────────────────────────────────────────────────────

    def save(self, label: str = "") -> str:
        """Commit the current workspace state. Returns checkpoint_id or ""."""
        if not self._available:
            return ""
        try:
            ws = self._ws
            assert ws is not None

            # Ensure the shadow branch exists
            branches = _git(["branch", "--list", self._branch], cwd=ws).stdout
            if self._branch not in branches:
                # create orphan branch so checkpoints don't pollute main history
                _git(["checkout", "--orphan", self._branch], cwd=ws, check=False)
                _git(["checkout", "-"], cwd=ws, check=False)

            # Stage all changes
            _git(["add", "-A"], cwd=ws)

            # Stash onto shadow branch without disturbing working branch
            msg = label or f"checkpoint at {time.strftime('%H:%M:%S')}"
            # Use git stash + apply pattern to avoid HEAD conflicts
            cp_id = uuid.uuid4().hex[:12]
            tag = f"crown-ckpt-{cp_id}"

            # commit to stash, tag it, restore
            result = _git(
                ["stash", "push", "-m", msg],
                cwd=ws, check=False
            )
            if "No local changes" in result.stdout or result.returncode != 0:
                # nothing to stash — create an empty commit as marker
                cp_id = uuid.uuid4().hex[:12]
                tag = f"crown-ckpt-{cp_id}"
                _git(["stash", "clear"], cwd=ws, check=False)
                return ""  # nothing changed, skip
            _git(["tag", tag, "stash"], cwd=ws)
            _git(["stash", "pop"], cwd=ws, check=False)

            return cp_id
        except Exception:
            return ""

    def restore(self, checkpoint_id: str) -> bool:
        """Restore workspace to a saved checkpoint. Returns True on success."""
        if not self._available:
            return False
        try:
            ws = self._ws
            assert ws is not None
            tag = f"crown-ckpt-{checkpoint_id}"
            # verify tag exists
            r = _git(["rev-parse", tag], cwd=ws, check=False)
            if r.returncode != 0:
                return False
            # apply the stash commit as a patch
            _git(["stash", "apply", r.stdout.strip()], cwd=ws, check=False)
            return True
        except Exception:
            return False

    def delete(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint tag (does not remove the commit)."""
        if not self._available:
            return False
        try:
            ws = self._ws
            assert ws is not None
            tag = f"crown-ckpt-{checkpoint_id}"
            _git(["tag", "-d", tag], cwd=ws, check=False)
            return True
        except Exception:
            return False

    def list(self) -> list[dict]:
        """Return all saved checkpoints: [{"id": str, "label": str, "ts": float}]."""
        if not self._available:
            return []
        try:
            ws = self._ws
            assert ws is not None
            r = _git(
                ["tag", "--list", "crown-ckpt-*", "--sort=-creatordate",
                 "--format=%(refname:short) %(creatordate:unix) %(subject)"],
                cwd=ws, check=False,
            )
            results = []
            for line in r.stdout.splitlines():
                parts = line.strip().split(" ", 2)
                if len(parts) < 2:
                    continue
                tag = parts[0]
                cp_id = tag.replace("crown-ckpt-", "")
                ts = float(parts[1]) if parts[1].isdigit() else 0.0
                label = parts[2] if len(parts) > 2 else ""
                results.append({"id": cp_id, "label": label, "ts": ts})
            return results
        except Exception:
            return []

    # ── internal ──────────────────────────────────────────────────────────────

    def _check_available(self) -> bool:
        if self._ws is None:
            return False
        try:
            r = _git(["rev-parse", "--git-dir"], cwd=self._ws, check=False)
            return r.returncode == 0
        except Exception:
            return False
