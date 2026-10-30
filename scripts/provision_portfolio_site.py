import sys, tempfile, time
from pathlib import Path

BASE = Path(r"C:\Users\harma\Desktop\PROJECTS\Keys-acendence-series\acendence-VIII_GEN-I")
sys.path.insert(0, str(BASE))
import os
os.environ.setdefault("NO_COLOR", "1")
from core import crown_bridge as cb

OUT_DIR_ENV = "CROWN_PORTFOLIO_OUT_DIR"

def main():
    out_dir = Path(os.environ.get(OUT_DIR_ENV, "")).resolve() if os.environ.get(OUT_DIR_ENV) else None
    if not out_dir or not out_dir.is_dir():
        print(f"ERROR: set {OUT_DIR_ENV} to an existing directory", flush=True)
        return 1

    work = out_dir
    print(f"WORK={work}", flush=True)

    ev = []
    def on_event(e):
        t = e.get("type")
        if t in ("ready","tool_start","tool_end","terminal_output","state","result","error","notice"):
            print(f"[{t}] {str(e)[:240]}", flush=True)
        ev.append(e)

    b = cb.CrownBridge(
        workspace=str(work),
        on_event=on_event,
        log=lambda m: print(f"[log] {m}", flush=True),
        model="qwen3:8b",
        provider="ollama",
        policy="safe",
        max_iterations=16,
    )

    task = (
        "Create a modern dark investment-portfolio dashboard as a SINGLE self-contained "
        "index.html. It must open directly in the default desktop browser via a file:// URL, "
        "with no server and no build step. Requirements:\n"
        "1) Dark finance look, responsive, no console errors on load.\n"
        "2) Portfolio summary: total value, daily change %, weekly change %, all-time return %.\n"
        "3) Horizontal bar chart of allocation across 3-5 asset classes drawn with inline SVG ONLY "
        "- no external chart library.\n"
        "4) Holdings table with 5-7 rows: ticker, name, shares, price, value, change.\n"
        "5) Recent transactions list with 3-4 items.\n"
        "6) Refresh Prices button that slightly randomizes prices and updates the UI.\n"
        "7) All JS inline, no fetch to any server.\n"
        "Write the file as index.html in the current directory. After writing it, use the "
        "terminal tool to run EXACTLY this command so the dashboard opens in the default browser:\n"
        "python -c 'import webbrowser,os; webbrowser.open(\"file://\"+os.path.abspath(\"index.html\"))'\n"
        "Confirm the file exists and report its size and absolute path."
    )

    print("STARTING_TASK", flush=True)
    started, smsg = b.start(task)
    print(f"started={started} msg={smsg}", flush=True)
    result = b.wait(timeout=900)
    b.stop()
    print(f"RESULT ({time.time():.0f}s): {result}", flush=True)

    print("=== DELIVERABLE_CHECK ===", flush=True)
    idx = work / "index.html"
    if idx.exists():
        raw = idx.read_text(encoding="utf-8", errors="replace")
        print(f"[FILE] index.html exists, size={len(raw)} bytes, path={idx.resolve()}", flush=True)
        import re
        bad = re.findall(r"\w+\s*=\s*\"[^\"]*,\s*\"", raw)
        print(f"[SVG] trailing-comma attribute patterns found={len(bad)}", flush=True)
        if bad:
            print("[SVG] BAD_EXAMPLES:", bad[:5], flush=True)
        print("[HTML_HEAD]", raw[:1200], flush=True)
    else:
        print("[FILE] index.html MISSING", flush=True)
        return 1

    print("=== DONE ===", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
