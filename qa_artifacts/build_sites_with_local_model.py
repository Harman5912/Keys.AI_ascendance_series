"""Build the demo pages with Keys.ai's own local models.

Runs core.site_builder for each brief: the planner (qwen2.5-coder:3b) writes the
plan, qwen3:8b writes the page, the checks and the browser audit decide whether
the model's file ships or the verified rendered floor does.

    python qa_artifacts/build_sites_with_local_model.py

Progress is appended to qa_artifacts/reports/local_model_sites.json so the run
can be watched while it happens.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

OUT = BASE / "examples" / "generated" / "sites"
REPORT = BASE / "qa_artifacts" / "reports" / "local_model_sites.json"

# The studio is pinned per page so the five builds cannot converge on one
# layout: the set has to look like five different sites, not one theme with
# five sets of words.
BRIEFS = [
    ("01_portfolio_riya_dev", "portfolio", "brutalist",
     "Portfolio website for Riya Nair, a full-stack developer. Dark, technical, "
     "type-led; projects with real outcomes, no grid of identical cards."),
    ("02_portfolio_atelier_nord", "portfolio", "swiss",
     "Portfolio website for Atelier Nord, a small architecture studio in Oslo. "
     "Light, huge type, lots of white space, three built projects."),
    ("03_portfolio_maya_photo", "portfolio", "cinematic",
     "Photography portfolio for Maya Osei, a portrait and documentary "
     "photographer in Accra. Warm, film-like, image-led gallery with series."),
    ("04_marketing_verdant", "website", "organic",
     "Marketing website for Verdant, a small-batch organic skincare brand in "
     "Somerset. Cream and sage, editorial serif, six products with prices."),
    ("05_marketing_rocketpay", "website", "aurora",
     "Marketing website for Rocketpay, a fintech payments product. Dark, neon, "
     "flat pricing, developer-first copy."),
]


def main() -> int:
    from core.site_builder import build_site

    # "fast"  = planner (qwen2.5-coder:3b) writes the plan, the verified renderer
    #           draws it — about a minute per page.
    # "custom" = the writer model (qwen3:8b by default) writes the whole page;
    #           on this machine that is ~20 minutes per page, so it is opt-in.
    speed = os.environ.get("BUILD_SPEED", "fast").strip().lower()
    writer = os.environ.get("BUILD_WRITER", "").strip()
    print(f"speed={speed} writer={writer or 'default'}", flush=True)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    results = []
    REPORT.write_text(json.dumps({"started": time.time(), "results": results}, indent=2),
                      encoding="utf-8")

    only = {s.strip() for s in os.environ.get("BUILD_ONLY", "").split(",") if s.strip()}
    for slug, kind, studio, brief in BRIEFS:
        if only and not any(slug.startswith(o) for o in only):
            continue
        out = OUT / slug
        print(f"\n=== {slug} ({kind}) ===", flush=True)
        started = time.time()
        try:
            result = build_site(
                brief, out, kind=kind, speed=speed, model=writer, attempts=1, browser=True,
                studio=studio,
                on_phase=lambda name, pct, detail="": print(f"  {name} {int(pct * 100)}% {detail}",
                                                            flush=True),
                on_log=lambda line: print(f"  · {line}", flush=True),
            )
        except Exception as err:                       # a failed build must not stop the run
            result = {"ok": False, "error": f"{type(err).__name__}: {err}"}
        result["slug"] = slug
        result["brief"] = brief
        result["kind"] = kind
        result["requested_studio"] = studio
        result["seconds"] = result.get("seconds") or round(time.time() - started, 1)
        results.append(result)
        REPORT.write_text(json.dumps({"results": results}, indent=2, default=str),
                          encoding="utf-8")
        print(f"  → {'OK' if result.get('ok') else 'FAILED'} "
              f"{result.get('mode', '')} {result.get('bytes', 0)}B "
              f"{result.get('seconds', 0)}s", flush=True)

    print("\nDone:", json.dumps(
        [(r["slug"], r.get("ok"), r.get("mode"), r.get("seconds")) for r in results], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
