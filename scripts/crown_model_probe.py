#!/usr/bin/env python3
"""crown_model_probe.py — talk to Ollama's chat API directly with the real
write_file tool schema, so we can see exactly what a local model does with one
of the harness's stage prompts (thinking tokens, time to first tool call,
whether the tool call ever arrives).

    python scripts/crown_model_probe.py --model qwen3.5:4b --which styles
    python scripts/crown_model_probe.py --model qwen3.5:4b --all
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from crown_websites_demo import (  # noqa: E402
    APP_TASK, DATA_TASK, LAUNCH_TASK, MARKUP_TASK, STYLES_TASK, SITES,
    number_list, render, series_lines,
)

OLLAMA = "http://localhost:11434/api/chat"

TOOLS = [{
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
}]

SYSTEM = ("You are Crown Code, a coding agent working in a real directory on this machine. "
          "Use the provided tools to do the work — never describe work you did not do.")


def site_prompt(which: str, site: dict) -> str:
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
    if which == "app":
        return render(APP_TASK, title=site["title"], domain=site["domain"])
    if which == "launch":
        return render(LAUNCH_TASK, title=site["title"])
    raise SystemExit(f"unknown stage {which}")


def probe(model: str, prompt: str, *, think: bool | None, num_ctx: int, timeout: int) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}],
        "tools": TOOLS,
        "stream": True,
        "options": {"num_ctx": num_ctx, "temperature": 0.2, "num_predict": 4096},
    }
    if think is not None:
        body["think"] = think
    req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"})
    t0 = time.time()
    first_think = first_tool = done_at = None
    chunks = thinking_chars = content_chars = 0
    tool_calls: list = []
    content_sample = ""
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            chunks += 1
            m = msg.get("message") or {}
            think_bit = m.get("thinking") or ""
            if think_bit:
                if first_think is None:
                    first_think = round(time.time() - t0, 1)
                thinking_chars += len(think_bit)
            text = m.get("content") or ""
            if text:
                content_chars += len(text)
                if len(content_sample) < 400:
                    content_sample += text
            if m.get("tool_calls"):
                if first_tool is None:
                    first_tool = round(time.time() - t0, 1)
                tool_calls.extend(m["tool_calls"])
            if msg.get("done"):
                done_at = round(time.time() - t0, 1)
                break
    args_len = 0
    names = []
    for tc in tool_calls:
        fn = (tc.get("function") or {})
        names.append(fn.get("name"))
        args_len += len(str(fn.get("arguments")))
    return {
        "model": model, "stage": None, "think": think, "num_ctx": num_ctx,
        "seconds": done_at or round(time.time() - t0, 1),
        "first_thinking_s": first_think, "first_tool_call_s": first_tool,
        "chunks": chunks, "thinking_chars": thinking_chars, "content_chars": content_chars,
        "tool_calls": len(tool_calls), "tool_names": names, "args_chars": args_len,
        "content_sample": content_sample[:300].replace("\n", " "),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.5:4b")
    ap.add_argument("--which", default="styles")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--think", default="auto", choices=["auto", "on", "off"])
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    think = {"auto": None, "on": True, "off": False}[args.think]
    site = SITES[0]
    which_list = ["styles", "markup", "data", "app", "launch"] if args.all else [args.which]

    for which in which_list:
        prompt = site_prompt(which, site)
        print(f"\n=== {args.model} | stage={which} | think={args.think} | num_ctx={args.num_ctx} "
              f"| prompt_chars={len(prompt)} ===", flush=True)
        try:
            r = probe(args.model, prompt, think=think, num_ctx=args.num_ctx, timeout=args.timeout)
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {type(e).__name__}: {e}", flush=True)
            continue
        r["stage"] = which
        print(json.dumps({k: v for k, v in r.items() if k != "model"}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
