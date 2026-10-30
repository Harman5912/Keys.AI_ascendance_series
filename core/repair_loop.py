"""
core/repair_loop.py — Enhanced repair loop for Crown Code builds.

Reads exact failing lines from pytest/compile output and feeds ONLY
that error + surrounding code context back to the model for a focused fix.
Max N repair passes, bounded, with exponential backoff.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable, Optional


_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0  # seconds


def extract_error_location(output: str) -> Optional[tuple[str, int, str]]:
    """
    Parse pytest/compiler output for (file_path, line_number, error_message).
    Supports: pytest, Python tracebacks, ruff, flake8 style.
    """
    # Python traceback: File "path/to/file.py", line N, in ...
    m = re.search(r'File "([^"]+)", line (\d+)', output)
    if m:
        fpath, lineno = m.group(1), int(m.group(2))
        # Extract the actual error message (next non-empty line after location)
        snippet = output[m.end():]
        err_line = next((l.strip() for l in snippet.splitlines() if l.strip()), "")
        return fpath, lineno, err_line

    # pytest format: FAILED path/file.py::TestClass::test_name - ExceptionType: msg
    m = re.search(r'FAILED ([^:]+)::([^:]+) - (.+)', output)
    if m:
        return m.group(1), 0, m.group(3)

    # ruff/flake8: path/file.py:N:C: EXXX msg
    m = re.search(r'([^\s:]+\.py):(\d+):\d+: ([A-Z]\d+ .+)', output)
    if m:
        return m.group(1), int(m.group(2)), m.group(3)

    return None


def extract_context_around_line(file_path: str, line_number: int,
                                  radius: int = 8) -> str:
    """Extract source lines around a given line number."""
    try:
        lines = Path(file_path).read_text(encoding="utf-8").splitlines()
        start = max(0, line_number - 1 - radius)
        end = min(len(lines), line_number + radius)
        return "\n".join(
            f"{'>>>' if i + 1 == line_number else '   '} {i+1:4d}: {l}"
            for i, l in enumerate(lines[start:end], start=start)
        )
    except Exception:
        return ""


def build_repair_prompt(error_output: str, workspace: str,
                          context_radius: int = 8) -> str:
    """
    Build a focused repair prompt from error output.
    Only includes the failing file + error context, not the full workspace.
    """
    loc = extract_error_location(error_output)
    if loc:
        fpath, lineno, err_msg = loc
        ctx = extract_context_around_line(fpath, lineno, context_radius)
        return (
            f"The build has a specific failure. Fix ONLY this error:\n\n"
            f"File: {fpath}\n"
            f"Error: {err_msg}\n\n"
            f"Code context:\n```\n{ctx}\n```\n\n"
            f"Write the corrected version of the affected code. Do not change anything else."
        )
    # Fallback: first N chars of error
    return (
        f"The build failed with this error:\n\n{error_output[:800]}\n\n"
        f"Identify and fix the root cause. Be specific and minimal."
    )


def run_repair_loop(
    build_fn: Callable[[], tuple[bool, str]],
    repair_fn: Callable[[str], None],
    max_retries: int = _MAX_RETRIES,
    workspace: str = "",
    on_attempt: Optional[Callable[[int, str], None]] = None,
) -> tuple[bool, str, int]:
    """
    Run a bounded repair loop.

    Args:
        build_fn: () -> (success, output). Runs the build/test.
        repair_fn: (repair_prompt) -> None. Applies a repair.
        max_retries: Maximum number of repair attempts.
        workspace: Project workspace path for context extraction.
        on_attempt: Optional callback(attempt_num, repair_prompt).

    Returns:
        (success, final_output, attempts_used)
    """
    last_output = ""
    for attempt in range(max_retries + 1):
        success, output = build_fn()
        last_output = output
        if success:
            return True, output, attempt

        if attempt == max_retries:
            break

        # Build focused repair prompt
        repair_prompt = build_repair_prompt(output, workspace)
        if on_attempt:
            on_attempt(attempt + 1, repair_prompt)

        # Apply repair
        repair_fn(repair_prompt)

        # Exponential backoff before next attempt
        if attempt < max_retries - 1:
            time.sleep(_BACKOFF_BASE ** attempt)

    return False, last_output, max_retries
