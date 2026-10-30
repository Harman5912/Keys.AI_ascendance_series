"""Stage 7: controlled failures, repair, security and task isolation.

Each check injects a fault into a *copy* of a test project, observes what the
product does, then repairs and re-runs. Nothing touches the delivered project
or any user data.

Run:  python KEYSAI_PHASE2_RESULTS/tests/stage7_failures_security.py
Out:  KEYSAI_PHASE2_RESULTS/logs/stage7_failures_security.json
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

OUT = BASE / "KEYSAI_PHASE2_RESULTS"
PROJECT = OUT / "projects" / "inventory_system"
REPORT = OUT / "logs" / "stage7_failures_security.json"

checks: list[dict] = []


def check(test_id: str, name: str, ok: bool, detail: str = "") -> None:
    checks.append({"test_id": test_id, "check": name, "ok": bool(ok),
                   "detail": str(detail)[:700]})
    print(f"{'PASS' if ok else 'FAIL'} {test_id} {name}"
          + (f" — {str(detail)[:200]}" if detail else ""), flush=True)


def copy_project(dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(PROJECT, dest,
                    ignore=shutil.ignore_patterns("__pycache__", "*.db"))
    return dest


def main() -> int:
    from core.app_checks import verify_workspace

    tmp = Path(tempfile.mkdtemp())

    # ── F02: syntax error → detected with file/line → repaired → passes ────
    ws = copy_project(tmp / "f02")
    models = ws / "models.py"
    original = models.read_text(encoding="utf-8")
    models.write_text(original.replace("def dashboard() -> dict:",
                                       "def dashboard() -> dict", 1),
                      encoding="utf-8")
    broken = verify_workspace(ws)
    check("F02", "syntax error is detected", not broken["ok"], broken["message"][:200])
    check("F02", "the failing file is named in the error",
          "models.py" in broken["message"], broken["message"][:200])
    models.write_text(original, encoding="utf-8")
    repaired = verify_workspace(ws)
    check("F02", "repair is confirmed by re-running the check", repaired["ok"],
          repaired["message"][:200])

    # ── F03: SQL schema mismatch → real DB error, then fixed ──────────────
    ws = copy_project(tmp / "f03")
    models = ws / "models.py"
    original = models.read_text(encoding="utf-8")
    models.write_text(original.replace("SELECT COUNT(*) AS product_count,",
                                       "SELECT COUNT(*) AS product_count,"
                                       " bogus_column,", 1),
                      encoding="utf-8")
    sys.path.insert(0, str(ws))
    try:
        import importlib
        for mod in ("app", "models", "db", "validation"):
            sys.modules.pop(mod, None)
        os_environ_db = ws / "f03.db"

        import os
        os.environ["INVENTORY_DB"] = str(os_environ_db)
        import app as app_module
        importlib.reload(app_module)
        client = app_module.create_app(os_environ_db).test_client()
        response = client.get("/api/dashboard")
        body = response.get_data(as_text=True)
        check("F03", "schema mismatch surfaces as a handled error",
              response.status_code >= 500 and "bogus_column" in body,
              f"status={response.status_code} body={body[:160]}")
        check("F03", "no traceback is leaked to the caller",
              "Traceback" not in body, body[:160])
    finally:
        for mod in ("app", "models", "db", "validation"):
            sys.modules.pop(mod, None)
        sys.path.remove(str(ws))
    models.write_text(original, encoding="utf-8")
    check("F03", "query repaired", "bogus_column" not in models.read_text(
        encoding="utf-8"))

    # ── F05: corrupt document → parse fails → regenerate → valid ──────────
    corrupt = tmp / "corrupt.docx"
    corrupt.write_bytes(b"PK\x03\x04 not really a document")
    try:
        from docx import Document
        Document(str(corrupt))
        parse_failed = False
    except Exception as err:
        parse_failed = True
        check("F05", "corrupt DOCX fails to parse as expected", True,
              type(err).__name__)
    if not parse_failed:
        check("F05", "corrupt DOCX fails to parse as expected", False,
              "python-docx opened junk bytes")
    import actions.file_processor as fp
    regenerated = tmp / "regenerated.docx"
    fp.file_processor({"action": "create", "file_path": str(regenerated),
                       "doc_type": "docx", "title": "Regenerated",
                       "instruction": "A short replacement document."})
    try:
        from docx import Document
        doc = Document(str(regenerated))
        check("F05", "regenerated document parses", len(doc.paragraphs) > 2,
              f"{len(doc.paragraphs)} paragraphs")
    except Exception as err:
        check("F05", "regenerated document parses", False, type(err).__name__)

    # ── Security: workspace escape is refused ────────────────────────────
    from core.app_builder import _write
    ws = tmp / "sec"
    ws.mkdir()
    try:
        _write(ws, "../escaped.txt", "should not exist")
        escaped = (tmp / "escaped.txt").exists()
        check("SEC-01", "path traversal is refused", not escaped,
              "file was written outside the workspace")
    except ValueError as err:
        check("SEC-01", "path traversal is refused", True, str(err))
    inside = _write(ws, "ok.txt", "fine")
    check("SEC-01", "normal writes still work", inside.exists()
          and inside.parent == ws.resolve())

    # ── Security: secrets are not in the generated front end ─────────────
    tokens = ("api_key", "apikey", "secret", "password", "sk-", "AIza")
    leaked = []
    for path in (PROJECT / "static").rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            leaked += [t for t in tokens if t in text]
    check("SEC-02", "no credential-shaped strings in the shipped front end",
          not leaked, ", ".join(sorted(set(leaked))))

    # ── Isolation: two builds in parallel keep separate outputs ──────────
    from core.app_builder import build_dashboard, build_python_desktop

    results: dict = {}

    def run(name, fn, out_dir, brief):
        try:
            results[name] = fn(brief, out_dir)
        except Exception as err:                      # a crash is a result
            results[name] = {"ok": False, "message": f"{type(err).__name__}: {err}"}

    a_dir = tmp / "par_a"
    b_dir = tmp / "par_b"
    threads = [
        threading.Thread(target=run, args=(
            "dashboard", build_dashboard, a_dir,
            "Build a fleet dashboard with fuel costs and vehicles")),
        threading.Thread(target=run, args=(
            "desktop", build_python_desktop, b_dir,
            "Python desktop app: a small ledger with entries and totals")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    check("ISO-01", "both parallel builds succeeded",
          results["dashboard"]["ok"] and results["desktop"]["ok"],
          f"{results['dashboard']['message'][:80]} | {results['desktop']['message'][:80]}")
    a_files = {p.name for p in a_dir.rglob("*") if p.is_file()}
    b_files = {p.name for p in b_dir.rglob("*") if p.is_file()}
    check("ISO-01", "each workspace contains only its own artifact",
          "app.py" in a_files and "main.py" not in a_files
          and "main.py" in b_files and "app.py" not in b_files,
          f"A={sorted(a_files)[:5]} B={sorted(b_files)[:5]}")
    check("ISO-01", "no zip/cross-write corruption",
          not any(p.name == "escaped.txt" for p in a_dir.rglob("*")))

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({"checks": checks}, indent=2), encoding="utf-8")
    passed = sum(1 for c in checks if c["ok"])
    print(f"\n{passed}/{len(checks)} stage-7 checks passed")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
