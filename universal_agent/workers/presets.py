"""Research presets — what each named research recipe searches and keeps.

The presets are data, not code: ``config/research_presets.json`` holds the
labels, query templates (``{topic}``), source hints and what to collect, so a
new recipe is a JSON entry rather than a code change. This module only loads
and normalises them, and never raises: a broken or missing file falls back to
the built-in defaults so research still runs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

PRESETS_PATH = (Path(__file__).resolve().parents[2]
                / "config" / "research_presets.json")

# Built-in defaults: the same four presets the shipped JSON file contains, so a
# deleted/edited file can never leave the agent with nothing to run.
DEFAULTS: list[dict] = [
    {
        "id": "github",
        "label": "GitHub research",
        "description": "Find repositories and libraries; read README, licence and API surface.",
        "queries": ["{topic} github repository", "site:github.com {topic}"],
        "source_domains": ["github.com", "raw.githubusercontent.com", "pypi.org"],
        "collect": ["repositories", "code samples", "licences"],
    },
    {
        "id": "docs",
        "label": "Docs / API",
        "description": "Read the official documentation and API reference.",
        "queries": ["{topic} official documentation", "{topic} API reference"],
        "source_domains": ["docs.", "readthedocs.io", "developer.mozilla.org"],
        "collect": ["documented sections", "code samples"],
    },
    {
        "id": "ui_design",
        "label": "UI / design references",
        "description": "Screenshots, palettes and layout notes as references only.",
        "queries": ["{topic} design system components",
                    "{topic} dashboard UI design inspiration"],
        "source_domains": ["tailwindcss.com", "mui.com", "ant.design",
                           "dribbble.com", "behance.net"],
        "collect": ["screenshots", "palette", "layout notes"],
    },
    {
        "id": "national_search",
        "label": "National search",
        "description": "Nationwide web/records search, deduplicated by name.",
        "queries": ["{topic} nationwide directory",
                    "{topic} locations United States"],
        "source_domains": [],
        "collect": ["candidate records", "regions", "source urls"],
    },
]


def _normalise(raw: dict, fallback: dict) -> dict:
    """One preset, with every field present and the right type."""
    merged = dict(fallback)
    merged.update({k: v for k, v in (raw or {}).items() if v is not None})
    merged["id"] = str(merged.get("id") or fallback["id"]).strip().lower()
    merged["label"] = str(merged.get("label") or fallback["label"])
    merged["description"] = str(merged.get("description") or "")
    merged["queries"] = [str(q) for q in (merged.get("queries") or [])
                         if str(q).strip()]
    merged["source_domains"] = [str(d).strip().lower()
                                for d in (merged.get("source_domains") or [])
                                if str(d).strip()]
    merged["collect"] = [str(c) for c in (merged.get("collect") or [])]
    return merged


def load() -> list[dict]:
    """Every preset, file order, defaults filling any gaps. Never raises."""
    by_id = {p["id"]: dict(p) for p in DEFAULTS}
    try:
        raw = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
        entries = raw.get("presets") if isinstance(raw, dict) else raw
    except Exception:
        entries = None
    if isinstance(entries, list):
        ordered: list[dict] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            pid = str(entry.get("id") or "").strip().lower()
            base = by_id.get(pid) or {"id": pid, "label": pid or "Preset"}
            preset = _normalise(entry, base)
            if preset["id"] and preset["id"] not in seen:
                seen.add(preset["id"])
                ordered.append(preset)
        for pid, preset in by_id.items():
            if pid not in seen:
                ordered.append(_normalise(preset, preset))
        if ordered:
            return ordered
    return [_normalise(p, p) for p in DEFAULTS]


def parse(names) -> list[str]:
    """Preset ids from whatever the caller has: list, or comma-separated text.

    Answers saved on a task are stored as strings, so a preset selection can
    come back as ``"github, docs"`` — both forms must land on the same ids.
    """
    if isinstance(names, str):
        names = re.split(r"[,;|\s]+", names)
    out: list[str] = []
    for name in names or []:
        text = str(name or "").strip().lower().replace("-", "_")
        if text and text not in out:
            out.append(text)
    return out


def resolve(names) -> list[dict]:
    """The presets named in `names`, in file order; all of them when empty."""
    wanted = set(parse(names))
    presets = load()
    if not wanted:
        return presets
    return [p for p in presets if p["id"] in wanted]


def ids() -> list[str]:
    return [p["id"] for p in load()]


def queries(preset: dict, topic: str) -> list[str]:
    """This preset's query templates filled in with the topic."""
    text = str(topic or "").strip()
    out: list[str] = []
    for template in preset.get("queries") or []:
        query = template.replace("{topic}", text).strip()
        if query and query not in out:
            out.append(query)
    return out


def prefers(preset: dict, url: str) -> bool:
    """Does this URL belong to one of the preset's source hints?"""
    low = str(url or "").lower()
    return bool(low) and any(domain in low
                            for domain in preset.get("source_domains") or [])


def summary_line(presets: list[dict]) -> str:
    labels = [p.get("label") or p.get("id") for p in presets]
    return ", ".join(str(l) for l in labels) or "no presets"


__all__ = ["PRESETS_PATH", "DEFAULTS", "load", "resolve", "ids", "queries",
           "prefers", "summary_line", "parse"]
