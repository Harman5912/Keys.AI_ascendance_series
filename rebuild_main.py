"""Rebuild main.py.

The live main.py got smashed by an earlier repair run: every line was padded
with ~295 blank lines (430k lines, 1.35 MB) and the middle of
KeysAILive._execute_tool was replaced by a fragment of the vision branch.

This script takes the non-blank lines (the real source, in order), splices the
missing handlers back in (recovered from __pycache__/main.cpython-312.pyc
bytecode) and writes a clean, conventionally spaced main.py.
"""
from __future__ import annotations

import marshal
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "bak_stripped.py"
OUT = ROOT / "main_rebuilt.py"
PYC = ROOT / "__pycache__" / "main.cpython-312.pyc"

BROKEN = (
    "                items = undo_stack.history()\n"
    "                result = (\n"
    '                    f"[VISION_ACTIVE] {_stall.capitalize()} captured. "\n'
    '                    f"Immediately say ONE natural sentence in English "\n'
    "                    f'(e.g. 'Looking at your {_stall} now, sir'). '\n"
    '                    f"Do NOT describe or guess content - the actual image arrives in the NEXT message."\n'
    "                )\n"
    '            elif name == "close_camera":\n'
    "                self.ui.stop_camera_stream()\n"
    '                result = "Camera closed."\n'
    '            elif name == "web_search":\n'
    'elif name == "system_status":\n'
)

FIXED = '''\
                items = undo_stack.history()
                result = (
                    "Things I can undo, most recent first:\\n"
                    + "\\n".join(f"{i+1}. {t}" for i, t in enumerate(items))
                ) if items else "I have not changed anything I can undo yet."
            else:
                result = await loop.run_in_executor(None, undo_stack.undo_last)
        elif name == "manage_monitor":
            action = args.get("action", "").lower().strip()
            topic  = args.get("topic", "").strip()
            if action == "add" and topic:
                result = await asyncio.to_thread(add_monitor, topic)
            elif action == "remove" and topic:
                result = await asyncio.to_thread(remove_monitor, topic)
            elif action == "list":
                topics = await asyncio.to_thread(list_monitors)
                result = ("Monitoring: " + ", ".join(topics)) if topics else "No topics are being monitored."
            else:
                result = "Specify action (add/remove/list) and a topic."

        # UAC secure desktop guard: while a UAC prompt owns the screen the
        # automation tools cannot see the desktop, so they pause instead of
        # clicking into the void.
        if name in (
            "computer_use", "hybrid_control", "computer_control",
            "computer_settings", "editor_control", "browser_control",
            "agent_control",
        ):
            try:
                from automation.elevation import secure_desktop_active
                if secure_desktop_active():
                    result = (
                        "The UAC secure desktop is active \u2014 I am pausing automation until "
                        "you approve the prompt and return to your desktop. Ask me to "
                        "continue afterwards."
                    )
                    return types.FunctionResponse(
                        id=fc.id, name=name, response={"result": result}
                    )
            except Exception:
                pass

        if name == "screen_process":
            import time as _t_mod
            _now = _t_mod.monotonic()
            # Cooldown: captures that arrive before the model has looked at the
            # previous frame only burn frames, so gate them.
            _cooldown = 1.5
            if self._vision_busy or (_now - self._vision_last_time) < _cooldown:
                _wait = max(0, _cooldown - (_now - self._vision_last_time))
                print(f"[Vision] \u23f3 Cooldown active ({_wait:.1f}s remaining)")
                result = (
                    "Vision is briefly cooling down. Wait a moment, then you may capture "
                    "once more to VERIFY the action's result on screen."
                )
            else:
                from actions.screen_processor import _capture_camera, _capture_screen
                self._vision_busy = True
                self._vision_last_time = _now
                angle     = args.get("angle", "screen").lower()
                user_text = args.get("text", "What do you see?")
                if angle == "camera":
                    img_b, mime_t = await loop.run_in_executor(None, _capture_camera)
                    self.ui.start_camera_stream()
                    self._vision_cam_active = True
                    print(f"[Vision] \U0001f4f7 Camera: {len(img_b):,} bytes")
                    _stall = "camera"
                else:
                    img_b, mime_t = await loop.run_in_executor(None, _capture_screen)
                    print(f"[Vision] \U0001f5a5\ufe0f  Screen: {len(img_b):,} bytes")
                    _stall = "screen"
                self._pending_vision = (img_b, mime_t, user_text, angle)
                result = (
                    f"[VISION_ACTIVE] {_stall.capitalize()} captured. "
                    f"Immediately say ONE natural sentence in English "
                    f"(e.g. 'Looking at your {_stall} now, sir'). "
                    f"Do NOT describe or guess content - the actual image arrives in the NEXT message."
                )
        elif name == "close_camera":
            self.ui.stop_camera_stream()
            result = "Camera closed."
        elif name == "web_search":
            from actions.web_search import web_search as web_search_action
            r = await loop.run_in_executor(
                None,
                lambda: web_search_action(parameters=args, player=self.ui),
            )
            result = r or "Done."
            _mode = args.get("mode", "search")
            if r and not r.startswith("No results") and not r.startswith("Search failed"):
                _query = args.get("query") or ", ".join(args.get("items", []))
                _label = f"{_mode.upper()} - {_query[:38]}" if _query else _mode.upper()
                self.ui.show_content(_label, r)
        elif name == "system_status":
'''


