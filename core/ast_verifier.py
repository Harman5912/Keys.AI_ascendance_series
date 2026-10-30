"""
core/ast_verifier.py — Post-write AST validation hook.

After Crown Code writes/edits a Python file, run ast.parse to verify
the file is syntactically valid before claiming success.
Inspired by OpenCode's post-edit linter feedback loop.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


def verify_python_file(path: str | Path) -> tuple[bool, str]:
    """
    Parse a Python file with ast.parse.
    Returns (ok, error_message).
    """
    p = Path(path)
    if not p.exists():
        return False, f"File not found: {path}"
    try:
        source = p.read_text(encoding="utf-8")
        ast.parse(source)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError at line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, str(e)


def verify_file(path: str | Path) -> tuple[bool, str]:
    """
    Verify any file by extension. Returns (ok, error_message).
    Currently handles .py with ast; .js/.ts/.json with basic checks.
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".py":
        return verify_python_file(p)
    if ext == ".json":
        try:
            import json
            json.loads(p.read_text(encoding="utf-8"))
            return True, ""
        except Exception as e:
            return False, f"JSON error: {e}"
    # For other files: just verify they exist and are readable
    if p.exists():
        return True, ""
    return False, f"File not found: {path}"


def run_linter(path: str | Path, python_exe: Optional[str] = None) -> tuple[bool, str]:
    """
    Run ruff or flake8 on a Python file.
    Returns (clean, output).
    """
    p = Path(path)
    if p.suffix != ".py":
        return True, ""
    exe = python_exe or sys.executable
    # Try ruff first (faster)
    for linter in [["ruff", "check", "--select=E,F", str(p)],
                   [exe, "-m", "flake8", "--max-line-length=120", str(p)]]:
        try:
            result = subprocess.run(
                linter, capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                return True, ""
            return False, (result.stdout + result.stderr)[:500]
        except FileNotFoundError:
            continue
        except Exception as e:
            return False, str(e)
    return True, ""  # No linter available — skip


def build_error_feedback(path: str | Path, error: str, source_preview_lines: int = 10) -> str:
    """
    Build a feedback message for the LLM after a verification failure.
    Feeds back: file path, error, and surrounding code context.
    """
    p = Path(path)
    lines = []
    if p.exists():
        try:
            source_lines = p.read_text(encoding="utf-8").splitlines()
            # Extract line number from error if present
            m = re.search(r'line (\d+)', error)
            if m:
                ln = int(m.group(1))
                start = max(0, ln - source_preview_lines // 2)
                end = min(len(source_lines), ln + source_preview_lines // 2)
                lines = source_lines[start:end]
            else:
                lines = source_lines[:source_preview_lines]
        except Exception:
            pass
    ctx = "\n".join(f"{i+1}: {l}" for i, l in enumerate(lines)) if lines else "(could not read file)"
    return (
        f"The file `{p.name}` failed verification:\n"
        f"Error: {error}\n\n"
        f"Relevant code:\n```python\n{ctx}\n```\n\n"
        f"Please fix this specific error and write the corrected file."
    )
