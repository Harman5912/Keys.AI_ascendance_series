"""actions/repo_tool.py — `repo_inspect`: look at a project before changing it.

Wraps ``core.repo_index`` so the assistant can answer "what is in this project",
"where is X defined", "what imports this module" and "find where this string
lives" without reading whole trees blindly.

Read-only. It never writes, never executes project code, and never reads
credentials: the index excludes ``.env``, ``api_keys.json``, ``secrets.enc``,
private keys and ``config/certs`` by path before anything is opened.

Parameters
    action  summary | search | symbol | file | imports | tests   (default summary)
    root    project folder to inspect (default: the assistant's workspace)
    query   text (search), symbol name (symbol), file path (file),
            module name (imports)
    regex   true to treat `query` as a regular expression (search)
    limit   max results (default 40)
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

_MAX_OUT = 6000


def _clip(text: str) -> str:
    text = str(text or "")
    return text if len(text) <= _MAX_OUT else text[:_MAX_OUT] + "\n… (truncated)"


def _resolve_root(root: str, player=None) -> Path | None:
    """The folder to inspect: explicit, else the session workspace, else cwd."""
    candidates = []
    if root:
        candidates.append(root)
    for attr in ("workspace_root", "_workspace", "current_workspace",
                 "creation_workspace"):
        value = getattr(player, attr, None) if player is not None else None
        if isinstance(value, str) and value.strip():
            candidates.append(value)
    candidates.append(str(Path.cwd()))

    for candidate in candidates:
        try:
            path = Path(candidate).expanduser().resolve()
        except Exception:
            continue
        if path.is_dir():
            return path
    return None


def repo_inspect(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "summary").strip().lower()
    query = str(p.get("query") or "").strip()
    limit = int(p.get("limit") or 40)

    from core import repo_index

    root = _resolve_root(str(p.get("root") or ""), player)
    if root is None:
        return ("I could not find a project folder to inspect. Pass `root` with "
                "the path of the project.")

    index = repo_index.build(root)
    if not index.files:
        return f"{root} has no readable source files to inspect."

    if action == "summary":
        return _clip(index.summary())

    if action == "tests":
        tests = index.tests()
        if not tests:
            return f"No test files found under {root}."
        lines = [f"{len(tests)} test file(s) under {root}:"]
        lines += [f"  - {t.path} ({t.lines} lines)" for t in tests[:limit]]
        return _clip("\n".join(lines))

    if action == "symbol":
        if not query:
            return "Pass `query` with the symbol name to look up."
        found = index.find_symbol(query, limit=limit)
        if not found:
            return f"No symbol matching {query!r} in {root}."
        lines = [f"{len(found)} symbol match(es) for {query!r}:"]
        for s in found:
            lines.append(f"  {s.kind} {s.qualified()} — {s.path}:{s.line}")
            if s.doc:
                lines.append(f"      {s.doc}")
        return _clip("\n".join(lines))

    if action == "imports":
        if not query:
            return "Pass `query` with the module name to see what imports it."
        users = index.who_imports(query, limit=limit)
        if not users:
            return f"Nothing under {root} imports {query!r}."
        return _clip(f"{len(users)} file(s) import {query!r}:\n"
                     + "\n".join(f"  - {u}" for u in users))

    if action == "file":
        if not query:
            return "Pass `query` with the file path (relative to the project)."
        rel = query.replace("\\", "/").lstrip("./")
        if repo_index.is_secret_path(rel):
            return "That file holds credentials, so I will not read it."
        if rel not in index.files:
            matches = [f for f in index.files if rel in f][:10]
            if not matches:
                return f"{rel} is not in the index of {root}."
            rel = matches[0]
        return _clip(index.context_for(rel))

    if action == "search":
        if not query:
            return "Pass `query` with the text to look for."
        hits = repo_index.search(index, query,
                                 regex=bool(p.get("regex")),
                                 limit=limit)
        if not hits:
            return f"No matches for {query!r} in {root}."
        return _clip(f"{len(hits)} match(es) for {query!r}:\n"
                     + repo_index.format_hits(hits, limit=limit))

    return (f"Unknown action {action!r}. Use summary, search, symbol, file, "
            "imports or tests.")
