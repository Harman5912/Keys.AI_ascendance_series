"""actions/_extract_json_helpers.py — deterministic JSON extraction helpers.

Local models wrap JSON in prose and fences, emit raw control characters inside
strings, double their quotes, and miss commas. These helpers try a bounded set
of repairs on a bounded set of candidates; they never recurse and never loop.
"""

from __future__ import annotations

import json
import re
from typing import Union


def _strip_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text).rstrip()
    return text


def _escape_controls(text: str) -> str:
    """Escape raw newlines/tabs that appear inside JSON strings."""
    out: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
            elif ch == "\\":
                out.append(ch)
                escaped = True
            elif ch == '"':
                out.append(ch)
                in_string = False
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
    return "".join(out)


def _fix_doubled_quotes(text: str) -> str:
    """Repair `""title":` / `""title"":` key artifacts without touching values."""
    fixed = re.sub(r'"{2,}\s*([A-Za-z_][\w \-]{0,40}?)\s*"{1,2}\s*:', r'"\1":', text)
    return fixed


def _relax_missing_commas(text: str) -> str:
    """Insert a comma where an object member ends and the next key begins."""
    return re.sub(r'("(?:\\.|[^"\\])*")\s+(?="[^"]+"\s*:)', r"\1, ", text)


def _drop_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([\]}])", r"\1", text)


def _candidate_spans(text: str) -> list[str]:
    spans: list[str] = []
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            spans.append(text[start:end + 1])
    return spans


def _candidates(raw: str, opener: str = "[") -> list[str]:
    base = _strip_fences(raw)
    escaped = _escape_controls(base)
    out: list[str] = [base, escaped]
    for source in (base, escaped):
        fixed = _fix_doubled_quotes(source)
        relaxed = _relax_missing_commas(fixed)
        out.extend([fixed, relaxed, _drop_trailing_commas(relaxed)])
        out.extend(_candidate_spans(source))
        out.extend(_candidate_spans(fixed))
        out.extend(_candidate_spans(relaxed))
    return out


def _parse_first(candidates: list[str]) -> Union[list, dict, None]:
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        for transform in (lambda s: s, _drop_trailing_commas,
                          _relax_missing_commas, _fix_doubled_quotes):
            try:
                value = json.loads(transform(candidate))
                if isinstance(value, (list, dict)):
                    return value
            except (json.JSONDecodeError, ValueError, RecursionError):
                continue
    return None


def _extract_json(raw: str, opener: str = "[") -> Union[list, dict]:
    """Extract the first JSON value (array or object) from model output."""
    if not isinstance(raw, str):
        raise ValueError("expected a string")
    value = _parse_first(_candidates(raw, opener))
    if value is not None:
        return value
    raise ValueError("no JSON value found in response")


def _salvage_slides(raw: str) -> list:
    """Best-effort recovery of a slide array from broken local-model output."""
    if not isinstance(raw, str) or "[" not in raw:
        return []
    candidates = _candidates(raw, "[")
    parsed = _parse_first(candidates)
    if parsed is None:
        return []
    source = parsed if isinstance(parsed, list) else [parsed]
    rows: list = []
    for item in source:
        if isinstance(item, dict) and ("title" in item or "content" in item):
            rows.append(item)
    return rows


def _strip_placeholder_lines(text: str) -> str:
    """Drop 'Label: [Your Name]' lines from generated slide content."""
    _PLACEHOLDER_LINE_RE = re.compile(
        r"^\s*[A-Za-z][A-Za-z0-9 _-]*\s*:\s*\[[^\]]*\]\s*$",
        re.M,
    )
    kept = [
        ln
        for ln in (text or "").split("\n")
        if not _PLACEHOLDER_LINE_RE.match(ln)
    ]
    return "\n".join(kept).strip("\n")
