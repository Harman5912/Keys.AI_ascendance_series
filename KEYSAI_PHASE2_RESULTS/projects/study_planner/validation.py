"""Input validation — every rule returns (ok, message, fields).

Rejected up front, with a specific message the UI can show next to the field:
  * missing / over-long titles
  * malformed or PAST deadlines (a study deadline must be today or later)
  * unknown priority / status values
  * non-numeric or out-of-range session minutes
  * unknown subject / user ids (existence is checked in models, not here)

Malformed dates are rejected as dates, not silently accepted as strings:
'2026-13-45' and 'next tuesday' must never reach the database.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any

PRIORITIES = ("low", "medium", "high")
STATUSES = ("todo", "in_progress", "done")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TITLE_MAX = 200
_NOTES_MAX = 2000


def _today() -> _dt.date:
    return _dt.date.today()


def parse_date(value: Any) -> _dt.date | None:
    """ISO date ('YYYY-MM-DD') or full ISO-8601 datetime → date, else None."""
    if isinstance(value, _dt.date) and not isinstance(value, _dt.datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if _ISO_DATE.match(raw):
        try:
            return _dt.date.fromisoformat(raw)
        except ValueError:
            return None
    # full ISO-8601 datetime with time / offset
    try:
        return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def valid_date_text(value: Any) -> str | None:
    """Canonical 'YYYY-MM-DD' text for a date the caller may store."""
    d = parse_date(value)
    return d.isoformat() if d else None


def validate_task(payload: dict, *, partial: bool = False,
                  allow_past: bool = False) -> tuple[bool, str, dict]:
    """Validate a create (or PATCH) payload. Returns (ok, message, clean)."""
    fields: dict[str, str] = {}
    clean: dict[str, Any] = {}

    if not partial or "title" in payload:
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            fields["title"] = "Title is required."
        elif len(title.strip()) > _TITLE_MAX:
            fields["title"] = f"Title must be {_TITLE_MAX} characters or fewer."
        else:
            clean["title"] = title.strip()

    if "notes" in payload:
        notes = payload.get("notes", "")
        if notes is None:
            notes = ""
        if not isinstance(notes, str):
            fields["notes"] = "Notes must be text."
        elif len(notes) > _NOTES_MAX:
            fields["notes"] = f"Notes must be {_NOTES_MAX} characters or fewer."
        else:
            clean["notes"] = notes

    if "priority" in payload:
        priority = payload.get("priority")
        if not isinstance(priority, str) or priority not in PRIORITIES:
            fields["priority"] = f"Priority must be one of: {', '.join(PRIORITIES)}."
        else:
            clean["priority"] = priority

    if "status" in payload:
        status = payload.get("status")
        if not isinstance(status, str) or status not in STATUSES:
            fields["status"] = f"Status must be one of: {', '.join(STATUSES)}."
        else:
            clean["status"] = status

    if "subject_id" in payload:
        sid = payload.get("subject_id")
        if isinstance(sid, bool) or not isinstance(sid, int) or sid <= 0:
            fields["subject_id"] = "subject_id must be a positive integer."
        else:
            clean["subject_id"] = sid

    if "due_date" in payload:
        raw = payload.get("due_date")
        if raw in (None, ""):
            clean["due_date"] = None            # clearing a deadline is legal
        else:
            iso = valid_date_text(raw)
            if iso is None:
                # covers '2026-13-45', 'next tuesday', '', 123, ...
                fields["due_date"] = ("Deadlines must be a real ISO date "
                                      "(YYYY-MM-DD), for example 2026-11-03.")
            elif not allow_past and _dt.date.fromisoformat(iso) < _today():
                fields["due_date"] = ("Deadlines cannot be in the past — that "
                                      "date has already been missed.")
            else:
                clean["due_date"] = iso

    if fields:
        return False, "Validation failed.", fields
    return True, "ok", clean


def validate_session(payload: dict) -> tuple[bool, str, dict]:
    """Validate a study-session payload."""
    fields: dict[str, str] = {}
    clean: dict[str, Any] = {}

    minutes = payload.get("minutes")
    if isinstance(minutes, bool) or not isinstance(minutes, int):
        fields["minutes"] = "minutes must be a whole number."
    elif not (1 <= minutes <= 600):
        fields["minutes"] = "minutes must be between 1 and 600."
    else:
        clean["minutes"] = minutes

    for key in ("subject_id", "task_id"):
        if key in payload and payload.get(key) is not None:
            value = payload.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                fields[key] = f"{key} must be a positive integer."
            else:
                clean[key] = value

    studied = payload.get("studied_on")
    if studied in (None, ""):
        clean["studied_on"] = _today().isoformat()
    else:
        iso = valid_date_text(studied)
        if iso is None:
            fields["studied_on"] = "studied_on must be an ISO date (YYYY-MM-DD)."
        else:
            clean["studied_on"] = iso

    notes = payload.get("notes", "")
    if notes in (None, ""):
        clean["notes"] = ""
    elif not isinstance(notes, str):
        fields["notes"] = "Notes must be text."
    elif len(notes) > _NOTES_MAX:
        fields["notes"] = f"Notes must be {_NOTES_MAX} characters or fewer."
    else:
        clean["notes"] = notes

    if fields:
        return False, "Validation failed.", fields
    return True, "ok", clean


def validate_subject(payload: dict, *, partial: bool = False) -> tuple[bool, str, dict]:
    """Validate a subject payload (name required, optional colour)."""
    fields: dict[str, str] = {}
    clean: dict[str, Any] = {}

    if not partial or "name" in payload:
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            fields["name"] = "Subject name is required."
        elif len(name.strip()) > 80:
            fields["name"] = "Subject name must be 80 characters or fewer."
        else:
            clean["name"] = name.strip()

    if "color" in payload:
        color = payload.get("color")
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color or ""):
            fields["color"] = "Colour must be a hex value like #d4a017."
        else:
            clean["color"] = color

    if fields:
        return False, "Validation failed.", fields
    return True, "ok", clean


def validate_user(payload: dict) -> tuple[bool, str, dict]:
    """Validate a test-profile payload (synthetic users only)."""
    fields: dict[str, str] = {}
    clean: dict[str, Any] = {}

    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        fields["name"] = "Name is required."
    elif len(name.strip()) > 80:
        fields["name"] = "Name must be 80 characters or fewer."
    else:
        clean["name"] = name.strip()

    email = payload.get("email")
    if email in (None, ""):
        clean["email"] = None
    elif not isinstance(email, str) or "@" not in email or len(email) > 254:
        fields["email"] = "email must look like an address (name@example.com)."
    else:
        clean["email"] = email

    if fields:
        return False, "Validation failed.", fields
    return True, "ok", clean
