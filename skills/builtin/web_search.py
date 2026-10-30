"""Skill: web search — current facts, news, prices, comparisons."""

from __future__ import annotations

from skills.builtin._delegate import run_tool, tool_ready

SKILL = {
    "name": "web-search",
    "purpose": "Answer from the live web: search, news, prices and "
               "side-by-side comparisons.",
    "version": "1.0.0",
    "group": "research",
    "capabilities": ["search the web", "latest news", "price lookup",
                     "compare products"],
    "tools": ["web_search"],
    "permission": "SAFE",
    "instructions": "Prefer this over guessing. Results carry their URLs, so "
                    "quote them when the user needs a source.",
    "triggers": ["search for", "latest news", "price of", "compare",
                 "what is happening with"],
    "inputs": {
        "query": {"type": "string", "required": True},
        "mode": {"type": "string",
                 "description": "search | news | research | price | compare"},
        "items": {"type": "array"},
        "aspect": {"type": "string"},
    },
    "outputs": ["a written answer with the sources that were read"],
    "timeout": 120.0,
    "tags": ["web", "news", "search"],
}


def run(parameters: dict, ctx) -> dict:
    return run_tool("web_search", parameters, ctx)


def verify() -> tuple[bool, str]:
    return tool_ready("web_search")
