#!/usr/bin/env python3
"""crown_stage_bench.py — pick the local model that can actually do the job.

Two measurements per model, both against the real Ollama chat API:

1. decode speed      — tokens/second on a plain generation (no tools).
2. stage compliance  — run the harness's real stage prompt with the real tool
   schemas and report whether the model emitted a usable tool call (a native
   `tool_calls`, or JSON-as-prose which Crown Code's parser recovers), how big
   the generated file was, and whether it looks complete.

    python scripts/crown_stage_bench.py
    python scripts/crown_stage_bench.py --models qwen2.5-coder:3b qwen3.5:4b
    python scripts/crown_stage_bench.py --stages app
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from crown_websites_demo import (  # noqa: E402
    CHARTS_TASK, DATA_TASK, LIVE_TASK, MARKUP_TASK, STYLES_TASK, TABLE_TASK, SITES,
    number_list, render, series_lines,
)

OLLAMA = "http://localhost:11434"
CHAT = OLLAMA + "/api/chat"

WRITE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file in the working directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Full file content"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the working directory",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]

SYSTEM = ("You are Crown Code, a coding agent working in a real directory on this machine. "
          "Use the tools to do the work. Never describe work you did not do; never write a "
          "tool call as JSON in your prose — invoke the tool.")

def capabilities(model: str) -> list[str]:
    """Ask Ollama what this model can do (thinking / tools / vision)."""
    try:
        req = urllib.request.Request(OLLAMA + "/api/show",
                                     data=json.dumps({"model": model}).encode(),
                                     headers={"Content-Type": "application/json"})
        data = json.load(urllib.request.urlopen(req, timeout=30))
        return list(data.get("capabilities") or [])
    except Exception:
        return []


def think_flag(caps: list[str]) -> bool | None:
    """`think: false` for models that support thinking (pure latency on CPU),
    and no flag at all for the rest — Ollama 400s if you send `think: true` to a
    model whose template has no thinking tags."""
    return False if "thinking" in caps else None


def stage_prompt(which: str, site: dict) -> str:
    kpis = number_list(site["kpis"])
    series = series_lines(site)
    cols = number_list(site["columns"])
    if which == "styles":
        return render(STYLES_TASK, title=site["title"], domain=site["domain"])
    if which == "markup":
        return render(MARKUP_TASK, title=site["title"], domain=site["domain"], kpis=kpis,
                      series=series, columns=cols, col1=site["columns"][0], col2=site["columns"][1],
                      col3=site["columns"][2], col4=site["columns"][3], col5=site["columns"][4],
                      col6=site["columns"][5])
    if which == "data":
        return render(DATA_TASK, title=site["title"], domain=site["domain"], kpis=kpis,
                      series=series, columns=cols)
    if which == "table":
        return render(TABLE_TASK, title=site["title"], domain=site["domain"])
    if which == "charts":
        return render(CHARTS_TASK, title=site["title"], domain=site["domain"], series=series)
    if which == "live":
        return render(LIVE_TASK, title=site["title"], domain=site["domain"])
    raise SystemExit(f"unknown stage {which}")


def post(path: str, body: dict, timeout: int):
    req = urllib.request.Request(path, data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def decode_speed(model: str, think: bool | None, timeout: int = 240) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Count from 1 to 80 as comma separated numbers. Numbers only."}],
        "stream": True,
        "options": {"num_ctx": 8192, "num_predict": 220, "temperature": 0.1},
    }
    if think is not None:
        body["think"] = think
    t0 = time.time()
    last = {}
    with post(CHAT, body, timeout) as resp:
        for raw in resp:
            msg = json.loads(raw.decode("utf-8", "replace"))
            if msg.get("done"):
                last = msg
                break
    dur = (last.get("eval_duration") or 0) / 1e9
    n = last.get("eval_count") or 0
    return {"decode_tok_s": round(n / dur, 1) if dur else 0.0,
            "eval_tokens": n, "seconds": round(time.time() - t0, 1),
            "load_ms": round((last.get("load_duration") or 0) / 1e6),
            "prompt_tokens": last.get("prompt_eval_count")}


def extract_brace_objects(text: str) -> list[str]:
    out, depth, start, in_str, esc = [], 0, -1, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    out.append(text[start:i + 1])
                    start = -1
    return out


def salvage_prose_calls(content: str) -> list[dict]:
    """Mirror of Crown Code's parseJsonToolCalls fallback."""
    found = []
    for cand in extract_brace_objects(content):
        try:
            obj = json.loads(cand)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        fn = obj.get("function")
        if isinstance(fn, dict) and isinstance(fn.get("name"), str):
            args = fn.get("arguments") or fn.get("parameters") or {}
            found.append({"name": fn["name"], "input": args if isinstance(args, dict) else {}})
            continue
        name = obj.get("name") or obj.get("tool") or obj.get("tool_name") or ""
        raw = obj.get("arguments", obj.get("input", obj.get("args", obj.get("parameters"))))
        if isinstance(name, str) and name and raw is not None:
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = {}
            found.append({"name": name, "input": raw if isinstance(raw, dict) else {}})
    return found


