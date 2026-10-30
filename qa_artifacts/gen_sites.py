"""qa_artifacts/gen_sites.py — build websites / web apps / portfolios with the
real Crown Code agent (core.crown_bridge.CrownBridge → Crown Code headless).

Each artifact is produced by the agent itself (write_file tool in an isolated
workspace), not by this script. A run that calls no tool, writes no file, or
leaves a file that does not parse is recorded as a FAILURE — never as success.

Usage:
  python qa_artifacts/gen_sites.py --kind website [--only 1,4,7] [--attempts 2]
  python qa_artifacts/gen_sites.py --kind webapp
  python qa_artifacts/gen_sites.py --kind portfolio
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

OUT = {
    "website": BASE / "qa_artifacts" / "generated_websites",
    "webapp": BASE / "qa_artifacts" / "generated_webapps",
    "portfolio": BASE / "qa_artifacts" / "generated_portfolios",
}
LOGS = BASE / "qa_artifacts" / "logs"

COMMON = ("Your FIRST action must be a write_file tool call that writes index.html; do not print the "
          "HTML in your reply and do not ask questions. Write ONE self-contained file named index.html "
          "in the current working directory using the write_file tool. Inline all CSS and JavaScript inside it. No external scripts, stylesheets, "
          "fonts or images from the internet. No build step. It must open and work from file://. "
          "Use semantic HTML and include a <title>, a header, a <main> and a footer. "
          "Write the finished production page, not a skeleton: real, specific copy for this brief, "
          "real section headings, real prices and names. At least 250 lines of HTML/CSS/JS. "
          "Never emit placeholder filler such as 'Feature 1', 'Lorem ipsum', 'Your Company' or "
          "'Description here'.")

PLACEHOLDER_TEXT = re.compile(
    r"(feature\s*[1-9]\b|lorem ipsum|your company|company name|description here|"
    r"insert (?:text|content)|coming soon|placeholder)", re.I)

MIN_BYTES = {"website": 3500, "webapp": 3500, "portfolio": 3500}

SPECS = {
    "website": [
        ("01_saas_landing", "SaaS product landing page", "Product 'Relaydesk', a support-inbox SaaS for small teams. Sections: hero with headline and two call-to-action buttons, three feature cards, a pricing table with three tiers, a testimonial, and a footer. Buttons must visibly respond (scroll to pricing / toggle a FAQ)."),
        ("02_ecommerce_storefront", "E-commerce storefront", "Store 'Fern & Flint', a fictional plant shop. Show six product cards with name, price and an 'Add to cart' button. A cart counter in the header must increase when a button is clicked. Include a mock checkout section with a name/email/card form that validates required fields and shows a confirmation message. Include a footer."),
        ("03_restaurant_menu", "Restaurant and menu website", "Restaurant 'Copper Spoon'. Sections: hero, about, a menu with at least eight dishes grouped into three categories with prices, opening hours, and a reservation form (name, date, party size) that validates and shows a confirmation. Include a footer."),
        ("04_education_institution", "Educational institution website", "Fictional 'Rivergate Institute'. Sections: hero, programmes (at least four with duration and description), admissions steps, an FAQ accordion with four questions that opens and closes, and a footer with contact details."),
        ("05_marketing_agency", "Digital marketing agency website", "Agency 'Northline Digital'. Sections: hero, services (four), case studies (three cards with a result metric), a team section (three members), a contact form with validation, and a footer."),
        ("06_event_conference", "Event and conference website", "Conference 'Signal Summit 2027'. Sections: hero with date and location, an agenda with at least six sessions across two days (with a day tab switcher that works), speakers (four), ticket tiers (three), and a footer."),
        ("07_news_editorial", "News and editorial website", "Publication 'The Ledger Line'. A masthead, a lead story with headline and standfirst, a grid of at least six more stories with category labels, a category filter that shows/hides stories when clicked, and a footer. All content fictional."),
        ("08_nonprofit", "Nonprofit organisation website", "Nonprofit 'Clean Currents Alliance'. Sections: mission hero, three programmes, impact statistics (numbers animated or plainly shown), a donation section with three preset amounts that highlight when selected, volunteer signup form with validation, and a footer."),
        ("09_analytics_dashboard", "Analytics dashboard website", "Dashboard 'Pulseboard'. A KPI row (four metrics), a bar chart drawn with inline SVG or canvas from a JS data array, a sortable table with at least six rows, a date-range filter that changes the displayed KPI numbers, and a footer. No external chart library."),
        ("10_business_services", "Professional business services website", "Consultancy 'Harbour & Vale'. Sections: hero, services (three), an engagement process with four numbered steps, testimonials (two), pricing guidance, a contact form with validation, and a footer."),
    ],
    "webapp": [
        ("01_task_manager", "Task management app", "A task manager: add a task with title and priority, list tasks, toggle done, delete a task, filter by all/active/done, and persist to localStorage so a reload keeps the tasks. Show an empty state when there are no tasks."),
        ("02_inventory_manager", "Inventory management app", "An inventory app: add an item (name, quantity, unit price), edit quantity, delete an item, show total stock value, search by name, and persist to localStorage. Validate that quantity is a positive number and show an inline error otherwise."),
        ("03_crm", "CRM with customer records", "A small CRM: add a customer (name, company, email, status), search customers by name or company, edit status, delete a customer, show a count of records, persist to localStorage, and show an empty state."),
        ("04_expense_tracker", "Expense tracker", "An expense tracker: add an expense (description, amount, category, date), list expenses, delete one, compute and display the total and a per-category breakdown, filter by category, and persist to localStorage. Reject non-positive amounts with an error message."),
        ("05_analytics_dashboard", "Analytics dashboard app", "An analytics dashboard over a fixed in-file dataset of at least twelve monthly records: show four KPIs, a bar chart in inline SVG, a sortable table, and a period selector (3/6/12 months) that updates the KPIs, chart and table together."),
        ("06_appointment_booking", "Appointment booking app", "An appointment booking app with simulated availability: pick a date, show four time slots as available or taken, book an available slot with a name, prevent double booking, list booked appointments, cancel a booking, and persist to localStorage."),
        ("07_kanban_board", "Kanban project board", "A kanban board with three columns (To do, In progress, Done): add a card with a title, move a card between columns with buttons, delete a card, show per-column counts, and persist to localStorage."),
        ("08_notes_app", "Notes app", "A notes app: create a note with title and body, edit it, delete it, search notes by text, show the selected note in a detail pane, and persist to localStorage. Show an empty state."),
        ("09_quiz_app", "Quiz and learning app", "A quiz app with at least five multiple-choice questions defined in JS: show one question at a time, record the answer, show progress, compute and display a final score with a pass/fail message, and allow restarting the quiz."),
        ("10_document_manager", "Document management app", "A document manager over a small mock file list: show documents with name, type and size, search by name, filter by type, select a document to preview its mock content, 'upload' a new mock document through a form with validation, delete a document, and persist to localStorage."),
    ],
    "portfolio": [
        ("01_fullstack_developer", "Full-stack developer portfolio", "Portfolio for fictional developer 'Arjun Mehta'. Sections: intro with role, about, skills grouped by area, three projects with description and tech tags, a contact form with validation, and social links (href='#'). Light theme, strong type hierarchy."),
        ("02_ai_ml_engineer", "AI/ML engineer portfolio", "Portfolio for fictional ML engineer 'Sofia Alvarez'. Sections: intro, about, four projects with a metric each, publications list, skills, contact form with validation. Include a subtle animated accent and respect prefers-reduced-motion."),
        ("03_data_analyst", "Data analyst portfolio", "Portfolio for fictional data analyst 'Daniel Osei'. Sections: intro, about, three case studies each with question/approach/result, tools list, a small inline SVG chart of a fictional metric, contact form. Clean and light."),
        ("04_uiux_designer", "UI/UX designer portfolio", "Portfolio for fictional designer 'Mina Park'. Sections: intro, selected work (three projects with a process note), design principles, tools, contact form with validation. Bold typography and a distinctive colour accent."),
        ("05_photographer", "Photographer portfolio", "Portfolio for fictional photographer 'Lena Fischer'. A gallery of at least nine tiles using CSS gradients or inline SVG as stand-in images (no external files), a filter by category that works, an about section, a booking enquiry form with validation, and a footer."),
        ("06_student_fresher", "Student and fresher portfolio", "Portfolio for fictional final-year student 'Rohit Nair'. Sections: intro, education, two academic projects, skills, certifications, and a contact form with validation. Simple, fast, no external assets."),
        ("07_creative_agency", "Creative agency portfolio", "Portfolio for fictional agency 'Studio Kestrel'. Sections: hero statement, four case studies with a result line, services, a client list, and a contact form. Expressive layout, still responsive."),
        ("08_accessible_minimal", "Minimalist accessibility-focused portfolio", "Portfolio for fictional accessibility specialist 'Nadia Haddad'. Light minimal layout, skip-to-content link, visible focus styles, semantic landmarks, high contrast, three projects, and a contact form with labelled inputs and inline validation messages announced via aria-live."),
        ("09_premium_dark", "Premium dark visual portfolio", "Portfolio for fictional creative developer 'Theo Marchetti'. Dark premium look, large hero statement, three featured projects with hover/focus states, a short about, and a contact form with validation. Must stay readable and responsive."),
        ("10_editorial", "Responsive editorial portfolio", "Portfolio for fictional writer-editor 'Clara Benson'. Editorial magazine layout: masthead, a long-form intro, three selected pieces with pull quotes, an about note, and a contact form with validation. Responsive from 375px to desktop."),
    ],
}

EXTRA = {
    "website": ("Every navigation link must point to an existing element on the page, every button must have a "
                "working click handler, the page must have no console errors, and the layout must not overflow "
                "horizontally at 375px width. Include at least two real <button> elements that do something "
                "visible when clicked, add :focus-visible styles for links and buttons, and set "
                "* { box-sizing: border-box } plus max-width: 100% so nothing overflows on a phone."),
    "webapp": ("The app must implement every operation listed, validate bad input with a visible message, keep "
               "working after reload via localStorage where stated, show an empty state, and have no console "
               "errors. Use real <form>/<input>/<button> elements with labels, add :focus-visible styles, and "
               "make the layout work at 375px without horizontal scrolling."),
    "portfolio": ("The page must have no console errors, no horizontal overflow at 375px, labelled form inputs "
                  "with validation, and working keyboard focus styles. Include a real <form> with labelled "
                  "inputs, at least one <button> with a working click handler, and :focus-visible styles."),
}

REPAIR = ("The file index.html is required but {problem}. Use the write_file tool to write a complete, "
          "self-contained index.html now for this project: {brief}")


def _slug(num: str, name: str) -> str:
    """Folder name for one artifact: '01_saas_landing', not '01_saas_landing_SaaS...'.

    Specs carry the index and slug in `num`; `name` is a human description that
    must never end up in a path (spaces, capitals, punctuation).
    """
    if re.match(r"^\d{2}_", num):
        return num
    return f"{num}_{re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')}"


def check_html(path: Path, kind: str = "website") -> tuple[bool, list[str]]:
    problems = []
    if not path.exists():
        return False, ["index.html was not created"]
    raw = path.read_text(encoding="utf-8", errors="replace")
    minimum = MIN_BYTES.get(kind, 4000)
    if len(raw) < minimum:
        problems.append(f"index.html is only {len(raw)} bytes (a finished page needs >= {minimum})")

    visible = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    visible = re.sub(r"<[^>]+>", " ", visible)
    filler = sorted({m.group(0).lower() for m in PLACEHOLDER_TEXT.finditer(visible)})
    if filler:
        problems.append(f"placeholder filler content: {filler[:3]}")
    if "<footer" not in raw.lower() and kind in ("website", "portfolio"):
        problems.append("no <footer> element")
    if "<button" not in raw.lower() and kind in ("website", "portfolio"):
        problems.append("no <button> element")
    if ":focus" not in raw.lower():
        problems.append("no :focus / :focus-visible styles")
    if kind == "webapp" and "<input" not in raw.lower():
        problems.append("no <input> controls")
    if "<html" not in raw.lower():
        problems.append("no <html> element")
    if re.search(r"<script[^>]+src=\"https?://", raw, re.I):
        problems.append("external script dependency")
    if re.search(r"<link[^>]+href=\"https?://", raw, re.I):
        problems.append("external stylesheet dependency")
    if "<title>" not in raw.lower():
        problems.append("no <title>")
    body = re.search(r"<body[^>]*>(.*)</body>", raw, re.S | re.I)
    # Apps can be form-first with little static copy; the browser audit is the
    # real content check. Just refuse a page whose body is essentially empty.
    min_text = 120 if kind == "webapp" else 200
    if not body or len(re.sub(r"<[^>]+>", "", body.group(1)).strip()) < min_text:
        problems.append("almost no visible text content")
    return (not problems), problems


def run_one(kind: str, num: str, name: str, brief: str, args) -> dict:
    from core.crown_bridge import CrownBridge

    ws = OUT[kind] / _slug(num, name)
    ws.mkdir(parents=True, exist_ok=True)
    index = ws / "index.html"
    if index.exists():
        index.unlink()

    task = f"Build this: {brief}\n\n{COMMON}{EXTRA[kind]}"
    attempts = []
    ok = False

    for attempt in range(1, args.attempts + 1):
        if attempt > 1:
            previous = attempts[-1]["problems"] if attempts else []
            why = ("; ".join(previous)[:300] if previous
                   else "was missing or invalid after the last attempt")
            task = REPAIR.format(problem=why, brief=brief)
            task += "\n\n" + COMMON + EXTRA[kind]

        events: list[dict] = []
        tools: list[str] = []
        tool_errors: list[str] = []

        def on_event(ev: dict) -> None:
            t = ev.get("type")
            events.append({"type": t})
            if t == "tool_start":
                tools.append(ev.get("tool", ""))
            elif t == "tool_end" and ev.get("isError"):
                tool_errors.append(str(ev.get("output", ""))[:200])

        bridge = CrownBridge(
            workspace=str(ws), on_event=on_event,
            permission_handler=lambda ev: True,
            log=lambda m: None,
            model=args.model, provider="ollama", policy="safe",
            max_iterations=args.max_iterations,
            tools=["write_file", "read_file"],
        )
        t0 = time.time()
        started, msg = bridge.start(task)
        result = bridge.wait(timeout=args.timeout) if started else {"ok": False, "summary": msg}
        bridge.stop()
        seconds = round(time.time() - t0, 1)

        passed, problems = check_html(index, kind)
        if not tools:
            passed = False
            problems = ["the model called no tool (it only produced text)"] + problems

        attempts.append({
            "attempt": attempt, "seconds": seconds, "tools": tools,
            "bridge_ok": bool((result or {}).get("ok")),
            "summary": str((result or {}).get("summary", ""))[:300],
            "tool_errors": tool_errors[:4], "problems": problems, "passed": passed,
            "bytes": index.stat().st_size if index.exists() else 0,
        })
        print(f"    attempt {attempt}: {'PASS' if passed else 'FAIL'} {seconds}s "
              f"tools={tools[:4]} problems={problems[:2]}", flush=True)
        if passed:
            ok = True
            break

    rec = {
        "kind": kind, "id": num, "name": name, "slug": _slug(num, name),
        "dir": str(ws.relative_to(BASE)).replace("\\", "/"),
        "passed": ok, "attempts": attempts,
        "bytes": index.stat().st_size if index.exists() else 0,
        "model": args.model, "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=list(SPECS), required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=360)
    ap.add_argument("--max-iterations", type=int, default=6)
    ap.add_argument("--model", default="qwen3:8b")
    args = ap.parse_args()

    specs = SPECS[args.kind]
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        specs = [s for s in specs if s[0].split("_")[0] in want]

    out_dir = OUT[args.kind]
    out_dir.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "_gen_manifest.json"
    manifest = []
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = []

    for num, name, brief in specs:
        print(f"\n== [{args.kind} {num}] {name}", flush=True)
        rec = run_one(args.kind, num, name, brief, args)
        manifest = [m for m in manifest if not (m.get("kind") == args.kind and m.get("id") == num)] + [rec]
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"   -> {'PASS' if rec['passed'] else 'FAIL'} ({rec['bytes']} bytes)", flush=True)

    done = sum(1 for m in manifest if m.get("kind") == args.kind and m.get("passed"))
    total = len([m for m in manifest if m.get("kind") == args.kind])
    print(f"\n{args.kind}: {done}/{total} artifacts built and structurally valid", flush=True)
    return 0 if done == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
