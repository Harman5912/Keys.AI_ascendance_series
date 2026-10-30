"""GitHub repository inspection over the public REST API.

The research worker needs facts about a repository — its license, its README,
its release dates and, crucially, the actual source files — rather than a
model's memory of the project. This module reads them from GitHub itself:

* repository metadata (description, stars, pushed date, default branch);
* the declared license (SPDX id) and the LICENSE file when present;
* the README as rendered text;
* the three most relevant code files, fetched from the tree;
* the latest releases with their publication dates.

Every returned fact carries the API URL it came from, so a report can cite it.
No token is required for public repositories; an optional token is read from
the app's existing config (``github_token``) and never logged. A rate-limited or
missing repository is reported as an explicit failure — never as "empty".

``get`` is injectable so tests exercise the real parsing against recorded API
responses without touching the network.
"""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.request

API_ROOT = "https://api.github.com"
_REPO_URL = re.compile(
    r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
# Files worth reading when a repository is inspected: configuration and entry
# points describe a project far better than whichever file sorts first.
_PRIORITY = (
    "package.json", "pyproject.toml", "requirements.txt", "setup.py",
    "Cargo.toml", "go.mod", "pom.xml", "composer.json", "Dockerfile",
    "main.py", "app.py", "index.js", "index.ts", "src/main.py",
    "src/index.ts", "src/App.tsx", "LICENSE", "LICENSE.md",
)
_CODE_EXT = (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
             ".rb", ".php", ".cs", ".c", ".cpp", ".h")


class GitHubError(RuntimeError):
    """A repository could not be inspected; the message is user-facing."""


def parse_repo(url: str) -> tuple[str, str] | None:
    """``(owner, repo)`` for a github.com URL, else ``None``."""
    match = _REPO_URL.search(str(url or ""))
    if not match:
        return None
    owner, repo = match.group(1), match.group(2)
    repo = repo[:-4] if repo.endswith(".git") else repo
    if owner.lower() in ("orgs", "users", "topics", "search", "features"):
        return None
    return owner, repo


def _token() -> str:
    """Optional token from the app config. Never included in output."""
    try:
        from core.api_config import load_api_config
        value = (load_api_config() or {}).get("github_token") or ""
        return str(value).strip()
    except Exception:
        return ""


def _get_json(url: str, timeout: float = 15.0) -> dict:
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "KeysAI-UniversalAgent"}
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read(2_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise GitHubError(
                "GitHub answered 404: the repository is missing or private."
            ) from exc
        if exc.code in (403, 429):
            raise GitHubError(
                "GitHub rate-limited this request (HTTP "
                f"{exc.code}). Try again later or configure a token."
            ) from exc
        raise GitHubError(f"GitHub answered HTTP {exc.code} for {url}") from exc
    except Exception as exc:
        raise GitHubError(f"GitHub could not be reached: {exc}") from exc


def _decode(blob: dict) -> str:
    content = str(blob.get("content") or "")
    if not content:
        return ""
    try:
        raw = base64.b64decode(content, validate=False)
    except Exception:
        return ""
    return raw.decode("utf-8", "replace")


def _interesting(paths: list[str], limit: int) -> list[str]:
    by_lower = {p.lower(): p for p in paths}
    chosen: list[str] = []
    for wanted in _PRIORITY:
        actual = by_lower.get(wanted.lower())
        if actual and actual not in chosen:
            chosen.append(actual)
        if len(chosen) >= limit:
            return chosen
    for path in sorted(paths):
        low = path.lower()
        if any(part in low for part in ("node_modules/", ".venv/", "test/",
                                        "tests/", "docs/")):
            continue
        if low.endswith(_CODE_EXT) and path not in chosen:
            chosen.append(path)
        if len(chosen) >= limit:
            break
    return chosen


def inspect(url: str, *, get=None, max_files: int = 3) -> dict:
    """Inspect one public repository.

    Returns ``{"ok", "repo", "evidence", "warnings", "error"}``. ``evidence``
    items use the research worker's shape so they can be merged directly.
    ``get`` defaults to the live HTTP reader; resolving it here (rather than as
    a default argument) keeps the module patchable in tests.
    """
    get = get or _get_json
    parsed = parse_repo(url)
    if parsed is None:
        return {"ok": False, "repo": {}, "evidence": [], "warnings": [],
                "error": f"'{url}' is not a GitHub repository URL."}
    owner, name = parsed
    base = f"{API_ROOT}/repos/{owner}/{name}"
    result = {"ok": False, "repo": {"owner": owner, "name": name,
                                    "url": f"https://github.com/{owner}/{name}"},
              "evidence": [], "warnings": [], "error": ""}
    retrieved = time.strftime("%Y-%m-%d %H:%M:%S")

    def fact(claim: str, source: str, title: str, quote: str = "") -> None:
        result["evidence"].append({
            "claim": claim[:400],
            "quote": (quote or claim)[:400],
            "source_url": source,
            "title": title,
            "retrieved_at": retrieved,
            "verified": True,
            "method": "github api",
        })

    try:
        meta = get(base)
    except GitHubError as exc:
        result["error"] = str(exc)
        return result
    except Exception as exc:                      # pragma: no cover - defensive
        result["error"] = f"GitHub could not be reached: {exc}"
        return result

    if not isinstance(meta, dict):
        result["error"] = "GitHub returned an unexpected response."
        return result

    repo = result["repo"]
    repo.update({
        "description": str(meta.get("description") or ""),
        "stars": int(meta.get("stargazers_count") or 0),
        "forks": int(meta.get("forks_count") or 0),
        "language": str(meta.get("language") or ""),
        "branch": str(meta.get("default_branch") or "main"),
        "pushed_at": str(meta.get("pushed_at") or ""),
        "archived": bool(meta.get("archived")),
        "topics": list(meta.get("topics") or [])[:10],
        "html_url": str(meta.get("html_url") or repo["url"]),
    })
    license_info = meta.get("license") or {}
    repo["license"] = str(license_info.get("spdx_id") or "NOASSERTION")
    repo["license_name"] = str(license_info.get("name") or "")

    fact(f"{owner}/{name} is described as: {repo['description'] or 'no description'}.",
         base, f"{owner}/{name} metadata")
    if repo["license"] not in ("", "NOASSERTION", "None"):
        fact(f"{owner}/{name} declares the {repo['license']} license.",
             base, f"{owner}/{name} license")
    else:
        result["warnings"].append(
            f"{owner}/{name} declares no recognised license; check the LICENSE "
            "file before reusing its code.")
        fact(f"{owner}/{name} declares no recognised license.", base,
             f"{owner}/{name} license")
    if repo["pushed_at"]:
        fact(f"The repository was last pushed to at {repo['pushed_at']}.",
             base, f"{owner}/{name} activity")
    if repo["archived"]:
        result["warnings"].append(
            f"{owner}/{name} is archived by its owner — treat it as unmaintained.")

    try:
        readme = get(f"{base}/readme")
        text = _decode(readme if isinstance(readme, dict) else {})
        if text.strip():
            repo["readme_name"] = str(readme.get("name") or "README")
            repo["readme"] = text[:8000]
            first = " ".join(
                line.strip("# ").strip()
                for line in text.splitlines()[:12] if line.strip())
            fact(f"The README says: {first[:300]}",
                 f"{repo['html_url']}/blob/{repo['branch']}/{repo['readme_name']}",
                 repo["readme_name"], first[:400])
        else:
            result["warnings"].append("The repository has no readable README.")
    except GitHubError as exc:
        result["warnings"].append(f"README unavailable: {exc}")

    try:
        tree = get(f"{base}/git/trees/{repo['branch']}?recursive=1")
        paths = [str(node.get("path") or "") for node in (tree.get("tree") or [])
                 if node.get("type") == "blob"]
        repo["file_count"] = len(paths)
        result["files"] = []
        for path in _interesting(paths, max_files):
            try:
                blob = get(f"{base}/contents/{path}")
                text = _decode(blob if isinstance(blob, dict) else {})
            except GitHubError as exc:
                result["warnings"].append(f"{path} could not be read: {exc}")
                continue
            if not text.strip():
                continue
            result["files"].append({"path": path, "text": text[:6000]})
            snippet = next((ln.strip() for ln in text.splitlines()
                            if len(ln.strip()) >= 30), text.strip()[:120])
            fact(f"{path} contains: {snippet[:240]}",
                 f"{repo['html_url']}/blob/{repo['branch']}/{path}", path,
                 snippet[:400])
    except GitHubError as exc:
        result["warnings"].append(f"The file tree was unavailable: {exc}")
        result["files"] = []

    try:
        releases = get(f"{base}/releases?per_page=3")
        result["releases"] = []
        for rel in (releases or [])[:3] if isinstance(releases, list) else []:
            entry = {"tag": str(rel.get("tag_name") or ""),
                     "published_at": str(rel.get("published_at") or ""),
                     "name": str(rel.get("name") or "")}
            result["releases"].append(entry)
            if entry["tag"]:
                fact(f"Release {entry['tag']} was published at "
                     f"{entry['published_at'] or 'an unrecorded date'}.",
                     f"{repo['html_url']}/releases", "Releases")
        if not result["releases"]:
            result["warnings"].append("No published releases were found.")
    except GitHubError as exc:
        result["warnings"].append(f"Releases were unavailable: {exc}")
        result["releases"] = []

    result["ok"] = True
    return result


def report_section(report: dict) -> str:
    """Markdown block describing an inspected repository."""
    repo = report.get("repo") or {}
    if not repo:
        return ""
    lines = [f"### {repo.get('owner')}/{repo.get('name')}", ""]
    lines.append(f"- URL: {repo.get('html_url') or repo.get('url')}")
    if repo.get("description"):
        lines.append(f"- Description: {repo['description']}")
    lines.append(f"- License: {repo.get('license', 'unknown')}"
                 + (f" ({repo['license_name']})" if repo.get("license_name") else ""))
    if repo.get("language"):
        lines.append(f"- Primary language: {repo['language']}")
    lines.append(f"- Stars / forks: {repo.get('stars', 0)} / {repo.get('forks', 0)}")
    if repo.get("pushed_at"):
        lines.append(f"- Last push: {repo['pushed_at']}")
    if repo.get("archived"):
        lines.append("- Archived: yes (unmaintained)")
    if repo.get("file_count"):
        lines.append(f"- Files in the tree: {repo['file_count']}")
    if report.get("files"):
        lines.append("- Files inspected: " + ", ".join(
            f"`{f['path']}`" for f in report["files"]))
    if report.get("releases"):
        lines.append("- Releases: " + ", ".join(
            f"{r['tag']} ({r['published_at'][:10] or 'undated'})"
            for r in report["releases"]))
    return "\n".join(lines)


__all__ = ["GitHubError", "parse_repo", "inspect", "report_section"]
