"""Application presets — dashboards, web apps and Python apps, chosen per brief.

The site builder has 52 page presets; an application is a different artefact,
so it has its own catalogue:

* ``DASHBOARD_PRESETS`` — 50 dashboard domains (sales, fleet, support, SOC,
  pharmacy, ...), each with a hue, a mood and the words that identify it.
* ``WEBAPP_PRESETS`` — the common kinds of web application (CRM, LMS, POS,
  booking, helpdesk, ...).
* ``PYTHON_PRESETS`` — the common kinds of Python application (desktop CRUD,
  CLI, scraper, report generator, tray tool, ...).

A preset is not a screenshot: it carries the design parameters the builders
already understand — hue and mood feed ``core.design_system.build_tokens``,
which generates a contrast-checked palette, and the label/summary go into the
prompt so a model-written application follows the same decisions. Selection is
deterministic per brief and varies between near-ties, exactly like the site
presets.
"""

from __future__ import annotations

import hashlib
import re

# (id, label, hue, mood, keywords, summary)
_DASHBOARDS: list[tuple] = [
    ("sales-performance", "Sales performance", 210, "dark",
     ("sales", "revenue", "pipeline", "deals", "quota"), "Pipeline, quota and closed-won trend"),
    ("marketing-campaigns", "Marketing campaigns", 320, "vivid",
     ("marketing", "campaign", "ads", "spend", "leads"), "Spend, leads and cost per acquisition"),
    ("finance-overview", "Finance overview", 150, "dark",
     ("finance", "budget", "cashflow", "profit", "p&l"), "Cash position, budget and margin"),
    ("accounting-ledger", "Accounting ledger", 190, "light",
     ("accounting", "ledger", "invoices", "reconciliation"), "Receivables, payables and reconciliation"),
    ("hr-people", "People and HR", 265, "light",
     ("hr", "people", "headcount", "attrition", "staff"), "Headcount, attrition and tenure"),
    ("recruitment", "Recruitment pipeline", 285, "vivid",
     ("recruitment", "candidates", "interviews", "hiring", "ats"), "Candidates by stage and time to hire"),
    ("support-desk", "Support desk", 25, "dark",
     ("support", "tickets", "sla", "helpdesk", "queue"), "Ticket volume, SLA and backlog"),
    ("devops-pipeline", "DevOps pipeline", 205, "dark",
     ("devops", "deploy", "pipeline", "build", "ci"), "Build success, deploy frequency and lead time"),
    ("observability", "Observability", 175, "dark",
     ("observability", "latency", "uptime", "errors", "logs"), "Latency, error rate and uptime"),
    ("iot-fleet", "IoT device fleet", 195, "dark",
     ("iot", "sensors", "devices", "telemetry", "fleet"), "Device health, telemetry and alerts"),
    ("fleet-operations", "Fleet operations", 30, "dark",
     ("fleet", "vehicles", "trucks", "fuel", "drivers"), "Vehicles, fuel and trip cost"),
    ("logistics", "Logistics", 32, "dark",
     ("logistics", "shipments", "delivery", "routes", "warehouse"), "Shipments, routes and on-time rate"),
    ("inventory", "Inventory overview", 45, "dark",
     ("inventory", "stock", "sku", "reorder", "goods"), "Stock levels, reorder points and value"),
    ("warehouse", "Warehouse flow", 50, "light",
     ("warehouse", "bins", "picks", "packing", "dock"), "Picks, packing and dock activity"),
    ("manufacturing", "Manufacturing", 20, "dark",
     ("manufacturing", "production", "oee", "downtime", "line"), "OEE, downtime and output"),
    ("energy-grid", "Energy grid", 60, "dark",
     ("energy", "grid", "load", "power", "electricity"), "Load, generation and outages"),
    ("solar-farm", "Solar generation", 85, "light",
     ("solar", "renewable", "generation", "kwh", "panels"), "Generation, yield and inverter health"),
    ("utilities", "Utilities", 100, "dark",
     ("utilities", "water", "meter", "outage", "usage"), "Consumption, meters and service outages"),
    ("telecom", "Telecom subscribers", 220, "dark",
     ("telecom", "subscribers", "churn", "arpu", "plans"), "Subscribers, churn and ARPU"),
    ("network-ops", "Network operations", 230, "dark",
     ("network", "bandwidth", "routers", "latency", "links"), "Bandwidth, link health and latency"),
    ("security-soc", "Security operations", 0, "dark",
     ("security", "threats", "alerts", "incidents", "soc"), "Alerts, incidents and response time"),
    ("healthcare", "Healthcare operations", 165, "light",
     ("healthcare", "patients", "clinic", "appointments", "ward"), "Patients, appointments and wait times"),
    ("pharmacy", "Pharmacy", 145, "light",
     ("pharmacy", "prescriptions", "dispensing", "medicines"), "Prescriptions, stock and dispensing"),
    ("education", "Education", 250, "light",
     ("education", "students", "classes", "attendance", "courses"), "Enrolment, attendance and outcomes"),
    ("school-admin", "School administration", 255, "light",
     ("school", "enrolment", "grades", "teachers", "terms"), "Enrolment, grades and staffing"),
    ("ecommerce", "E-commerce", 335, "dark",
     ("ecommerce", "orders", "cart", "conversion", "shop"), "Orders, conversion and basket value"),
    ("retail", "Retail stores", 340, "light",
     ("retail", "stores", "footfall", "basket", "sku"), "Footfall, basket size and sales per store"),
    ("restaurant", "Restaurant", 12, "dark",
     ("restaurant", "orders", "tables", "menu", "covers"), "Covers, table turns and menu mix"),
    ("hotel", "Hotel occupancy", 35, "light",
     ("hotel", "occupancy", "bookings", "rooms", "adr"), "Occupancy, ADR and bookings"),
    ("travel", "Travel bookings", 200, "dark",
     ("travel", "flights", "bookings", "passengers", "routes"), "Bookings, load factor and routes"),
    ("real-estate", "Real estate", 40, "light",
     ("real", "estate", "listings", "viewings", "rent"), "Listings, viewings and rent roll"),
    ("construction", "Construction projects", 28, "light",
     ("construction", "sites", "projects", "tasks", "crews"), "Sites, progress and crew allocation"),
    ("agriculture", "Agriculture", 95, "light",
     ("agriculture", "farm", "crops", "yield", "weather"), "Yield, acreage and weather impact"),
    ("insurance", "Insurance", 215, "light",
     ("insurance", "claims", "policies", "risk", "premium"), "Claims, policies and loss ratio"),
    ("banking", "Banking", 205, "dark",
     ("banking", "accounts", "transactions", "balances", "loans"), "Balances, transactions and exposure"),
    ("payments", "Payments", 160, "dark",
     ("payments", "settlement", "refunds", "transactions", "gateway"), "Settlements, refunds and failures"),
    ("subscriptions", "Subscriptions", 280, "dark",
     ("subscription", "mrr", "churn", "arr", "billing"), "MRR, churn and expansion"),
    ("saas-product", "Product metrics", 270, "dark",
     ("saas", "activation", "retention", "feature", "usage"), "Activation, retention and feature use"),
    ("web-analytics", "Web analytics", 225, "dark",
     ("analytics", "visits", "sessions", "bounce", "traffic"), "Sessions, sources and bounce"),
    ("social-media", "Social media", 315, "vivid",
     ("social", "followers", "engagement", "reach", "posts"), "Reach, engagement and followers"),
    ("advertising", "Advertising", 5, "vivid",
     ("advertising", "impressions", "ctr", "cpc", "placements"), "Impressions, CTR and spend"),
    ("supply-chain", "Supply chain", 55, "light",
     ("supply", "suppliers", "lead time", "procurement", "stock"), "Lead time, supplier fill rate and risk"),
    ("procurement", "Procurement", 75, "light",
     ("procurement", "purchase", "vendors", "po", "approvals"), "Purchase orders, vendors and approvals"),
    ("quality", "Quality control", 110, "light",
     ("quality", "defects", "inspections", "scrap", "rework"), "Defects, inspections and scrap rate"),
    ("maintenance", "Maintenance", 15, "light",
     ("maintenance", "work", "orders", "downtime", "assets"), "Work orders, downtime and asset age"),
    ("safety", "Safety", 355, "dark",
     ("safety", "incidents", "hazards", "compliance", "near"), "Incidents, hazards and corrective actions"),
    ("legal", "Legal matters", 240, "light",
     ("legal", "cases", "matters", "contracts", "counsel"), "Cases, matters and contract renewals"),
    ("compliance", "Compliance", 235, "light",
     ("compliance", "audits", "controls", "gdpr", "policies"), "Audits, controls and open findings"),
    ("projects", "Projects", 260, "light",
     ("projects", "milestones", "sprints", "tasks", "delivery"), "Milestones, sprint and delivery risk"),
    ("media-streaming", "Streaming", 300, "dark",
     ("streaming", "plays", "watch", "content", "viewers"), "Plays, watch time and content mix"),
]

