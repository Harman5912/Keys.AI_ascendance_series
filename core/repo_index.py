"""Local repository intelligence — inventory, symbols, imports, targeted search.

The audit found no code intelligence anywhere in KEYS.AI: file discovery was
``Path.rglob`` plus substring matching, with no idea what a file *defines*, what
imports what, or which files matter. An agent editing a project therefore had to
read whole trees blindly.

This module builds a small, refreshable index using the standard library only —
no new dependency, no embedding API, no vector database:

    * a file inventory that skips build output, virtualenvs, caches and
      credentials;
    * Python symbols (module, class, function, method) with line numbers,
      parsed with ``ast`` — never by importing the code;
    * an import graph for local modules, so "who uses this?" is answerable;
    * targeted content search that reports the enclosing symbol, not just a
      grep line.

Scope: Python is parsed structurally; other languages get inventory, size and
text search only. That is deliberate — a half-working JavaScript parser would be
worse than an honest inventory.

Secrets: paths that carry credentials (``.env``, ``api_keys.json``,
``secrets.enc``, private keys, ``config/certs``) are never inventoried, never
searched and never read.
"""

from __future__ import annotations

import ast
import fnmatch
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

# ── filters ───────────────────────────────────────────────────────────────
DEFAULT_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", "target",
    ".idea", ".vscode", "site-packages", ".tox", ".next", ".cache",
    "dist-headless", "coverage", "htmlcov", ".gradle", ".dart_tool",
}

# Never indexed, never searched, never read.
SECRET_PATTERNS = (
    ".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12", "id_rsa*",
    "id_ed25519*", "api_keys.json", "secrets.enc", "*.corrupt-*.json",
    "credentials*", "*.netrc", "token.json",
)

SECRET_DIRS = {"certs", ".ssh", ".aws", ".gnupg"}

TEXT_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".txt", ".yml",
    ".yaml", ".toml", ".ini", ".cfg", ".html", ".css", ".scss", ".sql", ".sh",
    ".bat", ".ps1", ".java", ".kt", ".go", ".rs", ".rb", ".php", ".cs", ".c",
    ".h", ".cpp", ".hpp", ".vue", ".svelte",
}

LANGUAGES = {
    ".py": "python", ".pyi": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".html": "html", ".css": "css",
    ".scss": "css", ".json": "json", ".md": "markdown", ".sql": "sql",
    ".yml": "yaml", ".yaml": "yaml", ".sh": "shell", ".bat": "shell",
    ".ps1": "powershell", ".java": "java", ".kt": "kotlin", ".go": "go",
    ".rs": "rust", ".rb": "ruby", ".php": "php", ".cs": "csharp", ".c": "c",
    ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".vue": "vue", ".svelte": "svelte",
}

MAX_FILE_BYTES = 2_000_000        # skip anything larger than this
MAX_INDEXED_FILES = 20_000
MAX_SEARCH_BYTES = 400_000        # per-file cap while searching


def is_secret_path(path: str | Path) -> bool:
    """True for paths that must never be indexed or read into context."""
    p = Path(path)
    parts = {part.lower() for part in p.parts}
    if parts & SECRET_DIRS:
        return True
    name = p.name.lower()
    return any(fnmatch.fnmatch(name, pat) for pat in SECRET_PATTERNS)


# ── data model ────────────────────────────────────────────────────────────
@dataclass
class FileEntry:
    path: str                     # POSIX-style, relative to the root
    size: int = 0
    language: str = ""
    mtime: float = 0.0
    is_test: bool = False
    lines: int = 0

    def as_dict(self) -> dict:
        return {"path": self.path, "size": self.size, "language": self.language,
                "lines": self.lines, "is_test": self.is_test}


@dataclass
class Symbol:
    name: str
    kind: str                     # module | class | function | method
    path: str
    line: int = 0
    parent: str = ""
    doc: str = ""

    def qualified(self) -> str:
        return f"{self.parent}.{self.name}" if self.parent else self.name

    def as_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "path": self.path,
                "line": self.line, "parent": self.parent}


