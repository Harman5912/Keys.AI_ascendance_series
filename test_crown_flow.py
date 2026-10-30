"""
test_crown_flow.py — the in-app coding-task flow, through the real dispatch.

Simulates what happens inside Keys.AI when the model calls the coding tool:
  TOOL_HANDLERS["crown_code"] -> actions.crown_code -> core.crown_bridge
  -> Crown Code headless agent -> events mapped back onto the UI player.

A recording player stub stands in for KeysAIUI so the whole path is exercised
without the GUI. Verifies the user-visible contract: the creation workspace
opens, activity/terminal output streams, the task is executed for real, and a
verified summary is returned.

Run:  python test_crown_flow.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


class StubPlayer:
    """Records every UI call crown_code makes (mirrors KeysAIUI's API)."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.terminal = ""
        self.cmd_handler = "unset"
        self.stop_handler = "unset"

    def _rec(self, name, *args):
        self.calls.append((name,) + args)

    def kinds(self):
        return [c[0] for c in self.calls]

    # creation workspace API
    def write_log(self, text): self._rec("write_log", text)
    def begin_creation(self, mode, name, path): self._rec("begin_creation", mode, name, path)
    def creation_event(self, icon, text, file=None): self._rec("creation_event", icon, text)
    def creation_file_set_active(self, path): self._rec("creation_file_set_active", path)
    def creation_code_set(self, content): self._rec("creation_code_set", len(content))
    def creation_progress(self, pct): self._rec("creation_progress", pct)
    def creation_error(self, text): self._rec("creation_error", text)
    def creation_complete(self, summary=""): self._rec("creation_complete", summary)

    # permission dialog
    def ask_permission(self, action, reason="", location=""):
        self._rec("ask_permission", action)
        return "allow_once"

    # embedded terminal
    def set_terminal_command_handler(self, cb): self.cmd_handler = cb
    def set_terminal_stop_handler(self, cb): self.stop_handler = cb
    def terminal_output(self, chunk, stream="stdout", origin="agent"):
        self.terminal += chunk

    def clear_terminal_command_handler(self): self.cmd_handler = None


def main() -> int:
    from core.tool_registry import TOOL_HANDLERS

    failures: list[str] = []
    if "crown_code" not in TOOL_HANDLERS:
        print("FAIL: crown_code is not registered in TOOL_HANDLERS")
        return 1

    workdir = Path(tempfile.mkdtemp(prefix="crown_flow_"))
    print(f"[workspace] {workdir}")

    player = StubPlayer()
    task = ("Create a file named flow.txt in the current directory containing exactly the "
            "text FLOW_OK, then run `type flow.txt` with the terminal tool to verify it.")
    try:
        result = TOOL_HANDLERS["crown_code"](
            # wait: the tool starts a background job by default (so the chat
            # stays responsive); this test asserts the finished build.
            {"description": task, "workspace": str(workdir), "policy": "safe",
             "wait": True},
            player, None,
        )
    except Exception as e:
        shutil.rmtree(workdir, ignore_errors=True)
        print(f"FAIL: crown_code raised {type(e).__name__}: {e}")
        return 1

    kinds = player.kinds()
    target = workdir / "flow.txt"
    file_ok = target.exists() and target.read_text(encoding="utf-8").strip() == "FLOW_OK"

    def check(cond, ok_msg, fail_msg):
        if cond:
            print(f"PASS: {ok_msg}")
        else:
            failures.append(fail_msg)
            print(f"FAIL: {fail_msg}")

    print(f"[ui calls] {kinds}")

    check("begin_creation" in kinds, "creation workspace opened for the task",
          "creation workspace never opened")
    check("creation_event" in kinds, "activity timeline received progress events",
          "no activity events")
    check("creation_complete" in kinds, "creation completed event emitted",
          "no completion event")
    check("FLOW_OK" in player.terminal,
          "streamed real terminal output into the embedded terminal",
          f"terminal output missing (got {player.terminal[:120]!r})")
    check(file_ok, "Crown Code created the file for real in the workspace",
          "file not created/correct")
    check(bool(result and result.strip()), "a user-facing result string was returned",
          "empty result returned")
    # A synchronous run returns the job's own report ("Coding X: done in Ns"
    # plus the files it wrote), not the old one-line summary.
    check(": done" in result and "Files:" in result,
          f"result reports a verified finish ({result.splitlines()[0]!r})",
          f"result did not report success: {result[:120]!r}")
    # The stop handler is pointed at the bridge for the length of the run and
    # cleared afterwards; crown_code registers no command handler of its own.
    check(player.stop_handler is None and player.cmd_handler in (None, "unset"),
          "terminal handlers cleaned up after the task",
          "terminal handlers left registered after the task")

    shutil.rmtree(workdir, ignore_errors=True)
    print("-" * 60)
    if failures:
        print(f"RESULT: FAIL ({len(failures)})")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: PASS — in-app coding-task flow works end to end")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
