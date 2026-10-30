"""Screenshot the two-of-each builds and write a gallery page.

    python qa_artifacts/make_gallery.py

Screenshots land in examples/generated/two_of_each/screenshots/ and the gallery
is examples/generated/two_of_each/index.html.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "examples" / "generated" / "two_of_each"
SHOTS = OUT / "screenshots"
REPORT = BASE / "qa_artifacts" / "reports" / "two_of_each.json"


def shoot(page_path: Path, target: Path) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 860},
                                  device_scale_factor=1)
        page = ctx.new_page()
        page.goto(page_path.resolve().as_uri(), wait_until="load")
        page.wait_for_timeout(400)
        page.screenshot(path=str(target), full_page=False)
        browser.close()
    return target.name


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    results = json.loads(REPORT.read_text())["results"] if REPORT.exists() else []
    pages = [r for r in results if r.get("artifact") == "page" and Path(r["path"]).exists()]
    apps = [r for r in results if r.get("artifact") != "page"]

    cards = []
    for r in pages:
        slug = r["slug"]
        shot = SHOTS / f"{slug}.png"
        if not shot.exists():
            shoot(Path(r["path"]), shot)
        studio = r.get("studio_used", r.get("studio", "")) or ""
        checklist = str(r.get("checklist_score", ""))
        cards.append(
            f'''      <article class="card">
        <a class="shot" href="pages/{slug}/index.html">
          <img src="screenshots/{slug}.png" alt="Screenshot of {slug}" loading="lazy">
        </a>
        <div class="body">
          <h3>{slug.replace("_", " ")}</h3>
          <p class="meta">{r.get("kind")} · {studio} · {r.get("bytes", 0) // 1024} KB · checklist {checklist}</p>
          <p class="actions"><a href="pages/{slug}/index.html">Open page</a>
             <a href="pages/{slug}/plan.json">Plan</a></p>
        </div>
      </article>'''
        )

    docs = [r for r in results if r.get("artifact") in ("pptx","docx","xlsx") and Path(r.get("path","")).exists()]

    app_cards = []
    for a in apps:
        files = a.get("files") or []
        state = "finished" if a.get("finished") else "incomplete"
        app_cards.append(
            f'''      <article class="app">
        <h3>{a["slug"].replace("_", " ")}</h3>
        <p class="meta">{a.get("artifact")} · {a.get("seconds", 0)}s · {state}</p>
        <p class="files">{', '.join(files[:8]) if files else "no files yet"}</p>
      </article>'''
        )

    doc_cards = []
    for d in docs:
        ext = d.get("artifact", "")
        pc = d.get("bytes", 0)
        doc_cards.append(
            f'''      <article class="doc">
        <h3>{d.get("title", Path(d["path"]).stem)}</h3>
        <p class="meta">{ext} · {pc // 1024} KB · {d.get("model", "")}</p>
        <p><a class="doc-link" href="documents/{ext}/{Path(d["path"]).name}" download>
          <span class="ext">.{ext}</span> Download</a></p>
      </article>'''
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Keys.ai — two of each, built by the local models</title>
<style>
  :root {{ --bg:#0c0f14; --panel:#141a22; --ink:#eaf0f7; --muted:#94a3b8; --line:#23303f; --accent:#5eead4; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); font:400 15px/1.6 "Segoe UI",system-ui,sans-serif; }}
  header {{ padding:2.4rem clamp(1rem,4vw,3rem) 1.2rem; border-bottom:1px solid var(--line); }}
  h1 {{ margin:0 0 .4rem; font-size:clamp(1.6rem,3.4vw,2.3rem); letter-spacing:-.02em; }}
  .sub {{ margin:0; color:var(--muted); max-width:70ch; }}
  main {{ padding:1.6rem clamp(1rem,4vw,3rem) 3rem; }}
  h2 {{ font-size:.8rem; letter-spacing:.16em; text-transform:uppercase; color:var(--muted);
        margin:2rem 0 1rem; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:1.1rem; }}
  .card {{ background:var(--panel); border:1px solid var(--line); border-radius:14px; overflow:hidden; }}
  .shot {{ display:block; aspect-ratio:4/3; overflow:hidden; background:#0a0d12; }}
  .shot img {{ width:100%; height:100%; object-fit:cover; object-position:top center; display:block;
               transition:transform .3s ease; }}
  .card:hover .shot img {{ transform:translateY(-4px); }}
  .body {{ padding:.9rem 1rem 1.1rem; }}
  h3 {{ margin:0 0 .2rem; font-size:1rem; }}
  .meta {{ margin:0; color:var(--muted); font-size:.78rem; }}
  .actions {{ margin:.6rem 0 0; display:flex; gap:1rem; font-size:.82rem; }}
  a {{ color:var(--accent); }}
  .apps {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:.8rem; }}
  .app {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:.9rem 1rem; }}
  .app .files {{ margin:.5rem 0 0; color:var(--muted); font-size:.74rem; font-family:ui-monospace,monospace; }}
  footer {{ color:var(--muted); font-size:.78rem; padding:0 clamp(1rem,4vw,3rem) 2rem; }}
</style>
</head>
<body>
  <header>
    <h1>Two of each — built by Keys.ai's own models</h1>
    <p class="sub">Pages planned by qwen2.5-coder:3b through the Crown Code site pipeline.
      Applications built by the Crown Code agent (qwen3:8b). Every page was verified with the
      deterministic checks and a headless Chromium audit before it shipped.</p>
  </header>
  <main>
    <h2>Pages · {len(pages)} built</h2>
    <div class="grid">{''.join(cards)}</div>
    <h2>Applications · {len(apps)}</h2>
    <div class="apps">{''.join(app_cards) or '<p class="meta">No applications yet.</p>'}</div>
    <h2>Documents · {len(doc_cards)}</h2>
    <div class="grid">{''.join(doc_cards) or '<p class="meta">No documents yet.</p>'}</div>
  </main>
  <footer>Generated by qa_artifacts/make_gallery.py · screenshot at 1280×860 · local models only.</footer>
</body>
</html>
"""
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"gallery: {OUT / 'index.html'} · {len(pages)} pages, {len(apps)} apps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