@dataclass
class RepoIndex:
    root: Path
    files: dict[str, FileEntry] = field(default_factory=dict)
    symbols: list[Symbol] = field(default_factory=list)
    imports: dict[str, list[str]] = field(default_factory=dict)   # file -> modules
    built_at: float = 0.0
    skipped: int = 0

    # ── queries ──────────────────────────────────────────────────────────
    def find_symbol(self, name: str, limit: int = 40) -> list[Symbol]:
        needle = (name or "").strip().lower()
        if not needle:
            return []
        exact = [s for s in self.symbols if s.name.lower() == needle]
        if exact:
            return exact[:limit]
        return [s for s in self.symbols if needle in s.name.lower()][:limit]

    def who_imports(self, module: str, limit: int = 60) -> list[str]:
        """Files that import ``module`` (dotted or basename form)."""
        needle = (module or "").strip()
        if not needle:
            return []
        base = needle.rsplit(".", 1)[-1]
        out = []
        for path, mods in self.imports.items():
            for mod in mods:
                tail = mod.rsplit(".", 1)[-1]
                if mod == needle or tail == needle or tail == base:
                    out.append(path)
                    break
        return out[:limit]

    def tests(self) -> list[FileEntry]:
        return [f for f in self.files.values() if f.is_test]

    def by_language(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.files.values():
            if f.language:
                counts[f.language] = counts.get(f.language, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def summary(self, max_files: int = 12) -> str:
        """Short natural-language description for a model or a log line."""
        langs = ", ".join(f"{k} {v}" for k, v in list(self.by_language().items())[:4])
        lines = [
            f"Repository: {self.root}",
            f"Files indexed: {len(self.files)}"
            + (f" ({self.skipped} skipped)" if self.skipped else ""),
            f"Languages: {langs or 'unknown'}",
            f"Python symbols: {len(self.symbols)} · test files: {len(self.tests())}",
        ]
        biggest = sorted(self.files.values(), key=lambda f: -f.lines)[:max_files]
        if biggest:
            lines.append("Largest files:")
            for f in biggest:
                lines.append(f"  - {f.path} ({f.lines} lines)")
        return "\n".join(lines)

    def context_for(self, path: str, max_chars: int = 4000) -> str:
        """A compact view of one file: its symbols and imports (not contents)."""
        entry = self.files.get(path)
        if entry is None:
            return f"{path} is not indexed."
        syms = [s for s in self.symbols if s.path == path]
        parts = [f"{path} ({entry.language or 'text'}, {entry.lines} lines)"]
        if self.imports.get(path):
            parts.append("imports: " + ", ".join(self.imports[path][:12]))
        if syms:
            parts.append("defines:")
            for s in syms[:40]:
                parts.append(f"  {s.kind} {s.qualified()} (line {s.line})")
        return "\n".join(parts)[:max_chars]


# ── building ──────────────────────────────────────────────────────────────
def _language_for(path: Path) -> str:
    return LANGUAGES.get(path.suffix.lower(), "")


def _is_test_path(rel: str) -> bool:
    p = rel.lower()
    name = Path(rel).name.lower()
    return (name.startswith("test_") or name.endswith(("_test.py", ".test.js",
            ".test.ts", ".spec.js", ".spec.ts"))
            or "/tests/" in f"/{p}" or p.startswith("tests/"))


def _python_symbols(rel: str, source: str) -> tuple[list[Symbol], list[str]]:
    """Parse classes/functions/imports without executing the module."""
    symbols: list[Symbol] = []
    imports: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return symbols, imports

    module = Path(rel).stem
    doc = (ast.get_docstring(tree) or "").strip().splitlines()
    symbols.append(Symbol(name=module, kind="module", path=rel, line=1,
                          doc=doc[0][:160] if doc else ""))

    # Imports are collected from the whole tree, not just the module body:
    # this codebase imports most heavy dependencies lazily inside functions, and
    # a top-level-only scan reported that nothing imported anything.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.extend(_imports_of(node))

    for node in tree.body:
        if isinstance(node, (ast.ClassDef,)):
            symbols.append(Symbol(name=node.name, kind="class", path=rel,
                                  line=node.lineno,
                                  doc=_first_doc_line(node)))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(Symbol(name=sub.name, kind="method", path=rel,
                                          line=sub.lineno, parent=node.name,
                                          doc=_first_doc_line(sub)))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(Symbol(name=node.name, kind="function", path=rel,
                                  line=node.lineno, doc=_first_doc_line(node)))

    # de-duplicate while keeping declaration order
    seen: set[str] = set()
    unique: list[str] = []
    for module_name in imports:
        if module_name not in seen:
            seen.add(module_name)
            unique.append(module_name)
    return symbols, unique


def _first_doc_line(node) -> str:
    doc = ast.get_docstring(node) or ""
    return doc.strip().splitlines()[0][:160] if doc.strip() else ""


def _imports_of(node) -> list[str]:
    """Module names a node imports.

    ``from core import config_store`` is recorded as both ``core`` and
    ``core.config_store``; without the second form "who imports config_store?"
    answered nothing, because the module name only appears in the names list.
    """
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom):
        base = node.module or ""
        if node.level:                     # relative import
            prefix = "." * node.level
            root = f"{prefix}{base}" if base else prefix
            mods = [root]
            for a in node.names:
                if a.name != "*":
                    mods.append(f"{root}.{a.name}" if base else f"{prefix}{a.name}")
            return mods
        if not base:
            return []
        mods = [base]
        for a in node.names:
            if a.name != "*":
                mods.append(f"{base}.{a.name}")
        return mods
    return []


def build(root: str | Path, *, max_files: int = MAX_INDEXED_FILES,
          follow_symlinks: bool = False) -> RepoIndex:
    """Walk ``root`` and index it. Never raises on unreadable paths."""
    root_path = Path(root).expanduser().resolve()
    index = RepoIndex(root=root_path, built_at=time.time())

    for dirpath, dirnames, filenames in os.walk(root_path,
                                                followlinks=follow_symlinks):
        # prune in place so os.walk does not descend into build output, and
        # does not walk hidden directories except the CI one people keep code in
        dirnames[:] = [
            d for d in dirnames
            if d.lower() not in DEFAULT_IGNORE_DIRS
            and (not d.startswith(".") or d == ".github")
        ]

        for name in filenames:
            if len(index.files) >= max_files:
                index.skipped += 1
                continue
            full = Path(dirpath) / name
            try:
                rel = full.relative_to(root_path).as_posix()
            except ValueError:
                continue
            if is_secret_path(rel) or is_secret_path(full):
                index.skipped += 1
                continue
            try:
                stat = full.stat()
            except OSError:
                index.skipped += 1
                continue
            if stat.st_size > MAX_FILE_BYTES:
                index.skipped += 1
                continue
            lang = _language_for(full)
            entry = FileEntry(path=rel, size=stat.st_size, language=lang,
                              mtime=stat.st_mtime, is_test=_is_test_path(rel))
            if lang in ("python",) or full.suffix.lower() in TEXT_SUFFIXES:
                try:
                    text = full.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                entry.lines = text.count("\n") + (1 if text else 0)
                if lang == "python":
                    syms, mods = _python_symbols(rel, text)
                    index.symbols.extend(syms)
                    if mods:
                        index.imports[rel] = mods
            index.files[rel] = entry

    index.symbols.sort(key=lambda s: (s.path, s.line))
    return index


# ── search ────────────────────────────────────────────────────────────────
@dataclass
class Hit:
    path: str
    line: int
    text: str
    symbol: str = ""

    def as_dict(self) -> dict:
        return {"path": self.path, "line": self.line, "text": self.text,
                "symbol": self.symbol}


def search(index: RepoIndex, pattern: str, *, regex: bool = False,
           case_sensitive: bool = False, limit: int = 60,
           language: str = "") -> list[Hit]:
    """Search indexed text files; each hit names its enclosing symbol."""
    if not pattern:
        return []
    try:
        rx = re.compile(pattern if regex else re.escape(pattern),
                        0 if case_sensitive else re.IGNORECASE)
    except re.error:
        return []

    by_file: dict[str, list[Symbol]] = {}
    for sym in index.symbols:
        by_file.setdefault(sym.path, []).append(sym)

    hits: list[Hit] = []
    for rel, entry in index.files.items():
        if language and entry.language != language:
            continue
        if not entry.language:
            continue
        full = index.root / rel
        try:
            if full.stat().st_size > MAX_SEARCH_BYTES:
                continue
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append(Hit(path=rel, line=lineno, text=line.strip()[:200],
                                symbol=_enclosing(by_file.get(rel, []), lineno)))
                if len(hits) >= limit:
                    return hits
    return hits


def _enclosing(symbols: list[Symbol], lineno: int) -> str:
    best = ""
    best_line = -1
    for sym in symbols:
        if sym.line <= lineno and sym.line > best_line:
            best, best_line = sym.qualified(), sym.line
    return best


def format_hits(hits: list[Hit], limit: int = 25) -> str:
    if not hits:
        return "No matches."
    lines = []
    for h in hits[:limit]:
        where = f"{h.path}:{h.line}"
        if h.symbol:
            where += f" (in {h.symbol})"
        lines.append(f"{where}\n    {h.text}")
    if len(hits) > limit:
        lines.append(f"… {len(hits) - limit} more")
    return "\n".join(lines)


__all__ = ["RepoIndex", "FileEntry", "Symbol", "Hit", "build", "search",
           "format_hits", "is_secret_path", "DEFAULT_IGNORE_DIRS"]
