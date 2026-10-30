"""Skill: files and folders.

Deleting is a MODERATE+ action: the manifest says MODERATE, and the safety layer
escalates any argument containing delete/remove/wipe to DANGEROUS, so the runner
requires approval for exactly those calls and lets reads through.
"""

from __future__ import annotations

from skills.builtin._delegate import run_tool, tool_ready

SKILL = {
    "name": "files",
    "purpose": "List, read, write, move, copy, rename and delete files and "
               "folders on this computer.",
    "version": "1.0.0",
    "group": "documents",
    "capabilities": ["list", "read", "write", "move", "copy", "rename",
                     "delete", "disk usage"],
    "tools": ["file_controller"],
    # SAFE is the *least* privilege: reads and listings. The safety layer
    # escalates any argument containing delete/remove/wipe to DANGEROUS, so
    # those calls ask first without making every listing a confirmation.
    "permission": "SAFE",
    "instructions": "Destructive actions need the user's confirmation — never "
                    "assume it. Reads and listings are cheap.",
    "triggers": ["create a file", "read this file", "move these files",
                 "delete this folder", "what is on my desktop"],
    "inputs": {
        "action": {"type": "string", "required": True,
                   "description": "list | read | write | create_file | "
                                  "create_folder | move | copy | rename | "
                                  "delete | find | disk_usage | info"},
        "path": {"type": "string"},
        "destination": {"type": "string"},
        "new_name": {"type": "string"},
        "content": {"type": "string"},
        "name": {"type": "string"},
        "extension": {"type": "string"},
        "count": {"type": "integer"},
    },
    "outputs": ["file contents, listings or a confirmation of the change"],
    "timeout": 60.0,
    "tags": ["files", "disk"],
}


def run(parameters: dict, ctx) -> dict:
    return run_tool("file_controller", parameters, ctx)


def verify() -> tuple[bool, str]:
    return tool_ready("file_controller")