_WEBAPPS: list[tuple] = [
    ("crm", "CRM", 210, "dark", ("crm", "contacts", "deals", "accounts", "leads"),
     "Contacts, deals and activity timeline"),
    ("erp", "ERP", 20, "light", ("erp", "orders", "bom", "finance", "procurement"),
     "Orders, stock and finance in one shell"),
    ("pos", "Point of sale", 12, "dark", ("pos", "till", "checkout", "receipts", "cash"),
     "Fast checkout with receipts"),
    ("inventory", "Inventory manager", 45, "dark", ("inventory", "stock", "sku", "reorder"),
     "Stock, movements and reorder alerts"),
    ("booking", "Booking system", 190, "light", ("booking", "appointments", "slots", "reservations"),
     "Availability, slots and confirmations"),
    ("lms", "Learning platform", 250, "light", ("lms", "courses", "lessons", "students", "quizzes"),
     "Courses, lessons and progress"),
    ("helpdesk", "Helpdesk", 25, "dark", ("helpdesk", "tickets", "support", "sla"),
     "Tickets, queues and SLA timers"),
    ("ticketing", "Ticketing", 10, "dark", ("ticketing", "issues", "backlog", "sprint"),
     "Issue tracker with a backlog"),
    ("kanban", "Kanban board", 220, "dark", ("kanban", "board", "cards", "columns", "sprints"),
     "Draggable columns and cards"),
    ("team-chat", "Team chat", 200, "dark", ("chat", "messages", "channels", "dm"),
     "Channels, threads and presence"),
    ("forum", "Forum", 160, "dark", ("forum", "threads", "posts", "replies", "topics"),
     "Threads, replies and moderation"),
    ("wiki", "Wiki", 230, "light", ("wiki", "pages", "links", "knowledge", "docs"),
     "Linked pages and a knowledge base"),
    ("docs", "Documents", 225, "light", ("documents", "editor", "markdown", "files"),
     "Document editor and library"),
    ("cms", "CMS", 265, "light", ("cms", "content", "articles", "publish", "media"),
     "Articles, media and publishing"),
    ("ecommerce-admin", "Shop admin", 335, "light", ("ecommerce", "products", "orders", "shop"),
     "Products, orders and fulfilment"),
    ("hr-ats", "Recruiting (ATS)", 285, "light", ("ats", "recruiting", "candidates", "jobs"),
     "Jobs, candidates and interviews"),
    ("payroll", "Payroll", 150, "light", ("payroll", "salary", "payslips", "tax"),
     "Runs, payslips and deductions"),
    ("invoicing", "Invoicing", 175, "light", ("invoices", "billing", "payments", "clients"),
     "Invoices, status and reminders"),
    ("expenses", "Expenses", 35, "light", ("expenses", "receipts", "claims", "reimburse"),
     "Claims, receipts and approvals"),
    ("project-mgmt", "Project management", 260, "light", ("project", "tasks", "milestones", "gantt"),
     "Tasks, milestones and workload"),
    ("time-tracking", "Time tracking", 40, "light", ("timesheet", "time tracking", "hours", "timer"),
     "Timers, timesheets and reports"),
    ("calendar", "Calendar", 210, "light", ("calendar", "events", "schedule", "meetings"),
     "Month view, events and invitations"),
    ("email-client", "Email client", 215, "dark", ("email", "inbox", "messages", "mail"),
     "Inbox, threads and compose"),
    ("file-manager", "File manager", 195, "light", ("files", "folders", "upload", "drive"),
     "Folders, uploads and previews"),
    ("notes", "Notes", 50, "light", ("notes", "notebook", "markdown", "tags"),
     "Notebooks, tags and search"),
    ("surveys", "Surveys and forms", 300, "light", ("survey", "forms", "responses", "questions"),
     "Forms, responses and summaries"),
    ("analytics-bi", "BI workspace", 205, "dark", ("bi", "reports", "dashboards", "charts", "query"),
     "Queries, charts and saved reports"),
    ("monitoring", "Monitoring console", 175, "dark", ("monitoring", "services", "health", "incidents"),
     "Services, health and incidents"),
    ("field-service", "Field service", 30, "dark", ("field", "technicians", "jobs", "dispatch"),
     "Jobs, dispatch and completion"),
    ("emr", "Patient records", 165, "light", ("patients", "medical", "emr", "appointments"),
     "Patients, visits and notes"),
    ("school-sis", "School system", 255, "light", ("students", "classes", "grades", "attendance"),
     "Students, classes and grades"),
    ("gym", "Gym management", 350, "dark", ("gym", "members", "classes", "trainers"),
     "Members, classes and check-ins"),
    ("restaurant-orders", "Restaurant orders", 14, "dark", ("restaurant", "orders", "kitchen", "menu"),
     "Orders, kitchen board and menu"),
    ("hotel-pms", "Hotel PMS", 35, "light", ("hotel", "rooms", "reservations", "housekeeping"),
     "Rooms, reservations and housekeeping"),
    ("real-estate-crm", "Property CRM", 40, "light", ("properties", "listings", "viewings", "buyers"),
     "Properties, viewings and buyers"),
    ("legal-cases", "Case management", 240, "light", ("cases", "matters", "documents", "hearings"),
     "Cases, documents and deadlines"),
    ("insurance-claims", "Claims", 215, "light", ("claims", "policies", "adjusters", "payouts"),
     "Claims, policies and payouts"),
    ("pharmacy-inventory", "Pharmacy stock", 145, "light", ("medicines", "prescriptions", "stock", "batches"),
     "Medicines, batches and expiry"),
    ("library", "Library", 85, "light", ("books", "loans", "members", "catalogue"),
     "Catalogue, loans and members"),
    ("events", "Event management", 310, "vivid", ("event", "tickets", "attendees", "agenda"),
     "Events, tickets and attendees"),
    ("memberships", "Memberships", 290, "dark", ("members", "plans", "renewals", "benefits"),
     "Plans, renewals and benefits"),
    ("donations", "Donations", 130, "light", ("donations", "donors", "campaigns", "fundraising"),
     "Campaigns, donors and receipts"),
    ("billing", "Subscription billing", 160, "dark", ("billing", "plans", "invoices", "subscriptions"),
     "Plans, invoices and dunning"),
    ("marketplace", "Marketplace", 25, "vivid", ("marketplace", "sellers", "listings", "orders"),
     "Sellers, listings and orders"),
    ("social-feed", "Social feed", 315, "dark", ("feed", "posts", "followers", "likes"),
     "Posts, follows and a timeline"),
    ("delivery-tracking", "Delivery tracking", 32, "dark", ("delivery", "couriers", "tracking", "routes"),
     "Couriers, routes and live status"),
]

