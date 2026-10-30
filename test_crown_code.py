"""
test_crown_code.py — integration test for the Crown Code ↔ Keys.AI bridge.

Verifies, without the GUI, that Keys.AI can drive Crown Code's real agent loop:
  B. Local model  — Ollama detected, a model responds to a real inference.
  C. Terminal     — a command executes and streams output with the right exit code.
  D. Coding flow  — Crown Code inspects, writes a file, runs a command, verifies.
  E. Reliability  — the bridge returns a result and cleans up its child process.

Run:  python test_crown_code.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

try:  # keep Windows consoles (cp1252) from choking on box/arrow glyphs
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core import crown_bridge as cb  # noqa: E402


def _line(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    failures: list[str] = []

    _line("=" * 60)
    _line("Crown Code ⇄ Keys.AI integration test")
    _line("=" * 60)

    # ── Environment ────────────────────────────────────────────────────────
    node = cb.node_exe()
    if not node:
        _line("SKIP: Node.js is not installed — cannot run the Crown Code bridge.")
        return 2
    if not cb.crown_dir().exists():
        _line(f"SKIP: Crown Code checkout not found at {cb.crown_dir()}")
        _line("      Set crown_dir in config/crown_code.json or CROWN_CODE_DIR.")
        return 2

    ok, msg = cb.ensure_built(_line)
    _line(f"[build] {msg}")
    if not ok:
        _line(f"FAIL: {msg}")
        return 1

    if not cb.ollama_installed():
        _line("SKIP: Ollama is not installed — cannot test local inference.")
        return 2
    if not cb.ollama_running():
        if not cb.start_ollama(_line):
            _line("SKIP: Ollama is not running and could not be started.")
            return 2

    models = cb.list_models()
    _line(f"[ollama] models: {', '.join(models) or '(none)'}")
    if not models:
        _line("SKIP: no local models installed (pull one, e.g. `ollama pull qwen2.5-coder:7b`).")
        return 2

    model, note = cb.recommend_model(
        models, preferred=(cb.load_config().get("model") or "")
    )
    if note:
        _line(f"[model] {note}")
    _line(f"[model] using {model} (configured: {cb.load_config().get('model')!r})")

    # ── B. Local model produces a real response ────────────────────────────
    t0 = time.time()
    verified, detail = cb.verify_model(model, timeout=300)
    if not verified:
        failures.append(f"B. inference failed: {detail}")
        _line(f"FAIL B: {detail}")
    else:
        _line(f"PASS B: {model} responded {detail!r} in {time.time()-t0:.0f}s")

    # ── C + D. Real agent loop in a scratch workspace ──────────────────────
    workdir = Path(tempfile.mkdtemp(prefix="crown_keysai_"))
    _line(f"[workspace] {workdir}")

    events: list[dict] = []

    def on_event(ev: dict) -> None:
        events.append(ev)
        t = ev.get("type")
        if t == "tool_start":
            _line(f"  tool_start  {ev.get('tool')}  {str(ev.get('input'))[:90]}")
        elif t == "terminal_output":
            _line(f"  term[{ev.get('stream')}] {ev.get('chunk','').rstrip()[:120]}")
        elif t == "terminal_exit":
            _line(f"  terminal_exit = {ev.get('exitCode')}")
        elif t == "tool_end":
            state = "ERR" if ev.get("isError") else "OK"
            _line(f"  tool_end    {state}  {str(ev.get('output'))[:90]}")
        elif t == "result":
            _line(f"  result ok={ev.get('ok')} state={ev.get('state')}")

    bridge = cb.CrownBridge(
        workspace=str(workdir),
        on_event=on_event,
        log=lambda m: _line(f"[log] {m}"),
        model=model,
        provider="ollama",
        policy="safe",
        max_iterations=8,
    )

    task = ("Create a file named verify.txt in the current directory containing exactly "
            "the text WS_OK. Then use the terminal tool to run `type verify.txt` (or, on "
            "Windows where `type` may not be on PATH, use `cmd /c type verify.txt` or "
            "`Get-Content verify.txt`) and confirm the output.")
    started, smsg = bridge.start(task)
    if not started:
        failures.append(f"C. bridge failed to start: {smsg}")
        _line(f"FAIL C: {smsg}")
    else:
        result = bridge.wait(timeout=900)
        bridge.stop()

        target = workdir / "verify.txt"
        file_ok = target.exists() and target.read_text(encoding="utf-8").strip() == "WS_OK"
        wrote = any(e.get("type") == "tool_end" and (e.get("output") or "").startswith("Created") for e in events)
        ran_term = any(e.get("type") == "terminal_output" and "WS_OK" in (e.get("chunk") or "") for e in events)
        exited = any(e.get("type") == "terminal_exit" and e.get("exitCode") == 0 for e in events)

        _line(f"[checks] file_ok={file_ok} wrote_file={wrote} ran_terminal={ran_term} exit0={exited}")

        if file_ok:
            _line("PASS D: Crown Code wrote the file inside the authorized workspace")
        else:
            failures.append("D. file not created/correct in workspace")
            _line("FAIL D: file not created/correct in workspace")

        if ran_term and exited:
            _line("PASS C: terminal executed a command, streamed output, exit code 0")
        else:
            failures.append("C. terminal command did not execute/stream with exit 0")
            _line("FAIL C: terminal command did not execute/stream with exit 0")

        if result and result.get("ok"):
            _line("PASS E: bridge returned a successful result")
        else:
            failures.append(f"E. bridge result not ok: {result}")
            _line(f"FAIL E: bridge result not ok: {result}")

        if bridge.proc is None or bridge.proc.poll() is not None:
            _line("PASS E: child process cleaned up")
        else:
            failures.append("E. child process still running after stop()")
            _line("FAIL E: child process still running")

    shutil.rmtree(workdir, ignore_errors=True)

    _line("-" * 60)
    if failures:
        _line(f"RESULT: FAIL ({len(failures)} issue(s))")
        for f in failures:
            _line(f"  - {f}")
        return 1
    _line("RESULT: PASS — Crown Code bridge works end to end")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
