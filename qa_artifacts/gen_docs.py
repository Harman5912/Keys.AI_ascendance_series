"""qa_artifacts/gen_docs.py — generate DOCX/PPTX through Keys.AI's real
file_processor document-creation path.

No mocks of the generation logic: the only thing this script does is point the
file_processor task model at the local Ollama runtime (via the app's own
core.api_config.set_task_model), call actions.file_processor.file_processor
with action="create", and record what actually happened. The user's previous
task-model setting is restored afterwards.

Usage:
  python qa_artifacts/gen_docs.py --kind docx [--only D01,D02] [--model qwen3:8b]
  python qa_artifacts/gen_docs.py --kind pptx
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

OUT_DOCX = BASE / "qa_artifacts" / "generated_documents"
OUT_PPTX = BASE / "qa_artifacts" / "generated_presentations"
LOG = BASE / "qa_artifacts" / "logs"

# ── Document specs (Mission 7) ─────────────────────────────────────────────
DOC_SPECS = [
    {
        "id": "D01", "slug": "business_proposal", "title": "Business Proposal — Northwind Bakery Expansion",
        "instruction": ("Write a professional business proposal for 'Northwind Bakery' expanding to a second "
                        "location. Required sections: Executive Summary, Business Opportunity, Objectives, "
                        "Target Market, Implementation Timeline, Budget Summary, Risks and Mitigation, "
                        "Recommendation. Use '# ' and '## ' markdown headings, short paragraphs and bullet "
                        "lists. Use fictional figures in USD. About 500-700 words. No placeholders."),
        "required": ["Executive Summary", "Budget", "Recommendation"],
        "min_paragraphs": 12,
    },
    {
        "id": "D02", "slug": "ats_resume", "title": "Résumé — Priya Raman, Data Analyst",
        "instruction": ("Write an ATS-friendly résumé for a fictional candidate 'Priya Raman', a data analyst "
                        "with 4 years experience. Sections: Professional Summary, Core Skills, Professional "
                        "Experience (2 roles with bullet achievements), Education, Certifications. Use simple "
                        "text headings ('# '), no tables, no graphics, no columns. Fictional employers and "
                        "contact details only. About 450 words."),
        "required": ["Priya Raman", "Experience", "Education", "Skills"],
        "min_paragraphs": 10,
    },
    {
        "id": "D03", "slug": "technical_project_report", "title": "Technical Project Report — Mosaic Sensor Gateway",
        "instruction": ("Write a technical project report for 'Mosaic Sensor Gateway', an industrial IoT data "
                        "collector. Sections: Project Overview, System Architecture, Components, Data Flow, "
                        "Performance Results, Known Limitations, Future Work. Include a short numbered list of "
                        "requirements. Use '# ' and '## ' headings. Fictional but technically coherent. About "
                        "600 words."),
        "required": ["Architecture", "Limitations", "Future Work"],
        "min_paragraphs": 12,
    },
    {
        "id": "D04", "slug": "standard_operating_procedure", "title": "Standard Operating Procedure — Backup Verification",
        "instruction": ("Write a Standard Operating Procedure for verifying nightly database backups at a "
                        "fictional company 'Halcyon Logistics'. Sections: Purpose, Scope, Roles and "
                        "Responsibilities, Prerequisites, Procedure (numbered steps), Verification Checks, "
                        "Escalation, Revision History. Use '# ' headings and numbered steps. About 500 words."),
        "required": ["Purpose", "Scope", "Procedure", "Escalation"],
        "min_paragraphs": 12,
    },
    {
        "id": "D05", "slug": "meeting_minutes", "title": "Meeting Minutes — Q3 Product Review",
        "instruction": ("Write meeting minutes for a fictional Q3 product review at 'Vertex Labs'. Include: "
                        "Attendees, Agenda items, Discussion summary per agenda item, Decisions, and an Action "
                        "Items list with owner and due date. Use '# ' headings. Fictional names only. About "
                        "400 words."),
        "required": ["Attendees", "Action Items", "Decision"],
        "min_paragraphs": 8,
    },
    {
        "id": "D06", "slug": "software_requirements_spec", "title": "Software Requirements Specification — Atlas Booking Service",
        "instruction": ("Write a Software Requirements Specification for 'Atlas Booking Service'. Sections: "
                        "Introduction, Purpose, Scope, Definitions, Functional Requirements (numbered FR-1..FR-8), "
                        "Non-Functional Requirements (NFR-1..NFR-5), Assumptions, Constraints. Use '# ' and '## ' "
                        "headings. Fictional system, realistic requirements. About 650 words."),
        "required": ["Functional Requirements", "Non-Functional", "Scope", "FR-1"],
        "min_paragraphs": 14,
    },
    {
        "id": "D07", "slug": "release_notes", "title": "Release Notes — Orbit Desktop 3.4.0",
        "instruction": ("Write product release notes for fictional software 'Orbit Desktop 3.4.0'. Sections: "
                        "Release Summary, New Features, Improvements, Bug Fixes, Known Issues, Upgrade Notes. "
                        "Use '# ' headings and bullet lists with short, specific entries. About 400 words."),
        "required": ["New Features", "Bug Fixes", "Known Issues"],
        "min_paragraphs": 8,
    },
    {
        "id": "D08", "slug": "research_summary", "title": "Research Summary — Urban Heat Island Mitigation",
        "instruction": ("Write a research summary on urban heat island mitigation for a fictional policy team. "
                        "Sections: Background, Objective, Methods Overview, Key Findings (4 numbered findings), "
                        "Limitations, Recommendations, References (list 3 clearly labelled fictional reference "
                        "entries with author, year, title). Use '# ' headings. About 600 words."),
        "required": ["Findings", "Recommendations", "References"],
        "min_paragraphs": 12,
    },
    {
        "id": "D09", "slug": "invoice", "title": "Invoice — Brightline Studio to Cobalt Retail",
        "instruction": ("Write an invoice document from fictional business 'Brightline Studio' to client 'Cobalt "
                        "Retail'. Include: Invoice Number INV-2041, Invoice Date, Due Date, Bill To address, a "
                        "line-item list with description / quantity / unit price / amount (4 items, USD), "
                        "Subtotal, Tax 8%, Total Due, Payment Terms. Use '# ' headings and '- ' bullet lines for "
                        "line items. All figures must add up. About 300 words."),
        "required": ["Invoice", "Total", "Subtotal"],
        "min_paragraphs": 7,
    },
    {
        "id": "D10", "slug": "user_manual", "title": "Technical User Manual — Aegis Home Hub",
        "instruction": ("Write a technical user manual for fictional device 'Aegis Home Hub'. Sections: "
                        "Introduction, Package Contents, Installation, Initial Setup (numbered steps), Using the "
                        "App, Troubleshooting (symptom → action), Safety Information, Support. Use '# ' and '## ' "
                        "headings. About 650 words."),
        "required": ["Installation", "Troubleshooting", "Safety"],
        "min_paragraphs": 14,
    },
]

# ── Presentation specs (Mission 9) ────────────────────────────────────────
PPT_SPECS = [
    {"id": "P01", "slug": "startup_pitch", "title": "Seed Pitch — Lumen Fields",
     "instruction": ("Create a seed-round pitch deck for fictional agritech startup 'Lumen Fields'. Cover: "
                     "problem, solution, product, market size, business model, traction, competition, team, "
                     "ask and use of funds. 8 slides. Specific but fictional numbers."),
     "required_prompt": "Return a JSON array of 8 slides. Each slide: {\"title\": \"...\", \"content\": \"...\"}. "
                     "First slide is the title slide. Include concrete fictional numbers throughout."},
    {"id": "P02", "slug": "technical_architecture", "title": "Platform Architecture — Mosaic Gateway",
     "instruction": ("Create a technical architecture presentation for 'Mosaic Gateway'. Cover: context, "
                     "component diagram description, data flow, storage, security, deployment, observability, "
                     "trade-offs. 7 slides."),
     "required_prompt": "Return a JSON array of 7 slides. Each slide: {\"title\": \"...\", \"content\": \"...\"}. "
                     "Include concrete technical names and components."},
    {"id": "P03", "slug": "product_demo", "title": "Product Demonstration — Orbit Desktop",
     "instruction": ("Create a product demonstration deck for fictional software 'Orbit Desktop'. Cover: "
                     "overview, key workflows, a walkthrough in 4 steps, integrations, security, pricing, next "
                     "steps. 7 slides."),
     "required_prompt": "Return a JSON array of 7 slides. Each slide: {\"title\": \"...\", \"content\": \"...\"}. "
                     "Include concrete feature names and workflow steps."},
    {"id": "P04", "slug": "data_analytics_report", "title": "Q3 Analytics Review — Northstar",
     "instruction": ("Create a data analytics review deck for fictional SaaS 'Northstar'. Cover: headline "
                     "metrics, acquisition, activation, retention, revenue, risks, recommendations. 8 slides. "
                     "Use consistent fictional numbers."),
     "required_prompt": "Return a JSON array of 8 slides. Each slide: {\"title\": \"...\", \"content\": \"...\"}. "
                     "Include consistent fictional numbers across all slides."},
    {"id": "P05", "slug": "education_lesson", "title": "Lesson — Introduction to Data Normalisation",
     "instruction": ("Create an educational lesson deck on database normalisation. Cover: objectives, why "
                     "normalisation matters, 1NF, 2NF, 3NF, worked example, common mistakes, recap and exercise. "
                     "8 slides."),
     "required_prompt": "Return a JSON array of 8 slides. Each slide: {\"title\": \"...\", \"content\": \"...\"}. "
                     "Include concrete examples and clear definitions."},
    {"id": "P06", "slug": "business_strategy", "title": "Strategy Plan — Halcyon Logistics 2027",
     "instruction": ("Create a business strategy plan deck for fictional 'Halcyon Logistics'. Cover: situation, "
                     "objectives, market trends, strategic pillars, initiatives, KPIs, risks, roadmap. 8 slides."),
     "required_prompt": "Return a JSON array of 8 slides. Each slide: {\"title\": \"...\", \"content\": \"...\"}. "
                     "Include concrete KPIs and initiative names."},
    {"id": "P07", "slug": "research_conference", "title": "Conference Talk — Sparse Retrieval at Scale",
     "instruction": ("Create a research conference presentation on sparse retrieval at scale. Cover: "
                     "motivation, related work, method, experimental setup, results, limitations, conclusion, "
                     "references. 8 slides. Do not invent a specific published paper; present it as a study."),
     "required_prompt": "Return a JSON array of 8 slides. Each slide: {\"title\": \"...\", \"content\": \"...\"}. "
                     "Present as a study with concrete methods and results."},
    {"id": "P08", "slug": "security_awareness", "title": "Security Awareness — Phishing Defence",
     "instruction": ("Create a cybersecurity awareness deck about phishing. Cover: why it matters, common "
                     "phishing types, red flags, a safe reporting process, password and MFA hygiene, quiz "
                     "questions, recap. 7 slides."),
     "required_prompt": "Return a JSON array of 7 slides. Each slide: {\"title\": \"...\", \"content\": \"...\"}. "
                     "Include concrete red flags and quiz questions."},
    {"id": "P09", "slug": "project_status", "title": "Project Status Review — Atlas Migration",
     "instruction": ("Create a project status review deck for the fictional 'Atlas Migration' programme. "
                     "Cover: scope, timeline vs actual, completed milestones, in-flight work, risks and issues, "
                     "budget status, decisions needed, next period. 7 slides."),
     "required_prompt": "Return a JSON array of 7 slides. Each slide: {\"title\": \"...\", \"content\": \"...\"}. "
                     "Include concrete dates and milestones."},
    {"id": "P10", "slug": "product_launch", "title": "Product Launch — Volta Home Battery",
     "instruction": ("Create a product launch deck for fictional 'Volta Home Battery'. Cover: market context, "
                     "product overview, key features, specifications, pricing and availability, go-to-market "
                     "plan, launch timeline, call to action. 7 slides."),
     "required_prompt": "Return a JSON array of 7 slides. Each slide: {\"title\": \"...\", \"content\": \"...\"}. "
                     "Include concrete specifications and pricing."},
]


class FakePlayer:
    """A non-interactive Keys.AI player: records events, never opens apps."""

    def __init__(self):
        self.events = []
        self.logs = []

    def write_log(self, msg):
        self.logs.append(str(msg))

    def creation_event(self, icon="", text="", *a, **kw):
        self.events.append(f"{icon} {text}")

    def creation_progress(self, pct=0):
        pass

    def creation_complete(self, summary=""):
        self.events.append(f"COMPLETE {summary}")

    def creation_error(self, msg=""):
        self.events.append(f"ERROR {msg}")

    def ask_decision(self, question, options, **kw):
        return options[0] if options else ""

    def ask_permission(self, action="", reason="", location=""):
        return "deny"          # never launch Word/PowerPoint during automation


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["docx", "pptx"], required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--provider", default="ollama")
    args = ap.parse_args()

    specs = DOC_SPECS if args.kind == "docx" else PPT_SPECS
    if args.only:
        want = {s.strip().upper() for s in args.only.split(",") if s.strip()}
        specs = [s for s in specs if s["id"].upper() in want]

    out_dir = OUT_DOCX if args.kind == "docx" else OUT_PPTX
    out_dir.mkdir(parents=True, exist_ok=True)
    LOG.mkdir(parents=True, exist_ok=True)

    from core.api_config import get_task_model, set_task_model
    from actions.file_processor import file_processor
    import actions.file_processor as fp

    previous = get_task_model("file_processor")
    # Keep a backup on disk so an interrupted run (kill/power loss) cannot leave
    # the user's task-model setting pointing at the local model.
    boot = LOG / "gen_docs_config_backup.json"
    boot.write_text(json.dumps(previous, indent=2), encoding="utf-8")
    set_task_model("file_processor", args.provider, args.model)
    fp._fp_cache = None                     # drop any client built from the old config

    manifest_path = out_dir / "_gen_manifest.json"
    manifest = []
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = []

    try:
        for spec in specs:
            dest = out_dir / f"{spec['id']}_{spec['slug']}.{args.kind}"
            if dest.exists():
                dest.unlink()
            player = FakePlayer()
            t0 = time.time()
            error = ""
            result = ""
            try:
                result = file_processor(
                    {
                        "action": "create",
                        "file_path": str(dest),
                        "title": spec["title"],
                        "instruction": spec["instruction"],
                    },
                    player=player,
                )
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                traceback.print_exc()
            seconds = round(time.time() - t0, 1)
            rec = {
                "id": spec["id"],
                "slug": spec["slug"],
                "kind": args.kind,
                "title": spec["title"],
                "path": str(dest.relative_to(BASE)).replace("\\", "/"),
                "exists": dest.exists(),
                "bytes": dest.stat().st_size if dest.exists() else 0,
                "seconds": seconds,
                "provider": args.provider,
                "model": args.model,
                "result": str(result)[:300],
                "error": error,
                "creation_events": player.events[-12:],
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            manifest = [m for m in manifest if m.get("id") != spec["id"]] + [rec]
            print(f"[{spec['id']}] {seconds}s  exists={rec['exists']}  "
                  f"bytes={rec['bytes']}  result={str(result)[:110]}", flush=True)
            if error:
                print(f"         ERROR {error}", flush=True)
            (out_dir / "_gen_manifest.json").write_text(
                json.dumps(sorted(manifest, key=lambda m: m["id"]), indent=2), encoding="utf-8")
    finally:
        set_task_model("file_processor", previous.get("provider", ""), previous.get("model", ""))
        fp._fp_cache = None
        boot.unlink(missing_ok=True)
        print(f"restored file_processor task model -> {previous}", flush=True)

    print(f"\nDONE {len(specs)} {args.kind} artifact(s) in {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
