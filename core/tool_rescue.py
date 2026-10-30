"""
core/tool_rescue.py — Tool-call rescue layer for weak local LLMs.

When a local model narrates its tool call as text instead of calling it,
or produces malformed JSON, this module:
1. Validates tool-call arguments against the declared schema
2. Extracts embedded JSON tool calls from plain text
3. Retries with the error message prepended to context
Inspired by filthyrake/filthy-tool-fixer and community Ollama testing notes.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional


def extract_json_from_text(text: str) -> Optional[dict]:
    """Try to extract a JSON object from narrated text."""
    # Try to find JSON object in text
    patterns = [
        r'```json\s*(\{.*?\})\s*```',
        r'```\s*(\{.*?\})\s*```',
        r'(\{[^{}]*"name"[^{}]*"arguments"[^{}]*\})',
        r'(\{[^{}]*"tool"[^{}]*\})',
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    # Last resort: find any JSON object
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def validate_tool_call(call: dict, schema: dict) -> tuple[bool, str]:
    """Validate a tool call dict against its schema. Returns (valid, error_msg)."""
    if not isinstance(call, dict):
        return False, "Tool call must be a dict"
    name = call.get("name") or call.get("tool")
    if not name:
        return False, "Tool call missing 'name' field"
    args = call.get("arguments") or call.get("args") or call.get("parameters") or {}
    if not isinstance(args, dict):
        try:
            args = json.loads(args) if isinstance(args, str) else {}
        except Exception:
            args = {}
    # Check required fields if schema provided
    if schema:
        required = schema.get("required", [])
        missing = [r for r in required if r not in args]
        if missing:
            return False, f"Missing required arguments: {missing}"
    return True, ""


def rescue_tool_call(
    model_output: str,
    expected_tool_name: Optional[str] = None,
    schema: Optional[dict] = None,
) -> Optional[dict]:
    """
    Try to extract and validate a tool call from model text output.
    Returns normalised {'name': ..., 'arguments': {...}} or None.
    """
    extracted = extract_json_from_text(model_output)
    if not extracted:
        return None
    # Normalise different field naming conventions
    name = extracted.get("name") or extracted.get("tool") or extracted.get("function")
    args = (extracted.get("arguments") or extracted.get("args")
            or extracted.get("parameters") or extracted.get("input") or {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    if not name:
        return None
    if expected_tool_name and name != expected_tool_name:
        return None
    normalised = {"name": name, "arguments": args}
    if schema:
        valid, _ = validate_tool_call(normalised, schema)
        if not valid:
            return None
    return normalised


def make_rescue_context(error: str, last_output: str, tool_schema: dict) -> str:
    """Build a retry context message when a tool call fails or was narrated."""
    return (
        f"The previous tool call failed or was not formatted correctly.\n"
        f"Error: {error}\n"
        f"Your previous output was:\n{last_output[:500]}\n\n"
        f"Please call the tool properly. The tool schema is:\n"
        f"{json.dumps(tool_schema, indent=2)}\n"
        f"Call it now using the proper tool-call format."
    )
