"""Skill: the in-app research browser — open pages, read them, capture them."""

from __future__ import annotations

from skills.builtin._delegate import run_tool, tool_ready

SKILL = {
    "name": "research-browser",
    "purpose": "Browse real pages inside Keys.AI: open a URL, read its text, "
               "take a screenshot, collect sources for research.",
    "version": "1.0.0",
    "group": "research",
    "capabilities": ["open a page", "read page text", "screenshot a page",
                     "list tabs", "close tabs"],
    "tools": ["research_browser"],
    "permission": "SAFE",
    "instructions": "Pages open in the app's own Chromium, so the user watches "
                    "what is being read. Use screenshots when the source "
                    "matters as evidence.",
    "triggers": ["open this page", "read this website", "browse to",
                 "screenshot this page", "research using the browser"],
    "inputs": {
        "action": {"type": "string", "required": True,
                   "description": "open_tab | navigate_to_url | get_current_page "
                                  "| screenshot | list_tabs | close_tab"},
        "url": {"type": "string"},
        "query": {"type": "string"},
    },
    "outputs": ["page text, tab state or a screenshot path"],
    "timeout": 120.0,
    "tags": ["browser", "research", "web"],
}


def run(parameters: dict, ctx) -> dict:
    return run_tool("research_browser", parameters, ctx)


def verify() -> tuple[bool, str]:
    return tool_ready("research_browser")