_PYTHON: list[tuple] = [
    ("desktop-crud", "Desktop CRUD app", 45, "dark",
     ("desktop", "crud", "table", "records", "track", "inventory"),
     "PyQt6 table, search, add form and totals"),
    ("pyqt-dashboard", "PyQt dashboard", 210, "dark", ("pyqt", "dashboard", "charts", "desktop"),
     "Desktop dashboard with charts and KPIs"),
    ("tkinter-tool", "Tkinter tool", 200, "light", ("tkinter", "tool", "form", "utility"),
     "Small Tkinter form tool"),
    ("cli-utility", "CLI utility", 160, "dark", ("cli", "command", "terminal", "script"),
     "Argument-driven command line tool"),
    ("web-scraper", "Web scraper", 25, "dark", ("scraper", "crawl", "scrape", "extract", "site"),
     "Fetch, parse and export pages"),
    ("data-analysis", "Data analysis", 195, "dark", ("analysis", "pandas", "csv", "dataset", "statistics"),
     "Load, clean and summarise a dataset"),
    ("report-generator", "Report generator", 230, "light", ("report", "pdf", "word", "monthly", "export"),
     "Build a document from data"),
    ("file-organizer", "File organiser", 40, "light", ("organise", "organize", "files", "folders", "sort"),
     "Sort and rename files safely"),
    ("backup-tool", "Backup tool", 15, "dark", ("backup", "copy", "archive", "restore"),
     "Copy, verify and restore a folder"),
    ("tray-utility", "Tray utility", 265, "dark", ("tray", "background", "hotkey", "notification"),
     "Background app with a tray icon"),
    ("pdf-tool", "PDF tool", 5, "light", ("pdf", "merge", "split", "pages"),
     "Merge, split and extract PDF pages"),
    ("image-tool", "Image tool", 300, "light", ("image", "resize", "crop", "watermark", "photos"),
     "Batch resize and watermark images"),
    ("log-analyzer", "Log analyser", 170, "dark", ("logs", "parse", "errors", "analyse", "analyze"),
     "Parse logs and report patterns"),
    ("scheduler", "Scheduler", 250, "light", ("schedule", "cron", "reminder", "job"),
     "Run tasks on a schedule"),
    ("api-server", "Local API server", 205, "dark", ("api", "fastapi", "flask", "endpoint", "server"),
     "Small FastAPI service with tests"),
    ("chatbot", "Local chatbot", 280, "dark", ("chatbot", "assistant", "llm", "chat"),
     "Chat UI over a local model"),
    ("spreadsheet-tool", "Spreadsheet tool", 130, "light", ("excel", "spreadsheet", "xlsx", "sheet"),
     "Read and write workbooks"),
    ("email-sender", "Email sender", 220, "light", ("email", "smtp", "send", "mail"),
     "Compose and send mail safely"),
    ("automation", "Automation script", 55, "dark", ("automation", "automate", "workflow", "script"),
     "Automate a repeated workflow"),
    ("game", "Python game", 330, "vivid", ("game", "pygame", "arcade", "player"),
     "Playable pygame game with a self-test"),
    ("converter", "File converter", 190, "light", ("convert", "converter", "format", "transcode"),
     "Convert between file formats"),
    ("test-runner", "Test runner", 145, "dark", ("tests", "pytest", "runner", "coverage"),
     "Discover and run tests with a report"),
]


