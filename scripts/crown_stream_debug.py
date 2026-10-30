#!/usr/bin/env python3
"""
scripts/crown_stream_debug.py — run ONE task through the Crown Code headless
bridge and print every NDJSON event as it arrives, including assistant token
deltas, so a stalled or looping generation is visible immediately.

Usage:
    python scripts/crown_stream_debug.py --task "create hello.txt with HI" --model qwen3.5:4b
    python scripts/crown_stream_debug.py --site 1 --model qwen3.5:4b
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import crown_websites_demo as demo  # noqa: E402
from core.crown_bridge import CrownBridge, ensure_built  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="")
    ap.add_argument("--site", type=int, default=0, help="use the build task for site N")
    ap.add_argument("--model", default="qwen3.5:4b")
    ap.add_argument("--cwd", default="")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    if args.site:
        site = demo.SITES[args.site - 1]
        kpi_lines = "\n".join(f"  {i + 1}. {k}" for i, k in enumerate(demo.kpis_for(site["domain"])))
        task = demo.BUILD_TASK.format(**site, kpi_lines=kpi_lines)
        cwd = Path(args.cwd) if args.cwd else demo.SITES_ROOT / ("debug_" + site["slug"])
    else:
        task = args.task or "Create a file named hello.txt containing HI using the write_file tool."
        cwd = Path(args.cwd) if args.cwd else demo.SITES_ROOT / "debug_scratch"
    cwd.mkdir(parents=True, exist_ok=True)

    ok, msg = ensure_built()
    if not ok:
        print(f"build failed: {msg}")
        return 2

    started = time.time()
    counts: dict[str, int] = {}
    deltas: list[str] = []
    last_report = [time.time()]
    last_event = [time.time(), ""]

    # Ollama only delivers a native tool call once its whole argument block is
    # generated, so a big write_file looks identical to a hang unless we print a
    # heartbeat for the silence.
    import threading

    def heartbeat() -> None:
        while not stop_hb.is_set():
            stop_hb.wait(20)
            silent = time.time() - last_event[0]
            print(f"  [{time.time() - started:6.1f}s] …still working (last event {silent:.0f}s ago: "
                  f"{last_event[1] or 'none'}, {sum(len(d) for d in deltas)} chars streamed)",
                  flush=True)

    stop_hb = threading.Event()
    threading.Thread(target=heartbeat, daemon=True).start()

    def on_event(ev: dict) -> None:
        etype = ev.get("type", "?")
        counts[etype] = counts.get(etype, 0) + 1
        elapsed = time.time() - started
        if etype != "assistant_delta":
            last_event[0] = time.time()
            last_event[1] = etype
        if etype == "assistant_delta":
            deltas.append(str(ev.get("text", "")))
            # heartbeat every 5s so a long generation is visibly alive
            if time.time() - last_report[0] > 5:
                last_report[0] = time.time()
                print(f"  [{elapsed:6.1f}s] streaming… {sum(len(d) for d in deltas)} chars "
                      f"({len(deltas)} deltas)", flush=True)
        elif etype == "tool_start":
            print(f"  [{elapsed:6.1f}s] TOOL_START {ev.get('tool')} "
                  f"{str(ev.get('input'))[:200]}", flush=True)
        elif etype == "tool_end":
            print(f"  [{elapsed:6.1f}s] TOOL_END err={ev.get('isError')} "
                  f"{str(ev.get('output'))[:150]}", flush=True)
        elif etype in ("ready", "result", "error", "permission_request", "state",
                       "terminal_exit", "terminal_output"):
            keep = {k: v for k, v in ev.items() if k != "tools"}
            print(f"  [{elapsed:6.1f}s] {etype}: {str(keep)[:400]}", flush=True)

    bridge = CrownBridge(
        workspace=str(cwd), on_event=on_event, permission_handler=lambda ev: True,
        log=lambda m: print(f"  [crown] {m}", flush=True),
        model=args.model, provider="ollama", policy="safe", max_iterations=30,
    )
    ok, msg = bridge.start(task)
    print(f"bridge start: {ok} {msg}  cwd={cwd}", flush=True)
    result = bridge.wait(timeout=args.timeout)
    bridge.stop()
    stop_hb.set()

    print(f"\nelapsed {time.time() - started:.1f}s")
    print(f"event counts: {counts}")
    if deltas:
        text = "".join(deltas)
        print(f"\nstreamed {len(text)} chars; first 400:\n{text[:400]}")
        print(f"\nlast 400:\n{text[-400:]}")
    print(f"\nresult: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
