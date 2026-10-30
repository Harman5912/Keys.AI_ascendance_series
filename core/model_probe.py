"""
core/model_probe.py — Startup capability probe for local LLMs.

At agent startup, tests whether the configured model:
1. Responds at all (connectivity check)
2. Supports native tool calls (tool_mode=native)
3. Can emit valid JSON on demand (tool_mode=json)
4. Falls back to bash/text-only mode

Inspired by community findings: qwen2.5-coder fails native tool calls
(prints JSON as text), qwen3:8b and devstral-small-2 pass.
"""
from __future__ import annotations

import json
import time
from typing import Optional


_PROBE_CACHE: dict[str, dict] = {}

_TOOL_CALL_TEST = {
    "name": "read_file",
    "description": "Read a file",
    "parameters": {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "File path"}},
        "required": ["path"],
    },
}

_CONNECTIVITY_PROMPT = "Reply with exactly: KEYS_PROBE_OK"
_JSON_MODE_PROMPT = 'Reply with exactly this JSON and nothing else: {"status": "ok", "mode": "json"}'


def probe_model(base_url: str, model: str, timeout: int = 30) -> dict:
    """
    Run a capability probe against a local Ollama model.
    Returns: {
        'reachable': bool,
        'tool_mode': 'native'|'json'|'text',
        'edit_format': 'tools'|'search_replace',
        'elapsed_ms': int,
        'model': str,
    }
    """
    cache_key = f"{base_url}:{model}"
    if cache_key in _PROBE_CACHE:
        return _PROBE_CACHE[cache_key]

    result = {
        "reachable": False,
        "tool_mode": "text",
        "edit_format": "search_replace",
        "elapsed_ms": 0,
        "model": model,
        "error": "",
    }

    try:
        import requests
    except ImportError:
        result["error"] = "requests not installed"
        return result

    t0 = time.monotonic()

    # 1. Connectivity check
    try:
        r = requests.post(
            f"{base_url.rstrip('/')}/api/generate",
            json={"model": model, "prompt": _CONNECTIVITY_PROMPT, "stream": False},
            timeout=timeout,
        )
        r.raise_for_status()
        resp_text = r.json().get("response", "")
        if "KEYS_PROBE_OK" in resp_text:
            result["reachable"] = True
        else:
            result["reachable"] = True  # responded, just different text
    except Exception as e:
        result["error"] = f"connectivity: {e}"
        result["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
        _PROBE_CACHE[cache_key] = result
        return result

    # 2. JSON mode check
    try:
        r = requests.post(
            f"{base_url.rstrip('/')}/api/generate",
            json={
                "model": model,
                "prompt": _JSON_MODE_PROMPT,
                "stream": False,
                "format": "json",
            },
            timeout=timeout,
        )
        r.raise_for_status()
        resp_text = r.json().get("response", "")
        parsed = json.loads(resp_text)
        if parsed.get("status") == "ok":
            result["tool_mode"] = "json"
            result["edit_format"] = "search_replace"
    except Exception:
        pass

    # 3. Native tool-call check (via /api/chat with tools)
    try:
        r = requests.post(
            f"{base_url.rstrip('/')}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Call read_file with path='test.py'"}],
                "tools": [{"type": "function", "function": _TOOL_CALL_TEST}],
                "stream": False,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        msg = r.json().get("message", {})
        tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            result["tool_mode"] = "native"
            result["edit_format"] = "tools"
    except Exception:
        pass

    result["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    _PROBE_CACHE[cache_key] = result
    return result


def get_recommended_edit_format(model_name: str) -> str:
    """
    Return the recommended edit format for known model families.
    Based on community testing: qwen2.5-coder → search_replace, qwen3 → tools.
    """
    mn = model_name.lower()
    if "qwen3" in mn or "devstral" in mn:
        return "tools"
    if "qwen2.5-coder" in mn or "qwen2.5" in mn:
        return "search_replace"
    if "tinyllama" in mn or "phi" in mn:
        return "search_replace"
    return "search_replace"  # safe default