def _rows(rows: list[tuple], kind: str) -> list[dict]:
    out = []
    for pid, label, hue, mood, words, summary in rows:
        out.append({
            # Kind-prefixed: "inventory" is both a dashboard and a web app, and
            # an id that resolves to the wrong kind would hand a dashboard
            # build a web app's palette.
            "id": f"{kind}-{pid}", "label": label, "kind": kind,
            "hue": int(hue) % 360,
            "mood": mood if mood in ("dark", "light", "vivid") else "dark",
            "keywords": tuple(words),
            "summary": summary,
        })
    return out


DASHBOARD_PRESETS: list[dict] = _rows(_DASHBOARDS, "dashboard")
WEBAPP_PRESETS: list[dict] = _rows(_WEBAPPS, "webapp")
PYTHON_PRESETS: list[dict] = _rows(_PYTHON, "python")

ALL_PRESETS: list[dict] = DASHBOARD_PRESETS + WEBAPP_PRESETS + PYTHON_PRESETS
_BY_ID: dict[str, dict] = {p["id"]: p for p in ALL_PRESETS}
_BY_KIND: dict[str, list[dict]] = {
    "dashboard": DASHBOARD_PRESETS,
    "webapp": WEBAPP_PRESETS,
    "python": PYTHON_PRESETS,
}