CHAIN_START = '        if name == "recall_memory":'
CHAIN_END = '        except Exception as e:'


def restore_try_block(lines: list[str]) -> list[str]:
    """The tool chain lives inside a try/except. The corrupted file lost the
    `try:` line and had the whole chain dedented by one level, so put both
    back: `try:` at 8 spaces, the chain indented one level deeper."""
    start = next((i for i, l in enumerate(lines) if l == CHAIN_START), None)
    end = None
    if start is not None:
        rel = next((i for i, l in enumerate(lines[start:]) if l == CHAIN_END), None)
        end = None if rel is None else start + rel
    if start is None or end is None or end <= start:
        raise SystemExit(
            f"[rebuild] could not locate the tool chain (start={start}, end={end})"
        )
    body = [("    " + l if l.strip() else l) for l in lines[start:end]]
    return lines[:start] + ["        try:"] + body + lines[end:]


def multi_line_string_lines(src: str) -> set[int]:
    """Line numbers that live inside a multi-line string literal."""
    import tokenize

    inside: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(iter(src.splitlines(True)).__next__):
            if tok.type == tokenize.STRING and tok.end[0] > tok.start[0]:
                inside.update(range(tok.start[0] + 1, tok.end[0] + 1))
    except Exception as exc:  # pragma: no cover - only on a broken rebuild
        print(f"[rebuild] tokenize failed: {exc}", file=sys.stderr)
    return inside


SPACER = re.compile(r"^(def |class |async def |# |@|<module>)")
METHOD = re.compile(r"^    (async def |def |@)")


def space_out(lines: list[str], protected: set[int]) -> str:
    out: list[str] = []
    for lineno, line in enumerate(lines, 1):
        add_blank = lineno not in protected and (
            SPACER.match(line) or METHOD.match(line)
        )
        if add_blank and out and out[-1].strip():
            out.append("")
        out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


def string_constants(code) -> list[str]:
    vals: list[str] = []
    stack = [code]
    while stack:
        c = stack.pop()
        for k in c.co_consts:
            if hasattr(k, "co_code"):
                stack.append(k)
            elif isinstance(k, str):
                vals.append(k)
    return sorted(vals)


def main() -> int:
    raw = BASE.read_text(encoding="utf-8")
    if BROKEN not in raw:
        print("[rebuild] broken anchor not found in bak_stripped.py", file=sys.stderr)
        return 1

    spliced = raw.replace(BROKEN, FIXED, 1)
    lines = spliced.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    lines = restore_try_block(lines)

    protected = multi_line_string_lines("\n".join(lines))
    text = space_out(lines, protected)
    # The padding ate blank lines that sat inside multi-line strings too. This
    # docstring is the only one the bytecode comparison flagged, so restore it.
    text = text.replace(
        "keeps running in text/brain mode via the configured LLM provider.\n",
        "keeps running in text/brain mode via the configured LLM provider.\n\n",
    )
    OUT.write_text(text, encoding="utf-8")

    try:
        compiled = compile(text, "main.py", "exec")
    except SyntaxError as exc:
        print(f"[rebuild] SyntaxError {exc.lineno}:{exc.offset} {exc.msg}", file=sys.stderr)
        print(f"          {(exc.text or '').rstrip()}", file=sys.stderr)
        return 2

    print(f"[rebuild] wrote {OUT.name}: {len(text.splitlines())} lines")

    if PYC.exists():
        old = marshal.loads(PYC.read_bytes()[16:])
        want = set(string_constants(old))
        got = set(string_constants(compiled))
        missing = sorted(want - got)
        added = sorted(got - want)
        print(f"[verify] pyc string constants: {len(want)}, rebuilt: {len(got)}")
        print(f"[verify] only-in-pyc ({len(missing)}):")
        for s in missing[:40]:
            print("   ", repr(s[:100]))
        print(f"[verify] only-in-rebuild ({len(added)}):")
        for s in added[:40]:
            print("   ", repr(s[:100]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
