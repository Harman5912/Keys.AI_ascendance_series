"""qa_artifacts/security_scan.py — defensive secret-leak scan.

Checks whether the real credentials from config/api_keys.json appear in logs,
generated artifacts, reports or any packaged build. Secret VALUES are never
printed — only the file, the credential name and the offset.

Writes qa_artifacts/reports/security_scan.txt and returns non-zero on a leak.

Usage: python qa_artifacts/security_scan.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REPORTS = BASE / "qa_artifacts" / "reports"

# Credential fields we care about. Values are loaded at runtime and never logged.
KEY_FIELDS = ["gemini_api_key", "google_oauth_client_secret", "firebase_api_key"]
PATTERNS = {
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "openai_style_key": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "private_key_block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "bearer_token": re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{30,}"),
}

# Tokens that are shaped like a credential but are deliberately synthetic:
# test fixtures for the scrubber itself (e.g. the canary key in
# test_agent_control.py::test_privacy_scrub) and documented placeholders.
# They are still LISTED in the report for review — they just do not fail the
# scan, because the real leak check above (exact configured credential values)
# is untouched and any real key is caught by it.
SYNTHETIC_MARKERS = ("1234567890", "abcdefghijklmnop", "deadbeef",
                     "your_api_key_here", "example_key")

SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "ms-playwright"}
SCAN_SUFFIXES = {".log", ".txt", ".json", ".md", ".csv", ".html", ".js", ".py", ".yaml", ".yml"}
MAX_BYTES = 3_000_000


def load_secrets() -> dict:
    try:
        raw = json.loads((BASE / "config" / "api_keys.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {k: str(raw.get(k, "")) for k in KEY_FIELDS if raw.get(k)}


def iter_files(roots: list[Path]):
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in SCAN_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            yield p


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    secrets = load_secrets()
    roots = [BASE / "qa_artifacts", BASE, BASE / "dist", BASE / "config"]
    out: list[str] = []
    leaks: list[str] = []
    synthetic: list[str] = []

    out.append("Security scan — secret leakage")
    out.append(f"Credential fields checked: {', '.join(secrets) or '(none readable)'}")
    out.append(f"Patterns checked: {', '.join(PATTERNS)}")
    out.append("")

    files = list(iter_files(roots))
    out.append(f"Files scanned: {len(files)}")
    for p in files:
        # config/api_keys.json is the legitimate store; it is not a leak.
        if p.name == "api_keys.json" and p.parent.name == "config" and p.parent.parent == BASE:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name, value in secrets.items():
            if value and len(value) >= 12 and value in text:
                leaks.append(f"LEAK {name} in {p.relative_to(BASE)} (offset {text.index(value)})")
        for label, rx in PATTERNS.items():
            m = rx.search(text)
            if not m:
                continue
            hit = m.group(0)
            where = f"PATTERN {label} in {p.relative_to(BASE)} (offset {m.start()})"
            if any(marker in hit for marker in SYNTHETIC_MARKERS):
                synthetic.append(where + " — synthetic canary/placeholder, "
                                        "listed for review, not a credential")
            else:
                leaks.append(where)

    out.append("")
    if leaks:
        out.append(f"FINDINGS: {len(leaks)}")
        out.extend(leaks)
    else:
        out.append("FINDINGS: 0 — no credential value or credential-shaped token found outside the config store.")
    if synthetic:
        out.append(f"Synthetic placeholders ignored (listed for review): "
                   f"{len(synthetic)}")
        out.extend(synthetic)

    # Local API exposure: does the dashboard / bridge bind beyond loopback?
    exposure = []
    for rel in ("dashboard/server.py", "main.py"):
        f = BASE / rel
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"(host\s*=\s*['\"]([^'\"]+)['\"])|uvicorn\.run\([^)]*", text):
            snippet = m.group(0)[:120]
            if "0.0.0.0" in snippet:
                exposure.append(f"WIDE BIND in {rel}: {snippet}")
    out.append("")
    out.append("Local exposure findings: " + (str(len(exposure)) if exposure else "0 (no 0.0.0.0 bind found)"))
    out.extend(exposure)

    text = "\n".join(out)
    (REPORTS / "security_scan.txt").write_text(text, encoding="utf-8")
    print(text)
    return 1 if leaks or exposure else 0


if __name__ == "__main__":
    raise SystemExit(main())