def get(preset_id: str) -> dict | None:
    return _BY_ID.get(str(preset_id or "").strip())


def presets_for(kind: str) -> list[dict]:
    return list(_BY_KIND.get(str(kind or "").strip().lower(), ALL_PRESETS))


def score_presets(brief: str, kind: str = "dashboard") -> list[tuple[int, str]]:
    text = (brief or "").lower()
    out: list[tuple[int, str]] = []
    for preset in presets_for(kind):
        score = 0
        for index, word in enumerate(preset["keywords"]):
            if re.search(rf"\b{re.escape(word)}\b", text):
                # The first keyword names what the preset *is* ("scraper",
                # "desktop"); the rest are supporting hints. Without the
                # distinction a brief that mentions "csv" could beat the
                # scraper it actually asked for.
                score += 3 if index == 0 else 2
        out.append((score, preset["id"]))
    return out


def choose_app_preset(brief: str, kind: str = "dashboard", seed: str = "") -> dict:
    """Best preset for this brief; near-ties vary with the brief's own hash."""
    kind = str(kind or "dashboard").strip().lower()
    if kind not in _BY_KIND:
        kind = "dashboard"
    scores = score_presets(brief, kind)
    best = max(score for score, _ in scores)
    tied = [pid for score, pid in scores if score == best]
    if best == 0:
        tied = [p["id"] for p in presets_for(kind)]
    ordered = sorted(tied)
    digest = hashlib.sha256((str(brief or "") + "|" + str(seed or "") + "|" + kind)
                            .encode("utf-8")).hexdigest()
    return _BY_ID[ordered[int(digest[:8], 16) % len(ordered)]]


def token_kwargs(preset: dict) -> dict:
    """The knobs ``core.design_system.build_tokens`` understands."""
    return {"hue": float(preset.get("hue", 210)), "mood": str(preset.get("mood") or "dark")}


def describe(preset: dict) -> str:
    """Prompt-ready description of the chosen preset."""
    if not preset:
        return ""
    return (f"DESIGN PRESET — {preset['label']} ({preset['kind']}): {preset['summary']}. "
            f"Palette hue {preset['hue']}°, {preset['mood']} mood; keep one accent "
            f"colour and the generated contrast ratios.")


__all__ = ["ALL_PRESETS", "DASHBOARD_PRESETS", "WEBAPP_PRESETS", "PYTHON_PRESETS",
           "choose_app_preset", "score_presets", "presets_for", "get",
           "token_kwargs", "describe"]