def stage_run(model: str, which: str, site: dict, think: bool | None, timeout: int) -> dict:
    prompt = stage_prompt(which, site)
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}],
        "tools": WRITE_TOOLS,
        "stream": True,
        "options": {"num_ctx": 16384, "num_predict": 4096, "temperature": 0.2},
    }
    if think is not None:
        body["think"] = think
    t0 = time.time()
    first_tool = None
    content = ""
    native: list = []
    last: dict = {}
    try:
        with post(CHAT, body, timeout) as resp:
            for raw in resp:
                msg = json.loads(raw.decode("utf-8", "replace"))
                m = msg.get("message") or {}
                content += m.get("content") or ""
                if m.get("tool_calls"):
                    if first_tool is None:
                        first_tool = round(time.time() - t0, 1)
                    native.extend(m["tool_calls"])
                if msg.get("done"):
                    last = msg
                    break
    except Exception as e:  # noqa: BLE001
        return {"stage": which, "error": f"{type(e).__name__}: {e}",
                "seconds": round(time.time() - t0, 1)}

    calls = [{"name": (c.get("function") or {}).get("name"),
              "input": (c.get("function") or {}).get("arguments") or {}}
             for c in native]
    mode = "native"
    if not calls:
        calls = salvage_prose_calls(content)
        mode = "json-as-prose" if calls else "none"

    written = ""
    path = ""
    for c in calls:
        inp = c.get("input")
        if isinstance(inp, str):
            try:
                inp = json.loads(inp)
            except Exception:
                inp = {}
        if not isinstance(inp, dict):
            continue
        if c.get("name") == "write_file":
            written = str(inp.get("content") or "")
            path = str(inp.get("path") or "")
            break

    dur = (last.get("eval_duration") or 0) / 1e9
    n = last.get("eval_count") or 0
    return {
        "stage": which,
        "mode": mode,
        "tool_names": [c.get("name") for c in calls],
        "path": path,
        "written_bytes": len(written),
        "written_lines": written.count("\n") + 1 if written else 0,
        "complete_braces": written.count("{") - written.count("}") == 0 if written else None,
        "seconds": round(time.time() - t0, 1),
        "first_tool_call_s": first_tool,
        "gen_tokens": n,
        "decode_tok_s": round(n / dur, 1) if dur else 0.0,
        "prompt_tokens": last.get("prompt_eval_count"),
        "thinking": bool((last.get("message") or {}).get("thinking")) if last else None,
        "content_chars": len(content),
        "content_head": content[:160].replace("\n", " "),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument("--stages", nargs="*", default=["charts"],
                    help="stages to test compliance on (default: charts — the hardest)")
    ap.add_argument("--site", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--skip-speed", action="store_true")
    args = ap.parse_args()

    models = args.models or ["qwen2.5-coder:3b", "qwen3.5:4b", "qwen2.5-coder:7b", "deepseek-r1:8b"]
    site = SITES[args.site - 1]
    results = []

    for model in models:
        caps = capabilities(model)
        think = think_flag(caps)
        row: dict = {"model": model, "think": think, "capabilities": caps}
        print(f"\n########## {model} (capabilities={caps} think={think}) ##########", flush=True)
        if not args.skip_speed:
            try:
                row["speed"] = decode_speed(model, think)
                print(f"  speed: {row['speed']}", flush=True)
            except Exception as e:  # noqa: BLE001
                row["speed"] = {"error": f"{type(e).__name__}: {e}"}
                print(f"  speed: ERROR {row['speed']}", flush=True)
        for which in args.stages:
            r = stage_run(model, which, site, think, args.timeout)
            row.setdefault("stages", {})[which] = r
            print(f"  stage {which}: {json.dumps(r)[:600]}", flush=True)
        results.append(row)

    out = BASE_DIR / "crown_sites" / "model_bench.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwritten {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
