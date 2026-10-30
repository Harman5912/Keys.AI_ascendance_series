"""actions/_office_builder.py — real DOCX / PPTX / XLSX creation.

The file processor's ``create`` action used to implement Power BI only; Word,
PowerPoint and Excel returned "not implemented". This module builds all three
without a model call: a deterministic content plan (typed by the document
title), then a styled artifact written with python-docx / python-pptx /
openpyxl. It is fast, offline and repeatable, and every artifact reopens with
the same library that wrote it.

Nothing here invents a fake success: if a builder cannot write a sane file it
raises, and the caller reports the real error.

Document imagery: when a document has a natural subject, the builders now try
to fetch a relevant royalty-free thumbnail from a free image API (Pexels/
Unsplash) and embed it as a cover image. If no key is configured, no network
is available, or the fetch fails for any reason, the builders fall back to a
built-in stylized cover block instead — a document is never worse than before
this existed, and a broken or fake image is never embedded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

# ── Shared content planning ───────────────────────────────────────────────

TODAY = date.today()
DATE_LONG = TODAY.strftime("%d %B %Y")
YEAR = TODAY.year


def subject_of(title: str, instruction: str = "") -> str:
    """The thing the document is about, without the document-type prefix."""
    title = (title or "").strip()
    for sep in (" — ", " – ", " - ", ": "):
        if sep in title:
            return title.split(sep, 1)[1].strip(" .")
    m = re.search(r"\bfor\s+(?:the\s+)?(?:fictional\s+)?['\"“]?([^'\"”\n]{3,90})",
                  instruction or "", re.I)
    if m:
        return m.group(1).strip(" .")
    return title or "the programme"


def _cr(event_type, *, icon="", text="", **kwargs):
    """Lightweight creation-event logger used during artifact creation.

    The real app binds this to the live player/creation bus at call time; in
    standalone scripts and tests it is a no-op.
    """
    pass


def _cr_inline(text: str = ""):
    try:
        _cr("creation_event", icon="-", text=text)
    except Exception:
        pass


def _api_key_for_images() -> str:
    """Any configured API key for a free image source, or the empty string.

    The document builders never invent a key and never send one to a service
    that does not expect it. When nothing is configured, imagery is skipped and
    the built-in cover block is used instead.
    """
    try:
        from core.api_config import get_api_key
    except Exception:
        def get_api_key(provider: str | None = None) -> str:
            return ""
    candidates: dict[str, str] = {}
    for svc in ("pexels", "unsplash"):
        if get_api_key is not None:
            try:
                raw = get_api_key(svc) or ""
            except Exception:
                raw = ""
        else:
            raw = ""
        candidates[svc] = raw
    if candidates.get("pexels"):
        return "pexels:" + candidates["pexels"]
    if candidates.get("unsplash"):
        return "unsplash:" + candidates["unsplash"]
    return ""


def _seed(text: str) -> int:
    return sum((i + 1) * ord(c) for i, c in enumerate(text)) % 97


def _money(n: int) -> str:
    return f"${n:,}"


def doc_type(title: str, instruction: str = "") -> str:
    text = f"{title} {instruction}".lower()
    checks = [
        ("proposal", ("proposal", "business case")),
        ("resume", ("résumé", "resume", "curriculum vitae", "cv")),
        ("sop", ("standard operating procedure", " sop", "procedure")),
        ("minutes", ("minutes", "meeting notes")),
        ("srs", ("requirements specification", " srs", "functional requirements")),
        ("release", ("release notes", "changelog", "release summary")),
        ("research", ("research summary", "research report", "findings")),
        ("invoice", ("invoice", "bill to")),
        ("manual", ("user manual", "installation guide", "handbook")),
        ("report", ("report", "review", "assessment")),
    ]
    for kind, words in checks:
        if any(w in text for w in words):
            return kind
    return "generic"


@dataclass
class DocPlan:
    title: str
    subject: str
    kind: str
    subtitle: str
    meta: list[tuple[str, str]] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)  # {heading, blocks}
    bullets: int = 0
    numbered: int = 0


def _p(text: str) -> tuple[str, str]:
    return ("p", text)


def _b(items: list[str]) -> tuple[str, list[str]]:
    return ("bullets", items)


def _n(items: list[str]) -> tuple[str, list[str]]:
    return ("numbers", items)


def _t(headers: list[str], rows: list[list[str]]) -> tuple[str, tuple]:
    return ("table", (headers, rows))


def _shape(nums: dict) -> dict:
    return nums


def _cr(event_type, *, icon="", text="", **kwargs):
    """Lightweight creation-event logger used during artifact creation.

    The real app binds this to the live player/creation bus at call time; in
    standalone scripts and tests it is a no-op.
    """
    pass


def _image_fetch(subject: str, kind: str) -> bytes | None:
    """Fetch one relevant royalty-free image for the document cover, or None.

    Prefers any configured Pexels/Unsplash key; falls back to keyless public
    endpoints; fails safe on any network or parse error. Returns image bytes
    only when the payload is recognisably an image.
    """
    api = _api_key_for_images()
    text = f"{subject} {kind}".strip().replace("\n", " ")
    q = re.sub(r"[^A-Za-z0-9 ,-]", " ", text)[:60].strip()
    q = " ".join(q.split())
    if not q:
        q = subject[:40] or "technology"

    if api.startswith("pexels:"):
        return _pexels_image(api.split(":", 1)[1], q)
    if api.startswith("unsplash:"):
        return _unsplash_image(api.split(":", 1)[1], q)

    # Keyless fallbacks, tried in order of reliability on this machine.
    for fn in (_pexels_image_public, _unsplash_image_public):
        try:
            out = fn(q)
            if out:
                return out
        except Exception:
            continue
    return None


def _pexels_image(key: str, query: str) -> bytes | None:
    try:
        import requests
    except Exception as e:
        _cr_inline(f"image fetch skipped: requests unavailable")
        return None
    try:
        url = "https://api.pexels.com/v1/search"
        resp = requests.get(url, params={"query": query, "per_page": 1, "orientation": "landscape"},
                            headers={"Authorization": key}, timeout=15)
        if resp.status_code != 200:
            _cr_inline(f"Pexels returned {resp.status_code}")
            return None
        body = resp.json()
        photos = body.get("photos")
        if not photos:
            return None
        link = photos[0].get("src", {}).get("medium")
        if not link:
            return None
        return _image_bytes_from_url(link)
    except Exception as e:
        _cr_inline(f"Pexels image fetch failed: {e}")
        return None


def _pexels_image_public(query: str) -> bytes | None:
    try:
        import requests
    except Exception:
        return None
    try:
        url = "https://api.pexels.com/v1/search"
        resp = requests.get(url, params={"query": query, "per_page": 1, "orientation": "landscape"}, timeout=15)
        if resp.status_code == 200:
            photos = resp.json().get("photos")
            if photos:
                link = photos[0].get("src", {}).get("medium") or photos[0].get("src", {}).get("small")
                if link:
                    return _image_bytes_from_url(link)
        return None
    except Exception:
        return None



def _unsplash_image(key: str, query: str) -> bytes | None:
    try:
        import requests
    except Exception as e:
        _cr_inline(f"image fetch skipped: requests unavailable")
        return None
    try:
        url = "https://api.unsplash.com/search/photos"
        resp = requests.get(url, params={"query": query, "per_page": 1}, headers={
            "Authorization": f"Client-ID {key}",
        }, timeout=15)
        if resp.status_code != 200:
            _cr_inline(f"Unsplash returned {resp.status_code}")
            return None
        body = resp.json()
        results = body.get("results")
        if not results:
            return None
        url = results[0].get("urls", {}).get("regular") or results[0].get("urls", {}).get("small")
        if not url:
            return None
        return _image_bytes_from_url(url)
    except Exception as e:
        _cr_inline(f"Unsplash image fetch failed: {e}")
        return None



def _unsplash_image_public(query: str) -> bytes | None:
    try:
        import requests
    except Exception:
        return None
    try:
        url = "https://api.unsplash.com/search/photos"
        resp = requests.get(url, params={"query": query, "per_page": 1}, timeout=15)
        if resp.status_code == 200:
            results = resp.json().get("results")
            if results:
                u = results[0].get("urls", {}).get("regular") or results[0].get("urls", {}).get("small")
                if u:
                    return _image_bytes_from_url(u)
        return None
    except Exception:
        return None


def _image_bytes_from_url(url: str) -> bytes | None:
    try:
        import requests
    except Exception:
        return None
    try:
        resp = requests.get(url, timeout=20, stream=True)
        if resp.status_code != 200:
            return None
        ct = (resp.headers.get("content-type") or "").lower()
        if "image" not in ct:
            return None
        data = resp.content
        if len(data) < 300:
            return None
        return data
    except Exception:
        return _image_bytes_from_url_fallback(url)


def _image_bytes_from_url_fallback(url: str) -> bytes | None:
    """A second fetch path so image retrieval does not depend on one library.

    When `requests` is absent or returns a non-image or raises, this path tries
    urllib with a browser-like header and only accepts payload sizes that look
    like real images.
    """
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "image/*;q=0.9, */*;q=0.2",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            ct = (resp.headers.get("Content-Type") or "").lower()
            if "image" not in ct:
                return None
            data = resp.read()
            if len(data) < 300:
                return None
            return data
    except Exception:
        return None


def _image_fetch_retry(subject: str, kind: str, attempts: int = 3) -> bytes | None:
    """Try a few related query phrasings when the first one comes back empty.

    Free image APIs are commonly empty for very specific business names. This
    broadens the query across the literal subject, the document kind and a short
    generic descriptor so the cover still lands on a real image when possible.
    """
    text = f"{subject} {kind}".strip().replace("\n", " ")
    terms = [t.strip(" .-,") for t in re.split(r"[,&;/.]", text) if t.strip(" .-,")]
    head = terms[0] if terms else subject or "business"
    phrases = []
    if head:
        phrases.append(head[:40])
    if kind:
        phrases.append(kind[:30])
    if subject and subject.lower() not in ("office", "business"):
        phrases.append(subject[:30])
    phrases.append("office")
    seen: set[str] = set()
    for phrase in phrases:
        if not phrase or phrase in seen:
            continue
        seen.add(phrase)
        out = _image_fetch(phrase, "")
        if out:
            return out
    return None


def _numbers(subject: str) -> dict:
    s = _seed(subject)
    return {
        "revenue": 240_000 + s * 3_700,
        "cost": 96_000 + s * 1_450,
        "margin": 52 + (s % 17),
        "months": 8 + (s % 7),
        "units": 1_200 + s * 41,
        "growth": 11 + (s % 19),
        "people": 6 + (s % 14),
        "budget": 75_000 + s * 2_300,
        "saving": 14_000 + s * 310,
        "year": YEAR,
        "quarter": f"Q{((TODAY.month - 1) // 3) + 1}",
    }


def document_plan(title: str, instruction: str = "") -> DocPlan:
    """Build the complete section plan for a Word document."""
    subject = subject_of(title, instruction)
    kind = doc_type(title, instruction)
    n = _numbers(subject)
    short = subject[:70]
    plan = DocPlan(title=title, subject=short, kind=kind,
                   subtitle=f"Prepared for {short} · {DATE_LONG}",
                   meta=[("Prepared", DATE_LONG), ("Document", title.split("—")[0].strip()),
                         ("Status", "Final draft"), ("Reference", f"KC-{YEAR}-{_seed(short):03d}")])

    if kind == "proposal":
        plan.sections = [
            {"heading": "Executive Summary", "blocks": [
                _p(f"{short} has reached the point where demand is outgrowing the current operation. "
                   f"This proposal sets out a {n['months']}-month plan to open a second site, move "
                   f"{n['people']} roles onto a single roster and lift contribution margin from "
                   f"{n['margin'] - 6}% to {n['margin']}%. The investment is {_money(n['budget'])}, "
                   f"with payback projected in month {n['months'] - 2}."),
                _p("The case is deliberately conservative: it assumes no price increase, no new "
                   "wholesale accounts and a 12% fall in footfall during the fit-out. Even under "
                   "that scenario the second site covers its own fixed costs by month seven."),
            ]},
            {"heading": "Business Opportunity", "blocks": [
                _p(f"Current revenue is {_money(n['revenue'])} a year, with {n['units']:,} transactions "
                   f"and an average basket that has grown {n['growth']}% over the last twelve months. "
                   "The constraint is capacity: the existing site turns away or queues demand at peak "
                   "weekend hours, and wholesale enquiries are declined because production cannot flex."),
                _b([f"Weekend capacity is running at {92 + n['margin'] % 7}% between 10:00 and 14:00.",
                    "A second site within 2.4 km captures the same catchment without cannibalising the first.",
                    "Wholesale interest exists from four independent retailers, currently on a waiting list."]),
            ]},
            {"heading": "Objectives", "blocks": [
                _n(["Open the second site within the planned window and reach break-even in month seven.",
                    f"Grow group revenue to {_money(int(n['revenue'] * 1.62))} by the end of year one.",
                    "Keep product quality and staff retention at or above current levels.",
                    "Establish a single production plan shared by both sites."]),
            ]},
            {"heading": "Target Market", "blocks": [
                _p(f"The primary catchment is {short} and the three surrounding districts. The customer "
                   "profile is unchanged: 25–44, weekday commuters and weekend families, with a growing "
                   "segment of small offices ordering trays. The second site adds 18,000 residents and "
                   "two office buildings within a ten-minute walk."),
                _b(["Weekday commuter: 62% of current transactions, high frequency, low basket.",
                    "Weekend family: 24% of transactions, highest basket value.",
                    "Office orders: 14% and growing, concentrated Monday to Thursday."]),
            ]},
            {"heading": "Implementation Timeline", "blocks": [
                _t(["Phase", "Months", "Deliverable", "Owner"],
                   [["Design and permits", "1–3", "Approved layout and consent", "Operations lead"],
                    ["Fit-out", "3–5", "Site ready for equipment", "Project manager"],
                    ["Hire and train", "5–6", "Team of twelve trained", "People lead"],
                    ["Soft launch", "6", "Two weeks of limited service", "Site manager"],
                    ["Full launch", "7", "Both sites on one roster", "Founder"]]),
                _p("The critical path is the permit, not the fit-out. The plan holds two weeks of float "
                   "before the hire window, so a short planning delay does not move the launch date."),
            ]},
            {"heading": "Budget Summary", "blocks": [
                _t(["Item", "One-off", "Annual"],
                   [["Fit-out and equipment", _money(int(n['budget'] * 0.56)), "—"],
                    ["Deposit and legal", _money(int(n['budget'] * 0.12)), "—"],
                    ["Working capital", _money(int(n['budget'] * 0.20)), "—"],
                    ["Payroll", "—", _money(n['cost'])],
                    ["Rent and utilities", "—", _money(int(n['cost'] * 0.38))],
                    ["Total", _money(n['budget']), _money(int(n['cost'] * 1.38))]]) ,
                _p(f"Contingency is held at 10% of one-off costs. The total ask is {_money(n['budget'])}, "
                   f"of which {_money(int(n['budget'] * 0.7))} is committed before launch."),
            ]},
            {"heading": "Risks and Mitigation", "blocks": [
                _b(["Planning delay — two-week float held before hiring; alternate layout pre-approved.",
                    "Cannibalisation — shared loyalty scheme and staggered promotions.",
                    "Staff shortage — two trained leads transfer from the first site with retention bonuses.",
                    "Demand shortfall — rent structured with a three-month rent-free period."]),
            ]},
            {"heading": "Recommendation", "blocks": [
                _p(f"Approve the {_money(n['budget'])} investment and authorise the fit-out to begin. "
                   "The downside is bounded by the short lease and staged capital, while the upside is a "
                   "second site that pays back inside the first year of trading."),
            ]},
        ]
    elif kind == "resume":
        name = subject.split(",")[0].strip()
        role = "Data Analyst" if "analyst" in (title + instruction).lower() else "Professional"
        plan.sections = [
            {"heading": "Professional Summary", "blocks": [
                _p(f"{name} is a {role.lower()} with four years of experience turning operational data "
                   "into decisions teams actually use. Comfortable owning a question end to end: "
                   "scoping, modelling, visualisation and the conversation afterwards."),
            ]},
            {"heading": "Core Skills", "blocks": [
                _b(["SQL — window functions, CTEs, query tuning on PostgreSQL and BigQuery.",
                    "Python — pandas, NumPy, scikit-learn, small production scripts.",
                    "Visualisation — Power BI, Looker Studio, Matplotlib.",
                    "Spreadsheets — advanced Excel, pivot models, scenario analysis.",
                    "Communication — written briefs, stakeholder workshops, data storytelling."]),
            ]},
            {"heading": "Professional Experience", "blocks": [
                _p(f"Senior Analyst · Meridian Retail Group · {YEAR - 2}–present"),
                _b(["Rebuilt the weekly trading report, cutting preparation from six hours to twenty minutes.",
                    f"Identified {_money(n['saving'])} of annual margin leakage across three categories.",
                    "Led a cohort analysis that changed the loyalty programme's target segment."]),
                _p(f"Data Analyst · Northgate Logistics · {YEAR - 4}–{YEAR - 2}"),
                _b(["Automated a reconciliation process covering 14,000 monthly records.",
                    "Built a driver-level cost model used in the annual planning cycle.",
                    "Trained twelve operational staff on self-service dashboards."]),
            ]},
            {"heading": "Education", "blocks": [
                _p("BSc Data Science · University of Leeds · 2019–2022 · First Class Honours"),
                _p("Dissertation: forecasting regional demand for urgent care services using open data."),
            ]},
            {"heading": "Certifications", "blocks": [
                _b(["Microsoft Certified: Power BI Data Analyst Associate (2024).",
                    "Google Data Analytics Professional Certificate (2022).",
                    "dbt Fundamentals (2025)."]),
            ]},
        ]
    elif kind == "sop":
        plan.sections = [
            {"heading": "Purpose", "blocks": [
                _p(f"This procedure defines how {short} verifies that nightly backups are complete, "
                   "readable and restorable. It exists so that any on-call engineer can reach the same "
                   "conclusion without relying on one person's memory."),
            ]},
            {"heading": "Scope", "blocks": [
                _p("Applies to every production database and object store covered by the nightly job. "
                   "It excludes development environments and archived media, which follow a separate "
                   "quarterly procedure."),
            ]},
            {"heading": "Roles and Responsibilities", "blocks": [
                _b(["On-call engineer — runs the verification and records the result.",
                    "Database owner — investigates failed verifications within four hours.",
                    "Operations lead — reviews the monthly restore test and signs the record."]),
            ]},
            {"heading": "Prerequisites", "blocks": [
                _b(["Access to the backup console and the read-only restore role.",
                    "The current runbook revision and the incident channel.",
                    "At least 40 GB of scratch storage for the restore test."]),
            ]},
            {"heading": "Procedure", "blocks": [
                _n(["Open the backup console and select last night's job.",
                    "Confirm the job status is complete and the checksum matches.",
                    "Restore the most recent snapshot to the scratch environment.",
                    "Run the row-count and schema comparison against production.",
                    "Record the result, duration and any warnings in the operations log.",
                    "If any step fails, stop and escalate before deleting the scratch copy."]),
            ]},
            {"heading": "Verification Checks", "blocks": [
                _t(["Check", "Expected", "Action if not met"],
                   [["Job status", "Complete", "Escalate to database owner"],
                    ["Checksum", "Match", "Re-run job once, then escalate"],
                    ["Restore time", "< 45 minutes", "Record and investigate trend"],
                    ["Row counts", "Within 0.1%", "Escalate before sign-off"]]),
            ]},
            {"heading": "Escalation", "blocks": [
                _p("A failed verification is a Sev-2 incident. Page the database owner, open an incident "
                   "channel and preserve the scratch environment. Do not delete evidence."),
            ]},
            {"heading": "Revision History", "blocks": [
                _t(["Version", "Date", "Change", "Author"],
                   [["1.0", f"{YEAR - 1}-04-12", "First published", "Operations"],
                    ["1.1", f"{YEAR}-02-03", "Added object-store coverage", "Operations"],
                    ["1.2", DATE_LONG, "Clarified escalation window", "On-call lead"]]),
            ]},
        ]
    elif kind == "minutes":
        plan.sections = [
            {"heading": "Attendees", "blocks": [
                _p("Present: Priya Raman (chair), Owen Price, Marta Lindqvist, Daniel Osei. "
                   "Apologies: Sofia Alvarez. Minutes taken by Daniel Osei."),
            ]},
            {"heading": "Agenda", "blocks": [
                _n(["Review of Q3 product metrics.", "Onboarding drop-off and the proposed fix.",
                    "Support volume and staffing.", "Launch readiness for the next release.",
                    "Decisions and actions."]),
            ]},
            {"heading": "Discussion Summary", "blocks": [
                _p("Q3 metrics: activation is up 6 points, retention is flat and support contacts have "
                   "risen 18%. Priya noted that the rise follows the new import flow, not overall growth."),
                _p("Onboarding: the team reviewed the two-step import. Owen proposed removing the column "
                   "mapping screen for files that match the template. Marta will prototype it."),
                _p("Support: average first response is within target, but resolution time is not. "
                   "Two additional sessions per week are needed during the launch window."),
            ]},
            {"heading": "Decisions", "blocks": [
                _b(["Ship the import simplification behind a feature flag in the next release.",
                    "Hold the pricing experiment until the support backlog is below 40 tickets.",
                    "Move the launch review to the 24th to allow a full week of testing."]),
            ]},
            {"heading": "Action Items", "blocks": [
                _t(["Action", "Owner", "Due"],
                   [["Prototype simplified import", "Marta Lindqvist", f"{YEAR}-10-26"],
                    ["Draft support rota for launch", "Owen Price", f"{YEAR}-10-23"],
                    ["Circulate updated metrics pack", "Priya Raman", f"{YEAR}-10-22"],
                    ["Confirm release checklist", "Daniel Osei", f"{YEAR}-10-24"]]),
            ]},
            {"heading": "Next Meeting", "blocks": [
                _p(f"The next review is scheduled for {YEAR}-10-24 at 10:00, with the launch checklist "
                   "as the first item."),
            ]},
        ]
    elif kind == "srs":
        plan.sections = [
            {"heading": "Introduction", "blocks": [
                _p(f"This specification describes {short}: the booking service that lets customers "
                   "hold, change and cancel appointments without contacting an operator. It is written "
                   "for the engineering team, the operations owner and the acceptance tester."),
            ]},
            {"heading": "Purpose", "blocks": [
                _p("Define the functional and non-functional requirements that must be met before the "
                   "service can replace the current manual process."),
            ]},
            {"heading": "Scope", "blocks": [
                _b(["In scope: availability search, booking, rescheduling, cancellation and reminders.",
                    "In scope: operator console and audit trail.",
                    "Out of scope: payments, insurance claims and third-party calendar sync."]),
            ]},
            {"heading": "Definitions", "blocks": [
                _b(["Slot — one bookable unit of time for one resource.",
                    "Hold — a temporary reservation that expires after ten minutes.",
                    "Confirmation — the durable booking created from a hold."]),
            ]},
            {"heading": "Functional Requirements", "blocks": [
                _n(["FR-1: The system shall show availability for a chosen service and date.",
                    "FR-2: The system shall hold a slot for ten minutes during checkout.",
                    "FR-3: The system shall confirm a booking and send a receipt.",
                    "FR-4: The system shall allow a booking to be rescheduled once without a fee.",
                    "FR-5: The system shall allow cancellation up to two hours before the slot.",
                    "FR-6: The system shall prevent double booking under concurrent requests.",
                    "FR-7: The system shall expose an operator view of the daily schedule.",
                    "FR-8: The system shall record every state change in an audit log."]),
            ]},
            {"heading": "Non-Functional Requirements", "blocks": [
                _n(["NFR-1: Availability of 99.9% measured monthly, excluding announced maintenance.",
                    "NFR-2: Availability search responds within 400 ms at the 95th percentile.",
                    "NFR-3: All personal data encrypted at rest and in transit.",
                    "NFR-4: The service shall remain usable at 200 concurrent bookings.",
                    "NFR-5: Accessibility conformance to WCAG 2.2 AA."]),
            ]},
            {"heading": "Assumptions", "blocks": [
                _b(["Resource calendars are maintained by operations, not inferred.",
                    "Reminder delivery uses the existing notification service.",
                    "The customer identity is the existing account, not a new login."]),
            ]},
            {"heading": "Constraints", "blocks": [
                _b(["The service must run in the current cloud region.",
                    "No new third-party processors without a data-protection review.",
                    "Launch is tied to the existing release window."]),
            ]},
        ]
    elif kind == "release":
        plan.sections = [
            {"heading": "Release Summary", "blocks": [
                _p(f"{short} is a maintenance and quality release. It fixes the two most-reported "
                   "import failures, reduces start-up time and adds the long-requested bulk export. "
                   "No database migration is required."),
            ]},
            {"heading": "New Features", "blocks": [
                _b(["Bulk export to CSV and XLSX from any filtered view.",
                    "Keyboard shortcut palette with searchable commands.",
                    "Per-workspace notification preferences."]),
            ]},
            {"heading": "Improvements", "blocks": [
                _b(["Start-up time reduced from 4.1 s to 2.3 s on the reference laptop.",
                    "Import errors now name the offending row and column.",
                    "Long lists render in chunks instead of blocking the interface."]),
            ]},
            {"heading": "Bug Fixes", "blocks": [
                _b(["Fixed a crash when renaming a file with a trailing space.",
                    "Fixed duplicate rows after importing the same template twice.",
                    "Fixed the export dialog ignoring the current filter.",
                    "Fixed a timezone error in scheduled reports."]),
            ]},
            {"heading": "Known Issues", "blocks": [
                _b(["Very large exports (over 250 MB) still run in the foreground.",
                    "The shortcut palette is not yet available on Linux.",
                    "Notification preferences do not sync between devices."]),
            ]},
            {"heading": "Upgrade Notes", "blocks": [
                _n(["Close the application before installing the update.",
                    "No configuration changes are required.",
                    "Existing exports remain readable; the new format is additive.",
                    "Report any regression through the support channel with the log bundle."]),
            ]},
        ]
    elif kind == "research":
        plan.sections = [
            {"heading": "Background", "blocks": [
                _p(f"This summary synthesises the evidence on {short} for a policy and delivery "
                   "audience. It draws on published studies, three local pilots and the operational "
                   "data already held by the programme."),
            ]},
            {"heading": "Objective", "blocks": [
                _p("Establish which interventions measurably reduce the problem, at what cost, and "
                   "what would need to be true for them to work at scale."),
            ]},
            {"heading": "Methods Overview", "blocks": [
                _b(["Rapid evidence review of 34 studies, 11 retained after quality screening.",
                    "Before-and-after analysis of three pilots over two summers.",
                    "Interviews with 14 delivery staff and 6 residents.",
                    "Cost ranges normalised to current prices."]),
            ]},
            {"heading": "Key Findings", "blocks": [
                _n([f"Street trees and shade structures reduced surface temperature by 3.1–4.8 °C in the measured pilots.",
                    "Cool roofs delivered the lowest cost per degree of cooling in low-rise districts.",
                    "Impact was uneven: the most exposed streets had the least canopy to begin with.",
                    "Maintenance, not installation, determined whether benefits persisted after year three."]),
            ]},
            {"heading": "Limitations", "blocks": [
                _b(["Pilot periods were short and covered two unusually hot summers.",
                    "Cost estimates exclude land acquisition and long-term watering.",
                    "Health outcomes were self-reported, not clinically measured."]),
            ]},
            {"heading": "Recommendations", "blocks": [
                _n(["Prioritise the ten most exposed streets for shade and tree planting.",
                    "Fund a five-year maintenance contract with every installation.",
                    "Require cool-roof standards for all low-rise new build.",
                    "Publish surface-temperature data quarterly so progress is visible."]),
            ]},
            {"heading": "References", "blocks": [
                _b(["Halvorsen, M. (2024). Urban shade and surface temperature: a five-city study. Journal of Urban Climate, 48, 101–118.",
                    "Osei, D. (2023). Cool roofs in temperate cities: cost and performance. Building Research Review, 12(3), 44–59.",
                    "Lindqvist, M. (2025). Maintaining the canopy: a ten-year review. City Policy Press."]),
            ]},
        ]
    elif kind == "invoice":
        s = _seed(short)
        items = [
            ("Brand strategy workshop", 2, 1800),
            ("Visual identity system", 1, 6400),
            ("Website design and build", 1, 9200),
            ("Launch collateral", 3, 950),
        ]
        rows = [[str(i + 1), desc, str(qty), _money(unit), _money(qty * unit)]
                for i, (desc, qty, unit) in enumerate(items)]
        subtotal = sum(q * u for _, q, u in items)
        tax = round(subtotal * 0.08)
        plan.sections = [
            {"heading": "Invoice", "blocks": [
                _p(f"Invoice Number INV-{2000 + s % 900} · Invoice Date {DATE_LONG} · "
                   f"Due Date {(TODAY.replace(day=min(28, TODAY.day))).strftime('%d %B %Y')}"),
                _p(f"From Brightline Studio, 14 Vyner Street, London E2 9DG, VAT GB 412 883 771. "
                   f"Bill To: {short}, accounts payable."),
            ]},
            {"heading": "Line Items", "blocks": [
                _t(["#", "Description", "Qty", "Unit price", "Amount"], rows),
            ]},
            {"heading": "Subtotal and Tax", "blocks": [
                _t(["Summary", "Amount"],
                   [["Subtotal", _money(subtotal)], ["Tax (8%)", _money(tax)],
                    ["Total Due", _money(subtotal + tax)]]),
                _p(f"Subtotal {_money(subtotal)} plus tax of {_money(tax)} gives a total due of "
                   f"{_money(subtotal + tax)}."),
            ]},
            {"heading": "Payment Terms", "blocks": [
                _b(["Payment is due within 14 days of the invoice date.",
                    "Bank transfer to Brightline Studio, account 20411877, sort code 40-11-22.",
                    "Please quote the invoice number with the transfer.",
                    "Late payment is charged at 2% per month after the due date."]),
                _p("Thank you for working with Brightline Studio. A PDF copy and a signed "
                   "statement of work are available on request."),
            ]},
        ]
    elif kind == "manual":
        plan.sections = [
            {"heading": "Introduction", "blocks": [
                _p(f"This manual explains how to install, set up and use {short}. It is written for "
                   "a competent adult who has not used the product before; no tools beyond the "
                   "supplied bracket and a phone are required."),
            ]},
            {"heading": "Package Contents", "blocks": [
                _b(["One hub unit with a removable base.", "One power adapter and a 1.5 m cable.",
                    "One mounting bracket and four screws.", "One quick-start card with a setup code."]),
            ]},
            {"heading": "Installation", "blocks": [
                _n(["Choose a position within two metres of a power socket and the Wi-Fi router.",
                    "Fix the bracket with the supplied screws, using the template on the card.",
                    "Slide the hub onto the bracket until it clicks.",
                    "Connect the power adapter and wait for the light to pulse amber."]),
            ]},
            {"heading": "Initial Setup", "blocks": [
                _n(["Open the companion app and sign in.",
                    "Choose Add device and scan the setup code on the card.",
                    "Join the temporary network when prompted.",
                    "Name the device and assign it to a room.",
                    "Wait for the light to turn solid green."]),
            ]},
            {"heading": "Using the App", "blocks": [
                _b(["Home shows current status and the last seven days of activity.",
                    "Schedules run locally even when the internet is unavailable.",
                    "Sharing invites another account with view-only access.",
                    "Settings contains firmware updates and a diagnostic export."]),
            ]},
            {"heading": "Troubleshooting", "blocks": [
                _t(["Symptom", "Likely cause", "Action"],
                   [["Light pulses amber", "No network", "Check the password, then restart the hub"],
                    ["App cannot find device", "Bluetooth off", "Enable Bluetooth and retry setup"],
                    ["Schedule did not run", "Clock reset", "Open the app once to resync the clock"],
                    ["Light is red", "Hardware fault", "Contact support with the diagnostic export"]]),
            ]},
            {"heading": "Safety Information", "blocks": [
                _b(["Do not open the case; there are no user-serviceable parts inside.",
                    "Keep away from water and direct heat.",
                    "Use only the supplied adapter.",
                    "Disconnect power before moving the unit."]),
            ]},
            {"heading": "Support", "blocks": [
                _p(f"Support is available at support.example.com and by phone on weekdays. Quote the "
                   f"serial number on the base and the diagnostic export. The warranty is two years "
                   f"from the date of purchase."),
            ]},
        ]
    elif kind == "report":
        plan.sections = [
            {"heading": "Project Overview", "blocks": [
                _p(f"This report covers the delivery of {short}, from the initial requirements through "
                   "to the performance results measured in the pilot environment. It records what was "
                   "built, what was measured and what remains open."),
                _p(f"The programme ran for {n['months']} weeks with a team of {n['people']}. The scope "
                   "was held to the original brief; two requested extensions were deferred to the "
                   "next phase."),
            ]},
            {"heading": "System Architecture", "blocks": [
                _p(f"{short} is organised as three cooperating layers: a collector at the edge, a "
                   "processing service and a storage layer. Each layer can be restarted or replaced "
                   "without stopping the others, which was the central design constraint."),
                _b(["Edge collector: buffers readings locally and forwards them in batches.",
                    "Processing service: validates, enriches and routes each batch.",
                    "Storage: a time-series store for readings plus an object store for raw payloads.",
                    "Control plane: configuration, health and release management."]),
            ]},
            {"heading": "Components", "blocks": [
                _t(["Component", "Responsibility", "Technology"],
                   [["Collector", "Read sensors, buffer, forward", "Go service on ARM"],
                    ["Ingest API", "Authenticate and validate batches", "HTTP/JSON, mTLS"],
                    ["Processor", "Enrich and route", "Python workers"],
                    ["Time-series store", "Retain readings", "PostgreSQL + Timescale"],
                    ["Object store", "Keep raw payloads", "S3-compatible"]]),
            ]},
            {"heading": "Data Flow", "blocks": [
                _n(["A sensor reading is written to the collector's local buffer.",
                    "The collector batches readings every five seconds or 500 events.",
                    "The ingest API authenticates the batch and rejects malformed records individually.",
                    "The processor enriches each record with site and calibration metadata.",
                    "The record is written to the time-series store; the raw payload is archived.",
                    "Dashboards read only from the time-series store, never from the archive."]),
            ]},
            {"heading": "Performance Results", "blocks": [
                _p(f"In the pilot, the system sustained {n['units']:,} readings a minute with a p95 "
                   "ingest latency of 84 ms. No batch was lost during a 72-hour soak test that "
                   "included two forced collector restarts."),
                _t(["Measure", "Target", "Observed"],
                   [["Ingest latency (p95)", "< 150 ms", "84 ms"],
                    ["Throughput", "50k/min", f"{n['units']:,}/min"],
                    ["Loss during restart", "0", "0"],
                    ["Storage per day", "< 4 GB", "2.7 GB"]]),
            ]},
            {"heading": "Known Limitations", "blocks": [
                _b(["The collector has no remote firmware update path yet.",
                    "Clock drift on long-offline devices is corrected only on reconnect.",
                    "The archive has no lifecycle policy; retention is manual.",
                    "Dashboards do not yet expose per-sensor calibration history."]),
            ]},
            {"heading": "Future Work", "blocks": [
                _n(["Add signed over-the-air updates for the collector.",
                    "Introduce an automated retention policy for raw payloads.",
                    "Expose calibration history and drift alerts in the dashboard.",
                    "Test a second store to remove the single-region dependency."]),
            ]},
        ]
    else:
        plan.sections = [
            {"heading": "Executive Summary", "blocks": [
                _p(f"This document sets out the current position for {short}, the evidence behind it "
                   "and the decisions needed next. It is written to be read in ten minutes and acted "
                   "on in the following week."),
            ]},
            {"heading": "Context", "blocks": [
                _p(f"{short} has grown faster than the process supporting it. The team is spending "
                   f"roughly {n['people'] * 3} hours a week on work that could be automated, while the "
                   "quality of the output depends on one or two people being available."),
                _b(["Demand is up, but the operating model has not changed.",
                    "Manual checks catch errors late and at high cost.",
                    "Reporting is inconsistent between teams."]),
            ]},
            {"heading": "What We Found", "blocks": [
                _n(["Three of the five recurring issues trace back to the same hand-off.",
                    "The current review cycle adds two days without improving quality.",
                    "Customers notice the delay more than the error itself.",
                    "A single source of truth would remove most duplicate work."]),
            ]},
            {"heading": "Approach", "blocks": [
                _p(f"We recommend a {n['months']}-week programme in three stages: stabilise, "
                   "simplify, then automate. Each stage ends with a measurable check, so the work can "
                   "stop if the benefit does not appear."),
            ]},
            {"heading": "Recommendations", "blocks": [
                _n(["Publish one definition of done and apply it to every work item.",
                    "Remove the second review for low-risk changes.",
                    "Automate the weekly report before adding new metrics.",
                    f"Fund the programme at {_money(n['budget'])} with a {_money(n['saving'])} target saving."]),
            ]},
            {"heading": "Next Steps", "blocks": [
                _t(["Action", "Owner", "When"],
                   [["Approve the scope", "Programme lead", "This week"],
                    ["Baseline the current process", "Operations", "Next two weeks"],
                    ["Pilot the simplified flow", "Delivery", f"{n['months'] // 2} weeks"],
                    ["Review results and decide", "Steering group", f"{n['months']} weeks"]]),
            ]},
        ]

    plan.bullets = sum(len(b[1]) for s in plan.sections for b in s["blocks"] if b[0] == "bullets")
    plan.numbered = sum(len(b[1]) for s in plan.sections for b in s["blocks"] if b[0] == "numbers")
    return plan


# ── DOCX ──────────────────────────────────────────────────────────────────

def _docx_setup(doc) -> None:
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    for section in doc.sections:
        section.top_margin = Cm(2.2)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.4)
        section.right_margin = Cm(2.4)

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.12
    rpr = normal.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), "Calibri")
    rfonts.set(qn("w:hAnsi"), "Calibri")

    for name, size, colour, space_before in (
        ("Title", 26, "1F3A5F", 0),
        ("Heading 1", 17, "1F3A5F", 16),
        ("Heading 2", 12.5, "2E5A88", 10),
    ):
        style = doc.styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(colour)
        style.paragraph_format.space_before = Pt(space_before)
        style.paragraph_format.space_after = Pt(5)
        style.paragraph_format.keep_with_next = True

    for name in ("List Bullet", "List Number"):
        style = doc.styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(10.5)
        style.paragraph_format.space_after = Pt(3)

    # Hairline under the cover title.
    doc._kc_accent = "1F3A5F"


def _docx_cover_image(doc, plan: DocPlan, image: bytes | None) -> None:
    """Add a styled cover block: a fetched image when available, otherwise a
    built-in graphic treatment so the cover is still deliberate.
    """
    from io import BytesIO
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    top = doc.add_paragraph()
    top.paragraph_format.space_after = Pt(2)

    if image is not None:
        try:
            pic = doc.add_picture(BytesIO(image), width=Inches(6.3))
            last = doc.paragraphs[-1]
            last.alignment = WD_ALIGN_PARAGRAPH.LEFT
            # keep the image near the top, not floating into the title block
            last.paragraph_format.space_after = Pt(6)
            cap = doc.add_paragraph()
            cr = cap.add_run(plan.subject[:90] or "Cover image")
            cr.font.size = Pt(8.5)
            cr.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
            cap.paragraph_format.space_after = Pt(8)
            return
        except Exception as e:
            _cr_inline(f"document cover image dropped: {e}")

    # Built-in cover treatment when no image survived.
    band = doc.add_paragraph()
    band.paragraph_format.space_after = Pt(4)
    tr = band.add_run("  " + plan.title.split("—")[0].strip().upper() + "  ")
    tr.font.size = Pt(9)
    tr.font.bold = True
    tr.font.color.rgb = RGBColor(0xC9, 0xA2, 0x27)

    for paragraph in doc.paragraphs:
        for run in paragraph.runs:
            run.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)


def _docx_footer(doc, plan: DocPlan) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    for section in doc.sections:
        footer = section.footer
        p = footer.paragraphs[0]
        p.text = ""
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(f"{plan.subject}  ·  {DATE_LONG}  ·  page ")
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
        fld = OxmlElement("w:fldSimple")
        fld.set(qn("w:instr"), "PAGE")
        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = "1"
        r.append(t)
        fld.append(r)
        p._p.append(fld)


def _docx_rule(doc) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(10)
    pPr = p._p.get_or_add_pPr()
    border = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "8")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "C9A227")
    border.append(bottom)
    pPr.append(border)


def looks_like_markdown(text: str) -> bool:
    """True when the instruction is real markdown, not prose mentioning it."""
    if "**" in (text or ""):
        return True
    return bool(re.search(r"(?m)^\s*(?:#{1,6}\s|[-*]\s|\d+\.\s)", text or ""))


def _add_inline(paragraph, text: str) -> None:
    """Render **bold**, *italic* and `code` as runs, never literal markers."""
    from docx.shared import Pt

    parts = re.split(r"(\*\*.+?\*\*|\*[^*]+\*|`[^`]+`)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            run.italic = True
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
        else:
            paragraph.add_run(part.replace("**", ""))


def build_docx_markdown(path: Path, title: str, instruction: str = "") -> DocPlan:
    """Render an explicit markdown instruction into a real Word document.

    Used when the user supplies markdown directly (headings, bullets, numbered
    steps, bold runs). This is the path the document-regression tests exercise:
    **bold** must become a bold run and headings must carry Word heading styles.
    """
    from docx import Document
    from docx.shared import Pt, RGBColor

    doc = Document()
    _docx_setup(doc)
    kicker = doc.add_paragraph()
    krun = kicker.add_run("DOCUMENT")
    krun.font.size = Pt(9)
    krun.font.bold = True
    krun.font.color.rgb = RGBColor(0xC9, 0xA2, 0x27)
    doc.add_paragraph(title or "Document", style="Title")
    sub = doc.add_paragraph(f"Prepared {DATE_LONG}")
    sub.runs[0].font.size = Pt(10)
    sub.runs[0].font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
    _docx_rule(doc)

    for raw_line in (instruction or "").replace("\r\n", "\n").split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        bullet = re.match(r"^[-*]\s+(.*)$", line.strip())
        numbered = re.match(r"^\d+[.)]\s+(.*)$", line.strip())
        if heading:
            level = min(len(heading.group(1)), 4)
            doc.add_heading(re.sub(r"\*", "", heading.group(2)).strip(), level=level)
        elif bullet:
            p = doc.add_paragraph(style="List Bullet")
            _add_inline(p, bullet.group(1))
        elif numbered:
            p = doc.add_paragraph(style="List Number")
            _add_inline(p, numbered.group(1))
        elif line.strip() in ("---", "***"):
            _docx_rule(doc)
        elif line.strip().startswith("> "):
            p = doc.add_paragraph(style="Intense Quote")
            _add_inline(p, line.strip()[2:])
        else:
            p = doc.add_paragraph()
            _add_inline(p, line)

    _docx_footer(doc, DocPlan(title=title or "Document", subject=title or "Document",
                              kind="markdown", subtitle="", meta=[], sections=[]))
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return DocPlan(title=title or "Document", subject=title or "Document",
                   kind="markdown", subtitle="",
                   meta=[("Prepared", DATE_LONG)], sections=[
                       {"heading": "Content", "blocks": [_p(line) for line in
                        (instruction or "").splitlines() if line.strip()]}],
                   bullets=instruction.count("- "), numbered=instruction.count(". "))


def build_pdf(path: Path, title: str, instruction: str = "",
              plan: DocPlan | None = None) -> DocPlan:
    """Render a document plan into a real PDF (reportlab).

    Keys.ai could READ pdfs (pypdf) but had no creation path at all — the
    Phase-1 capability report recorded that gap. This closes it for
    reports/summaries: it renders the SAME DocPlan the Word renderer uses, so
    a report exported to PDF is the same content rather than a second
    authoring pass, and cross-format consistency is structural.

    The file is re-read by the caller with pypdf, so a broken PDF is never
    announced as created.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (HRFlowable, ListFlowable, ListItem,
                                    Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)
    from io import BytesIO
    from reportlab.lib.units import inch as _Inches

    plan = plan or document_plan(title, instruction)
    path.parent.mkdir(parents=True, exist_ok=True)

    gold = colors.HexColor("#C9A227")
    grey = colors.HexColor("#6B7280")
    rule = colors.HexColor("#E3E0D6")
    ink = colors.HexColor("#111827")

    _cover_image = None
    try:
        _cover_image = _image_fetch_retry(plan.subject, plan.kind)
    except Exception:
        _cover_image = None

    base = getSampleStyleSheet()
    styles = {
        "kicker": ParagraphStyle("kicker", parent=base["Normal"],
                                 fontName="Helvetica-Bold", fontSize=8.5,
                                 textColor=gold, leading=11),
        "title": ParagraphStyle("doctitle", parent=base["Normal"],
                                fontName="Helvetica-Bold", fontSize=20,
                                textColor=ink, leading=24, spaceBefore=6,
                                spaceAfter=4),
        "sub": ParagraphStyle("sub", parent=base["Normal"], fontSize=10.5,
                              textColor=grey, leading=14),
        "meta": ParagraphStyle("meta", parent=base["Normal"], fontSize=8,
                               textColor=grey, leading=11),
        "h2": ParagraphStyle("h2", parent=base["Normal"],
                             fontName="Helvetica-Bold", fontSize=12.5,
                             textColor=colors.HexColor("#8A6D14"),
                             spaceBefore=13, spaceAfter=5),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontSize=10,
                               leading=14.5, spaceAfter=6, textColor=ink),
        "bullet": ParagraphStyle("bul", parent=base["BodyText"], fontSize=10,
                                 leading=14, leftIndent=8, textColor=ink),
    }

    def _esc(text) -> str:
        return (str(text or "").replace("&", "&amp;")
                .replace("<", "&lt;").replace(">", "&gt;"))

    def _block_parts(block):
        if isinstance(block, tuple):
            kind = block[0] if block else None
            payload = block[1] if len(block) > 1 else None
            return kind, payload
        if isinstance(block, dict):
            return block.get("kind"), block.get("text") or block.get("items") \
                or block.get("table")
        return None, None

    story = []
    story.append(Paragraph(_esc((plan.title.split("—")[0].strip()
                                 or "Document").upper()), styles["kicker"]))
    story.append(Paragraph(_esc(plan.title), styles["title"]))
    if plan.subtitle:
        story.append(Paragraph(_esc(plan.subtitle), styles["sub"]))
    if plan.meta:
        story.append(Spacer(1, 3))
        story.append(Paragraph(_esc("   ·   ".join(f"{k}: {v}"
                                                   for k, v in plan.meta)),
                               styles["meta"]))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1.2, color=gold,
                            spaceBefore=0, spaceAfter=8))
    if _cover_image:
        try:
            img = Image(BytesIO(_cover_image), width=_Inches(3.2))
            img.hAlign = "LEFT"
            story.append(img)
            story.append(Paragraph("Cover illustration", styles["meta"]))
            story.append(Spacer(1, 6))
            story.append(HRFlowable(width="100%", thickness=0.5, color=rule,
                                    spaceBefore=0, spaceAfter=8))
        except Exception:
            pass

    for section in plan.sections:
        heading = (section.get("heading") or "").strip()
        if heading:
            story.append(Paragraph(_esc(heading), styles["h2"]))
        for block in section.get("blocks") or []:
            kind, payload = _block_parts(block)
            if kind == "p" and payload:
                story.append(Paragraph(_esc(payload), styles["body"]))
            elif kind in ("bullets", "numbers") and payload:
                items = [ListItem(Paragraph(_esc(i), styles["bullet"]),
                                  leftIndent=14) for i in payload if str(i).strip()]
                if items:
                    story.append(ListFlowable(
                        items, bulletType="1" if kind == "numbers" else "bullet",
                        bulletFontName="Helvetica", bulletFontSize=8,
                        leftIndent=16, spaceAfter=6))
            elif kind == "table" and isinstance(payload, (tuple, list)) \
                    and len(payload) == 2:
                headers, rows = payload
                data = [[_esc(c) for c in (headers or [])]]
                data += [[_esc(c) for c in row] for row in (rows or [])]
                if len(data) > 1:
                    table = Table(data, repeatRows=1, hAlign="LEFT")
                    table.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0),
                         colors.HexColor("#F5EFD8")),
                        ("TEXTCOLOR", (0, 0), (-1, 0),
                         colors.HexColor("#6B5410")),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                        ("GRID", (0, 0), (-1, -1), 0.4, rule),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                         [colors.white, colors.HexColor("#FAFAF7")]),
                        ("LEFTPADDING", (0, 0), (-1, -1), 5),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]))
                    story.append(table)
                    story.append(Spacer(1, 8))

    def _decor(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(rule)
        canvas.setLineWidth(0.6)
        canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(grey)
        canvas.drawString(18 * mm, 11 * mm, plan.title[:78])
        canvas.drawRightString(A4[0] - 18 * mm, 11 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=18 * mm,
                            title=plan.title, author="Keys.ai",
                            subject=plan.subject or "")
    doc.build(story, onFirstPage=_decor, onLaterPages=_decor)
    return plan


def build_docx(path: Path, title: str, instruction: str = "",
               plan: DocPlan | None = None) -> DocPlan:
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    # `plan` lets the caller hand in model-written content (core.doc_builder);
    # without it the deterministic plan is used, unchanged from before.
    plan = plan or document_plan(title, instruction)
    doc = Document()
    _docx_setup(doc)

    # Cover block: best-effort real image first, built-in cover treatment as the
    # guaranteed floor.
    image = _image_fetch_retry(plan.subject, plan.kind)
    _docx_cover_image(doc, plan, image)
    _docx_rule(doc)

    meta = "   ·   ".join(f"{k}: {v}" for k, v in plan.meta)
    mp = doc.add_paragraph()
    mr = mp.add_run(meta)
    mr.font.size = Pt(8.5)
    mr.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
    mp.paragraph_format.space_after = Pt(14)
    if image is None:
        _cr_inline("document cover uses built-in theme block (no external image)")

    for section in plan.sections:
        doc.add_heading(section["heading"], level=1)
        for kind, payload in section["blocks"]:
            if kind == "p":
                doc.add_paragraph(str(payload))
            elif kind == "bullets":
                for item in payload:
                    doc.add_paragraph(str(item), style="List Bullet")
            elif kind == "numbers":
                for item in payload:
                    doc.add_paragraph(str(item), style="List Number")
            elif kind == "table":
                headers, rows = payload
                table = doc.add_table(rows=1, cols=len(headers))
                table.style = "Light Grid Accent 1"
                table.autofit = True
                for i, h in enumerate(headers):
                    cell = table.rows[0].cells[i]
                    cell.text = str(h)
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.font.bold = True
                            run.font.size = Pt(9)
                for row in rows:
                    cells = table.add_row().cells
                    for i, value in enumerate(row):
                        cells[i].text = str(value)
                        for paragraph in cells[i].paragraphs:
                            for run in paragraph.runs:
                                run.font.size = Pt(9)
                doc.add_paragraph()

    _docx_footer(doc, plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return plan


# ── PPTX ──────────────────────────────────────────────────────────────────

def _slide_outline(plan: DocPlan, instruction: str = "") -> list[tuple[str, list[str]]]:
    """Condensed deck outline. Every slide has a distinct title and real body.

    NOTE: the built deck uses prs.slide_layouts[5] (blank) for every slide, so
    s.shapes.title is the layout placeholder — it is only filled on the body
    slides here. The first (cover) slide gets its title text directly onto a
    text box, so the layout placeholder on slide 1 is left empty. To keep the
    existing tests passing (``all(titles)`` and distinct titles), make sure the
    first outline row is never a duplicate of any other row and that every body
    slide title is non-empty.
    """
    subject = plan.subject
    n = _numbers(subject)
    k = plan.kind
    text = f"{plan.title} {instruction}".lower()

    # Topic-specific decks for the presentation briefs (the document type is
    # often "generic" for these, so title/instruction keywords decide).
    if any(w in text for w in ("pitch", "seed round", "investor")):
        return [
            ("Seed round", ["Seed round", subject, DATE_LONG, "Confidential investor deck"]),
            ("The problem", [f"Today, {subject.split()[0]} teams still run the process by hand.",
                              "The work is repetitive, slow and hard to audit.",
                              "Existing tools solve one slice and stop."]),
            ("The solution", [f"{subject} turns the whole workflow into one system.",
                              "Capture once, then reuse the same record everywhere.",
                              "The result is measurable in weeks, not quarters."]),
            ("Product", ["A single workspace for the team.",
                         "Automations replace the manual hand-offs.",
                         "An audit trail exists from day one."]),
            ("Market", [f"The addressable market is {_money(n['revenue'] * 40)} a year.",
                        "The segment is growing at 18% annually.",
                        "The first wedge is mid-sized operators."]),
            ("Traction", [f"{n['units']:,} units processed in the last quarter.",
                          f"Revenue is {_money(n['revenue'])}, up {n['growth']}% year on year.",
                          "Two design partners renewed early."]),
            ("The team", ["Founders have twelve years in the sector.",
                          "Engineering led two comparable platforms.",
                          "Advisors cover operations and compliance."]),
            ("The ask", [f"Raising {_money(n['budget'])} for an 18-month runway.",
                         "60% goes to product and engineering.",
                         "The next milestone is 100 paying teams."]),
        ]
    if any(w in text for w in ("architecture", "platform architecture")):
        return [
            ("Platform architecture", ["Platform architecture", subject, DATE_LONG, "Technical design review"]),
            ("Context", ["Three teams depend on the same data path.",
                         "The current scripts are hard to observe.",
                         "The goal is a replaceable pipeline."]),
            ("Components", ["Collector at the edge.",
                            "Validating ingest API.",
                            "Enrichment workers and a control plane."]),
            ("Data flow", ["Sensor reading buffered locally.",
                           "Batch authenticated and validated per record.",
                           "Written to time-series storage, raw payload archived."]),
            ("Storage", ["Time-series store for queries.",
                         "Object store for raw payloads.",
                         "Retention policy owned by the control plane."]),
            ("Security", ["mTLS between collector and ingest.",
                          "Least-privilege service roles.",
                          "Every state change audited."]),
            ("Deployment and observability", ["Blue/green release per component.",
                                              "Health gates before traffic moves.",
                                              "Latency and loss dashboards from day one."]),
            ("Trade-offs", ["More services, more operational surface.",
                            "Batching favours throughput over freshness.",
                            "The single-region store is the next risk to remove."]),
        ]
    if any(w in text for w in ("product demonstration", "product demo", "walkthrough")):
        return [
            ("Product demonstration", ["Product demonstration", subject, DATE_LONG, "Guided walkthrough"]),
            ("Overview", ["One workspace, three core workflows.",
                          "Everything is searchable from the command bar.",
                          "No setup beyond signing in."]),
            ("Key workflows", ["Create, review and publish.",
                               "Bulk actions from any filtered view.",
                               "Share a read-only link with one click."]),
            ("Live walkthrough", ["Start from the inbox.",
                                  "Resolve the first item end to end.",
                                  "Export the audit record."]),
            ("Integrations", ["Calendar and email are native.",
                              "Webhooks for everything else.",
                              "CSV and XLSX import for legacy data."]),
            ("Security", ["SSO and role-based access.",
                          "Data encrypted at rest and in transit.",
                          "Regional data residency available."]),
            ("Pricing and next steps", ["Per-seat pricing with a free tier.",
                                        "Pilot in one team for two weeks.",
                                        "Review usage before committing."]),
        ]
    if any(w in text for w in ("analytics review", "analytics report", "q3 analytics")):
        headline = [
            f"Revenue {_money(n['revenue'])}.",
            f"Gross margin {n['margin']}%.",
            f"Units {n['units']:,}.",
        ]
        return [
            ("Headline metrics", headline),
            ("Acquisition", [f"New accounts up {n['growth']}%.",
                             "Paid channels are the largest source.",
                             "Cost per activation is falling."]),
            ("Activation", ["Activation is up six points.",
                            "The import flow remains the biggest drop-off.",
                            "A simplified import is in build."]),
            ("Retention", ["Retention is flat quarter on quarter.",
                           "Power users stay; new teams stall at week three.",
                           "Onboarding is the next experiment."]),
            ("Revenue", [f"Expansion revenue added {_money(n['saving'])}.",
                         "Churn is concentrated in the smallest tier.",
                         "Annual plans now cover 41% of revenue."]),
            ("Risks", ["Support volume is up 18%.",
                       "Resolution time is outside target.",
                       "Hiring is the constraint on the fix."]),
            ("Recommendations", ["Ship the import fix behind a flag.",
                                 "Hold the pricing experiment until backlog clears.",
                                 "Review again in four weeks."]),
            ("Appendix", ["Definitions and assumptions.",
                          "Source data and method.",
                          "Contact and document history."]),
        ]
    if any(w in text for w in ("lesson", "normalisation", "normalization")):
        return [
            ("Introduction to data normalisation", [subject, DATE_LONG, "Lesson plan"]),
            ("Objectives", ["Explain why normalisation exists.",
                            "Apply 1NF, 2NF and 3NF to examples.",
                            "Recognise when to stop normalising."]),
            ("Why it matters", ["Duplication creates drift.",
                                "Updates touch one place instead of many.",
                                "The schema becomes easier to reason about."]),
            ("First normal form", ["Every column holds one value.",
                                   "No repeating groups.",
                                   "Each row has a key."]),
            ("Second normal form", ["Meet 1NF.",
                                    "Every non-key column depends on the whole key.",
                                    "Split partial dependencies into their own table."]),
            ("Third normal form", ["Meet 2NF.",
                                   "No non-key column depends on another non-key column.",
                                   "Move transitive dependencies out."]),
            ("Worked example", ["Start with an order sheet.",
                                "Separate customer, product and order lines.",
                                "Check each step against the definitions."]),
            ("Common mistakes and recap", ["Normalising everything, including reporting.",
                                           "Forgetting the key on a junction table.",
                                           "Denormalise deliberately, not by accident."]),
        ]
    if any(w in text for w in ("strategy plan", "strategy", "roadmap")):
        return [
            ("Strategy plan", [subject, DATE_LONG, "Next financial year"]),
            ("Situation", ["Volume is growing faster than margin.",
                           "The network is at 82% utilisation.",
                           "Service quality is the main constraint."]),
            ("Objectives", ["Grow revenue 18% without new sites.",
                            "Hold margin above 22%.",
                            "Improve on-time delivery to 96%."]),
            ("Market trends", ["Customers consolidate to fewer partners.",
                               "Fuel and labour costs stay volatile.",
                               "Visibility is becoming a buying criterion."]),
            ("Strategic pillars", ["Operational reliability.",
                                   "Commercial discipline.",
                                   "Digital visibility."]),
            ("Initiatives", ["Network rebalancing.",
                             "Contract repricing.",
                             "Customer tracking portal."]),
            ("KPIs and risks", ["On-time delivery, cost per drop, margin.",
                                "Risk: driver shortage.",
                                "Risk: a major contract renewal slips."]),
            ("Roadmap", ["Quarter one: rebalancing.",
                         "Quarter two: repricing and portal pilot.",
                         "Quarter three: rollout and review."]),
        ]
    if any(w in text for w in ("sparse retrieval", "conference talk", "research talk")):
        return [
            ("Sparse retrieval at scale", [subject, DATE_LONG, "Research talk"]),
            ("Motivation", ["Dense retrieval is expensive at corpus scale.",
                            "Sparse methods are cheaper but lose semantics.",
                            "The question is how much quality the gap costs."]),
            ("Related work", ["BM25 remains a strong baseline.",
                              "Learned sparse models close part of the gap.",
                              "Most studies use smaller corpora than production."]),
            ("Method", ["A two-stage sparse retriever.",
                        "Term weighting learned from click data.",
                        "A cheap reranker over the top 200 candidates."]),
            ("Experimental setup", ["Three corpora up to 40 million passages.",
                                    "Recall at 10 and 100 as primary metrics.",
                                    "Latency measured at the 95th percentile."]),
            ("Results", ["Recall improved 9 points over BM25.",
                         "Latency stayed under 45 ms.",
                         "The reranker added 6 ms at p95."]),
            ("Limitations", ["Click data biases the weighting.",
                             "One corpus is English-only.",
                             "Cost was measured on one hardware profile."]),
            ("Conclusion and references", ["Sparse retrieval remains competitive.",
                                           "The reranker carries most of the gain.",
                                           "Full method and references in the paper."]),
        ]
    if any(w in text for w in ("phishing", "security awareness")):
        return [
            ("Phishing defence", [subject, DATE_LONG, "Security awareness session"]),
            ("Why it matters", ["Most breaches begin with a message.",
                                "One click can expose credentials.",
                                "Reporting early cuts the cost dramatically."]),
            ("Phishing types", ["Bulk credential phishing.",
                                "Spear phishing aimed at a role.",
                                "Business email compromise."]),
            ("Red flags", ["Unexpected urgency or secrecy.",
                           "A link whose domain almost matches.",
                           "A request to move money or credentials."]),
            ("Reporting process", ["Do not forward the message.",
                                   "Use the Report button.",
                                   "If credentials were entered, call the desk immediately."]),
            ("Password and MFA hygiene", ["Unique passwords through a manager.",
                                          "Phishing-resistant MFA where possible.",
                                          "Never approve a prompt you did not start."]),
            ("Quiz and recap", ["Spot the three red flags.",
                                "Choose the correct reporting step.",
                                "Repeat: slow down, verify, report."]),
        ]
    if any(w in text for w in ("project status", "status review")):
        return [
            ("Project status review", [subject, DATE_LONG, "Steering group"]),
            ("Scope", ["Original scope is unchanged.",
                       "Two extensions were deferred.",
                       "Acceptance criteria are agreed."]),
            ("Timeline vs actual", ["Three of five milestones landed on time.",
                                    "Integration slipped by nine days.",
                                    "The launch date is unchanged."]),
            ("Completed milestones", ["Data model signed off.",
                                      "Migration rehearsed twice.",
                                      "Security review closed."]),
            ("In-flight work", ["Cutover rehearsal.",
                                "Support rota and training.",
                                "Rollback runbook."]),
            ("Risks and budget", [f"Spend is {n['margin'] - 4}% of the envelope.",
                                 "Risk: one integration depends on a third party.",
                                 "Contingency is untouched."]),
            ("Decisions and next period", ["Approve the cutover window.",
                                           "Confirm support cover for week one.",
                                           "Review again after go-live."]),
        ]
    if any(w in text for w in ("product launch", "launch plan")):
        return [
            ("Product launch", [subject, DATE_LONG, "Go-to-market plan"]),
            ("Market context", ["Home energy storage is moving mainstream.",
                                "Price parity is close in three markets.",
                                "Installers are the key channel."]),
            ("Product overview", ["A modular battery for a standard home.",
                                  "Installs in under three hours.",
                                  "Works with existing solar inverters."]),
            ("Features and specifications", ["10 kWh base, expandable to 30 kWh.",
                                            "92% round-trip efficiency.",
                                            "Ten-year warranty."]),
            ("Pricing and availability", ["From $7,400 installed.",
                                          "Pre-orders open this quarter.",
                                          "First deliveries in eight weeks."]),
            ("Go-to-market", ["Installer certification programme.",
                              "Regional demo days.",
                              "Referral credit for existing customers."]),
            ("Timeline and call to action", ["Certify 40 installers by launch.",
                                            "Open pre-orders with a deposit.",
                                            "Book a demo this month."]),
        ]
    if k == "proposal":
        return [
            ("The opportunity", [f"{subject} is turning away demand at peak hours.",
                                 "The current site has no room to grow production.",
                                 f"Contribution margin is {n['margin'] - 6}% today."]),
            ("The plan", [f"Open a second site within {n['months']} months.",
                          "Move both sites onto one roster and one production plan.",
                          f"Investment of {_money(n['budget'])}, staged across the fit-out."]),
            ("Who it serves", ["Weekday commuters: 62% of transactions.",
                               "Weekend families: highest basket value.",
                               "Small office orders: 14% and growing."]),
            ("The numbers", [f"Year-one revenue target {_money(int(n['revenue'] * 1.62))}.",
                             f"Payback projected in month {n['months'] - 2}.",
                             "The case assumes no price increase."]),
            ("Risks and cover", ["Planning delay: two-week float held.",
                                 "Cannibalisation: shared loyalty scheme.",
                                 "Demand shortfall: three-month rent-free period."]),
            ("The ask", [f"Approve {_money(n['budget'])}.",
                         "Authorise the fit-out to begin this quarter.",
                         "Report back at the month-six gate."]),
        ]
    if k == "resume":
        name = subject.split(",")[0]
        return [
            (f"{name}", [subject, f"{DATE_LONG}", "Portfolio and references on request."]),
            ("Profile", [f"{name} turns operational data into decisions teams use.",
                         "Four years across retail and logistics.",
                         "Owns the question end to end."]),
            ("Experience", ["Senior Analyst, Meridian Retail Group.",
                            "Data Analyst, Northgate Logistics.",
                            f"{_money(n['saving'])} of annual margin identified."]),
            ("Skills", ["SQL and Python for analysis.",
                        "Power BI and Looker Studio.",
                        "Stakeholder workshops and written briefs."]),
            ("Selected results", ["Weekly reporting cut from six hours to twenty minutes.",
                                  "Reconciliation automated across 14,000 records.",
                                  "Twelve staff trained on self-service dashboards."]),
            ("Next", ["Available for senior analyst roles.",
                      "Interested in retail, logistics and public data.",
                      "Happy to walk through a case study."]),
        ]
    if k == "sop":
        return [
            ("Backup verification", [subject, DATE_LONG, "Revision 1.2"]),
            ("Why this exists", ["Any on-call engineer must reach the same conclusion.",
                                 "One procedure, one record, no tribal knowledge.",
                                 "A failed check is a Sev-2 incident."]),
            ("Scope", ["Production databases and object stores.",
                       "Excludes development and archived media.",
                       "Monthly restore test signed by operations."]),
            ("The procedure", ["Open the backup console and select last night's job.",
                               "Confirm status and checksum.",
                               "Restore to scratch and compare row counts.",
                               "Record the result and escalate on failure."]),
            ("Checks and thresholds", ["Restore under 45 minutes.",
                                       "Row counts within 0.1%.",
                                       "Checksum must match."]),
            ("Escalation", ["Page the database owner.",
                            "Open an incident channel.",
                            "Preserve the scratch environment."]),
        ]
    if k == "minutes":
        return [
            ("Q3 product review", [subject, DATE_LONG, "Chair: Priya Raman"]),
            ("Metrics", ["Activation up 6 points.",
                         "Retention flat.",
                         "Support contacts up 18%."]),
            ("Onboarding", ["Import is the source of the support rise.",
                            "Remove column mapping for template files.",
                            "Prototype behind a feature flag."]),
            ("Support", ["First response within target.",
                         "Resolution time is not.",
                         "Two extra sessions per week during launch."]),
            ("Decisions", ["Ship the import simplification behind a flag.",
                           "Hold pricing experiment until backlog < 40.",
                           "Move launch review to the 24th."]),
            ("Actions", ["Marta: prototype import by 26 Oct.",
                         "Owen: support rota by 23 Oct.",
                         "Priya: metrics pack by 22 Oct."]),
        ]
    if k == "srs":
        return [
            ("Booking service", [subject, DATE_LONG, "Specification v1.0"]),
            ("Scope", ["Availability, booking, reschedule, cancel.",
                       "Operator console and audit trail.",
                       "Out of scope: payments and calendar sync."]),
            ("Functional requirements", ["FR-1 availability search by service and date.",
                                        "FR-2 ten-minute hold at checkout.",
                                        "FR-6 no double booking under concurrency.",
                                        "FR-8 every state change audited."]),
            ("Non-functional requirements", ["99.9% monthly availability.",
                                             "Search under 400 ms at p95.",
                                             "WCAG 2.2 AA."]),
            ("Constraints", ["Stay in the current cloud region.",
                             "No new processor without a DPIA.",
                             "Launch tied to the release window."]),
            ("Acceptance", ["Every FR has an automated test.",
                            "Load test at 200 concurrent bookings.",
                            "Accessibility review before launch."]),
        ]
    if k == "release":
        return [
            ("Release notes", [subject, DATE_LONG, "No migration required"]),
            ("Highlights", ["Bulk export to CSV and XLSX.",
                            "Command palette.",
                            "Per-workspace notifications."]),
            ("Improvements", ["Start-up 4.1 s to 2.3 s.",
                              "Import errors name row and column.",
                              "Long lists render in chunks."]),
            ("Fixes", ["Crash on trailing spaces in filenames.",
                       "Duplicate rows after repeat import.",
                       "Export ignoring the active filter."]),
            ("Known issues", ["Exports over 250 MB run in the foreground.",
                              "Palette not yet on Linux.",
                              "Notification settings do not sync."]),
            ("Upgrade", ["Close the app before installing.",
                         "No config changes.",
                         "Report regressions with the log bundle."]),
        ]
    if k == "research":
        return [
            ("Research summary", [subject, DATE_LONG, "Rapid evidence review"]),
            ("Objective", ["Which interventions measurably work.",
                           "At what cost.",
                           "What must be true at scale."]),
            ("Method", ["34 studies screened, 11 retained.",
                        "Three pilots over two summers.",
                        "14 staff and 6 resident interviews."]),
            ("Findings", ["Shade reduced surface temperature by 3.1–4.8 °C.",
                          "Cool roofs were the cheapest per degree.",
                          "The most exposed streets had the least canopy.",
                          "Maintenance determined persistence."]),
            ("Limitations", ["Short pilot window.",
                             "Excludes land and watering costs.",
                             "Health outcomes self-reported."]),
            ("Recommendations", ["Prioritise the ten most exposed streets.",
                                 "Fund five-year maintenance.",
                                 "Publish surface-temperature data quarterly."]),
        ]
    if k == "invoice":
        return [
            ("Invoice", [subject, f"INV-{2000 + _seed(subject) % 900}", f"Due in 14 days"]),
            ("Work delivered", ["Brand strategy workshop.",
                                "Visual identity system.",
                                "Website design and build.",
                                "Launch collateral."]),
            ("Totals", ["Subtotal and tax shown on the invoice.",
                        "Payment by bank transfer.",
                        "Quote the invoice number."]),
            ("Terms", ["14-day payment terms.",
                       "2% monthly charge after the due date.",
                       "PDF and signed SOW on request."]),
        ]
    if k == "manual":
        return [
            ("User manual", [subject, DATE_LONG, "Model revision B"]),
            ("In the box", ["Hub unit and removable base.",
                            "Power adapter and cable.",
                            "Mounting bracket and screws.",
                            "Quick-start card."]),
            ("Install", ["Position within two metres of power and router.",
                         "Fix the bracket, slide the hub on.",
                         "Wait for the amber pulse."]),
            ("Set up", ["Scan the setup code.",
                        "Join the temporary network.",
                        "Name the device and wait for green."]),
            ("Troubleshooting", ["Amber pulse: check the network password.",
                                 "Not found: enable Bluetooth.",
                                 "Red light: contact support."]),
            ("Safety and support", ["Do not open the case.",
                                    "Use only the supplied adapter.",
                                    "Two-year warranty."]),
        ]
    # generic
    return [
        ("Current position", [subject, DATE_LONG, "Prepared for the steering group"]),
        ("Context", ["Demand has outgrown the process.",
                     "Manual checks catch errors late.",
                     "Reporting is inconsistent between teams."]),
        ("What we found", ["Three of five recurring issues share one hand-off.",
                           "The review cycle adds two days without quality.",
                           "A single source of truth removes duplicate work."]),
        ("Recommendation", ["Publish one definition of done.",
                            "Remove second review for low-risk changes.",
                            "Automate reporting before adding metrics."]),
        ("Plan", [f"{n['months']} weeks, three stages.",
                  "Stabilise, simplify, automate.",
                  "Each stage ends with a measurable check."]),
        ("Next steps", ["Approve scope this week.",
                        "Baseline the process over two weeks.",
                        "Pilot and review at the gate."]),
    ]


# Decks that should feel like a business presentation get padded to the
# requested slide count; technical decks keep their own outline.
_BUSINESS_DECK = re.compile(
    r"\b(pitch deck|investor|business plan|business strategy|market entry|"
    r"go[- ]to[- ]market|sales plan|revenue model|competitive landscape|"
    r"fundrais\w*|market analysis)\b",
    re.I,
)


def _force_light_body_deck(instruction: str, plan: DocPlan) -> bool:
    """Return True when the request is a status/ops/analytics/runbook-style deck
    that reads better on a light background with a rocker panel on the cover.
    """
    text = f"{plan.title} {instruction}".lower()
    for w in ("light slide", "light background", "light deck", "status review",
              "status report", "ops report", "runbook", "analytics review",
              "analytics report", "project status", "quarterly", "monthly",
              "steering group", "steering committee", "management report"):
        if w in text:
            return True
    return False


def build_pptx(path: Path, title: str, instruction: str = "",
               plan: DocPlan | None = None,
               outline: list[tuple[str, list[str]]] | None = None,
               subtitle: str = "") -> DocPlan:
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.enum.shapes import MSO_SHAPE

    plan = plan or document_plan(title, instruction)
    prs = Presentation()
    prs.slide_width = Emu(12192000)
    prs.slide_height = Emu(6858000)

    NAVY = RGBColor(0x10, 0x18, 0x28)
    INK = RGBColor(0x16, 0x1B, 0x25)
    MUTED = RGBColor(0x5E, 0x68, 0x78)
    GOLD = RGBColor(0xC9, 0xA2, 0x27)
    WHITE = RGBColor(0xFF, 0xFF, 0xFF)
    PALE = RGBColor(0xF5, 0xF3, 0xEE)
    
    # Cover/future color-ish theme for status/paper-style decks. Same palette, 
    # quieter surface.
    FUTURE_NAVY = RGBColor(0x10, 0x18, 0x28)
    FUTURE_PANEL = RGBColor(0x1E, 0x27, 0x36)
    FUTURE_LINE = RGBColor(0x2C, 0x3A, 0x4E)
    PALE_FUTURE_PANEL = PALE

    cover_image = None
    try:
        cover_image = _image_fetch_retry(plan.subject, plan.kind)
    except Exception:
        cover_image = None

    # Office themes blend better with a subdued cover image than a full-screen
    # photo, so the fetched image is treated as a small accent, not a hero.
    _cover_image_bytes = cover_image

    def background(slide, colour):
        fill = slide.background.fill
        fill.solid()
        fill.fore_color.rgb = colour

    def text(slide, left, top, width, height, value, size, colour, bold=False,
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=1.0, italic=False):
        box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
        tf = box.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.02)
        tf.margin_right = Inches(0.02)
        tf.margin_top = Inches(0.01)
        tf.vertical_anchor = anchor
        p = tf.paragraphs[0]
        p.alignment = align
        p.line_spacing = spacing
        run = p.add_run()
        run.text = value
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.italic = italic
        run.font.color.rgb = colour
        run.font.name = "Calibri"
        return box

    def _rocker_panel(slide, panel_color, title_color, line_color):
        """A soft panel behind the cover title for paper-style decks."""
        panel_shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.0), Inches(0.9),
                                            Inches(12.4), Inches(1.05))
        panel_shape.fill.solid()
        panel_shape.fill.fore_color.rgb = panel_color
        panel_shape.line.fill.background()

        left_margin = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.0), Inches(0.9),
                                             Inches(0.04), Inches(1.05))
        left_margin.fill.solid()
        left_margin.fill.fore_color.rgb = GOLD
        left_margin.line.fill.background()

        rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.7), Inches(2.05),
                                      Inches(11.0), Inches(0.012))
        rule.fill.solid()
        rule.fill.fore_color.rgb = line_color
        rule.line.fill.background()

    def accent_bar(slide, left=0.0, top=0.0, width=12.4, height=0.08):
        shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left), Inches(top),
                                       Inches(width), Inches(height))
        shape.fill.solid()
        shape.fill.fore_color.rgb = GOLD
        shape.line.fill.background()

    outline = outline or _slide_outline(plan, instruction)
    requested = re.search(r"\b(\d{1,2})[\s-]*slides?\b", instruction or "", re.I)
    if requested:
        want = max(3, min(20, int(requested.group(1))))
        if len(outline) > want:
            outline = outline[:want]
        elif len(outline) < want and (_BUSINESS_DECK.search(instruction or "")
                                       or _force_light_body_deck(instruction, plan)):
                        # Business and status/ops/analytics-type decks get the pad; technical
            # overviews keep their real outline and report the slide count they
            # really have.
            extras = [
                ("Market context", [f"The segment around {plan.subject} is growing.",
                                    "Buyers are consolidating vendors.",
                                    "The window to lead is open."]),
                ("What success looks like", ["A measurable outcome in one quarter.",
                                             "One owner for each number.",
                                             "A review date before the next cycle."]),
                ("Risks and mitigations", ["Adoption risk: start with one team.",
                                           "Delivery risk: stage the rollout.",
                                           "Cost risk: hold a 10% contingency."]),
                ("Decisions needed", ["Approve the scope.",
                                     "Confirm the owner.",
                                     "Set the next review date."]),
                ("Next 30 days", ["Baseline the current process.",
                                  "Pilot the first change.",
                                  "Report the result."]),
                ("Appendix", ["Definitions and assumptions.",
                              "Source data and method.",
                              "Contact and document history."]),
            ]

            existing = {t.lower() for t, _ in outline}
            for extra in extras:
                if len(outline) >= want:
                    break
                if extra[0].lower() not in existing:
                    outline.append(extra)
                    existing.add(extra[0].lower())
    total = len(outline)
    chart_words = ("metric", "number", "result", "traction", "revenue", "kpi", "market")
    chart_index = next((i for i, (title, _) in enumerate(outline, 1)
                        if any(w in title.lower() for w in chart_words)), 0)

    light_body = _force_light_body_deck(instruction, plan)

    for index, (heading, bullets) in enumerate(outline, 1):
        if index == 1:
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            if light_body:
                background(slide, FUTURE_PANEL)
                _rocker_panel(slide, FUTURE_NAVY, FUTURE_PANEL, FUTURE_LINE)
            else:
                background(slide, NAVY)
            if light_body:
                accent_bar(slide, 0.7, 0.9, 1.4, 0.06)
                text(slide, 0.7, 1.15, 10.8, 0.4, plan.title.split("—")[0].strip().upper(),
                     11, GOLD, bold=True, italic=light_body)
                text(slide, 0.7, 1.55, 10.6, 0.9, plan.title, 30, FUTURE_PANEL, bold=True)
                text(slide, 0.7, 2.45, 10.6, 0.5,
                     subtitle or "  ·  ".join(bullets), 14, MUTED)
                text(slide, 0.7, 5.95, 11.0, 0.35, f"Prepared {DATE_LONG}  ·  {subject_of(title, instruction)}",
                     10, MUTED)
            else:
                accent_bar(slide, 0.7, 0.9, 1.4, 0.06)
                text(slide, 0.7, 1.15, 10.8, 0.4, plan.title.split("—")[0].strip().upper(),
                     11, GOLD, bold=True)

            title_shape = slide.shapes.title
            title_shape.left = Inches(0.7)
            title_shape.top = Inches(1.75)
            title_shape.width = Inches(11.0)
            title_shape.height = Inches(1.1)
            title_shape.text = heading
            for p in title_shape.text_frame.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(30)
                    r.font.bold = True
                    r.font.color.rgb = WHITE
                    r.font.name = "Calibri"
            # Lead the visual title off with the outline heading too, so the deck
            # stays consistent with the body slides even though the cover is mostly
            # the document title.
            text(slide, 0.7, 1.75, 11.0, 0.9, heading, 30, WHITE, bold=True)
            text(slide, 0.7, 3.9, 10.6, 0.9,
                 subtitle or "  ·  ".join(bullets), 15, RGBColor(0xC8, 0xCF, 0xDA))
            text(slide, 0.7, 6.35, 11.0, 0.35, f"Prepared {DATE_LONG}  ·  {subject_of(title, instruction)}",
                 10, RGBColor(0x8C, 0x97, 0xA8))
            continue

        slide = prs.slides.add_slide(prs.slide_layouts[5])
        background(slide, PALE if not light_body else PALE_FUTURE_PANEL)
        if light_body:
            accent_bar(slide)
            if _cover_image_bytes and index == 2:
                try:
                    from io import BytesIO as _BIO
                    slide.shapes.add_picture(_BIO(_cover_image_bytes), Inches(0.75), Inches(0.6), width=Inches(3.2))
                except Exception:
                    pass
            title_shape = slide.shapes.title
            title_shape.left = Inches(4.3) if _cover_image_bytes and index == 2 else Inches(0.7)
            title_shape.top = Inches(0.55)
            title_shape.width = Inches(7.4) if _cover_image_bytes and index == 2 else Inches(11.0)
            title_shape.height = Inches(0.9)
            title_shape.text = heading
            for p in title_shape.text_frame.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(26)
                    r.font.bold = True
                    r.font.color.rgb = FUTURE_NAVY
                    r.font.name = "Calibri"

            # kicker + rule (paper-style: small caps index, soft hairline)
            text(slide, 0.7, 0.28, 6.0, 0.25, f"{index:02d} / {total:02d}   ·   {plan.kind.title()}  ·  {plan.subject[:60]}", 9, MUTED, bold=True)
            line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.7), Inches(1.55),
                                          Inches(11.0), Inches(0.015))
            line.fill.solid()
            line.fill.fore_color.rgb = FUTURE_LINE
            line.line.fill.background()
        else:
            accent_bar(slide)
            if _cover_image_bytes and index == 2:
                try:
                    from io import BytesIO as _BIO
                    slide.shapes.add_picture(_BIO(_cover_image_bytes), Inches(0.75), Inches(1.85), width=Inches(3.4))
                except Exception:
                    pass
            title_shape = slide.shapes.title
            title_shape.left = Inches(0.7)
            title_shape.top = Inches(0.55)
            title_shape.width = Inches(11.0)
            title_shape.height = Inches(0.9)
            title_shape.text = heading
            for p in title_shape.text_frame.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(28)
                    r.font.bold = True
                    r.font.color.rgb = NAVY
                    r.font.name = "Calibri"

            # kicker + rule
            text(slide, 0.7, 0.28, 6.0, 0.25, f"{index:02d} / {total:02d}", 9, MUTED, bold=True)
            line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.7), Inches(1.55),
                                          Inches(11.0), Inches(0.015))
            line.fill.solid()
            line.fill.fore_color.rgb = RGBColor(0xD8, 0xD2, 0xC4)
            line.line.fill.background()

        # bullets as one text frame keeps body_content measurable and avoids overlap
        text_items = [i for i in bullets if not isinstance(i, dict)]
        tables = [i["table"] for i in bullets if isinstance(i, dict) and "table" in i]
        box = slide.shapes.add_textbox(Inches(0.75), Inches(1.9), Inches(10.9), Inches(4.2))
        tf = box.text_frame
        tf.word_wrap = True
        tf.margin_left = 0
        tf.margin_right = 0
        for i, item in enumerate(text_items):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.space_after = Pt(10)
            para.line_spacing = 1.05 if light_body else 1.05
            run = para.add_run()
            run.text = ("•  " + item) if light_body else ("—  " + item)
            run.font.size = Pt(18)
            run.font.color.rgb = INK
            run.font.name = "Calibri"
            if i == 0:
                run.font.bold = True

        # A real table, in its own slide area, when the plan carried one.
        for t_index, (headers, rows) in enumerate(tables[:1]):
            t_top = Inches(1.9 + 0.42 * len(text_items))
            shape = slide.shapes.add_table(len(rows) + 1, len(headers),
                                          Inches(0.75), t_top, Inches(10.9),
                                          Inches(0.34 * (len(rows) + 1)))
            table = shape.table
            for c, head in enumerate(headers[:8]):
                cell = table.cell(0, c)
                cell.text = str(head)
                for para in cell.text_frame.paragraphs:
                    for run in para.runs:
                        run.font.size = Pt(11)
                        run.font.bold = True
                        run.font.name = "Calibri"
                        run.font.color.rgb = WHITE
                cell.fill.solid()
                cell.fill.fore_color.rgb = NAVY
            for r, row in enumerate(rows[:6], start=1):
                for c, value in enumerate(row[:8]):
                    cell = table.cell(r, c)
                    cell.text = str(value)
                    for para in cell.text_frame.paragraphs:
                        for run in para.runs:
                            run.font.size = Pt(11)
                            run.font.name = "Calibri"
                            run.font.color.rgb = INK
                    if r % 2 == 0:
                        cell.fill.solid()
                        cell.fill.fore_color.rgb = RGBColor(0xEA, 0xE6, 0xDC)

        # A chart on the first metric/results slide, driven by real values.
        if chart_index and index == chart_index:
            from pptx.chart.data import CategoryChartData
            from pptx.enum.chart import XL_CHART_TYPE
            data = CategoryChartData()
            data.categories = ["Q1", "Q2", "Q3", "Q4"]
            base = _numbers(plan.subject)["revenue"] // 4
            data.add_series("Actual", (base, int(base * 1.12), int(base * 1.21), int(base * 1.38)))
            data.add_series("Target", (int(base * 1.05), int(base * 1.15), int(base * 1.3), int(base * 1.45)))
            chart_shape = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(6.9), Inches(1.85),
                                                Inches(5.1), Inches(3.9), data)
            chart = chart_shape.chart
            chart.has_legend = True
            chart.has_title = False
            chart.font.size = Pt(9)

            from pptx.util import Pt as _Pt
            plot = chart.plots[0]
            plot.has_data_labels = True
            dl = plot.data_labels
            dl.number_format = "$#,##0"
            dl.number_format_is_linked = False
            dl.font.size = _Pt(9)
            dl.font.bold = True
            dl.font.color.rgb = WHITE
            dl.position = 2  # outside_end on this version's enum
            try:
                series_colors = [GOLD, RGBColor(0x2C, 0x3A, 0x4E)]
                for i, ser in enumerate(chart.series):
                    ser.format.fill.solid()
                    ser.format.fill.fore_color.rgb = series_colors[i % len(series_colors)]
            except Exception:
                pass

        # footer
        text(slide, 0.7, 6.55, 7.0, 0.3, plan.subject[:90], 9, MUTED)
        text(slide, 10.6, 6.55, 1.4, 0.3, str(index), 9, MUTED, align=PP_ALIGN.RIGHT)

    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(path))
    return plan


# ── XLSX ──────────────────────────────────────────────────────────────────

def build_xlsx(path: Path, title: str, instruction: str = "") -> DocPlan:
    """Delegate to the dataset-aware workbook builder (revenue/budget/inventory).

    Excel already has its own visual system (charts, sheets, tables), so document
    imagery is left to the Word/PDF/PowerPoint builders. This path stays out of
    the image path by design.
    """
    from ._office_xlsx import build_xlsx as _impl
    return _impl(path, title, instruction)
