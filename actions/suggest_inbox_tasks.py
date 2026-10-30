"""
suggest_inbox_tasks — tool wrapper around core/firebase_client inbox reading.

Reads the user's recent Gmail, uses the configured LLM to turn the contents
into a short list of concrete tasks the assistant can actually do from email
(reply, follow up, forward, summarise, extract an action item, nudge a
thread, archive a cleared thread). The suggestions are read-only — they are
shown to the user and never acted on without an explicit go-ahead.
"""

from __future__ import annotations

from typing import Any

from core import firebase_client as fb
from core.llm_client import complete as _chat


# ---------------------------------------------------------------------------
# LLM prompt + pruning
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are a helpful email-task assistant. You are given a small slice of "
    "the user's Gmail inbox (message id, from, subject, date, body). Produce "
    "a SHORT, concrete, actionable list of tasks the Keys.ai assistant could "
    "do for the user based ONLY on these emails."
)

_USER_TEMPLATE = (
    "Here are the most recent emails in the inbox.\n\n"
    "{emails}\n\n"
    "For each email, decide whether there is a real, concrete action worth "
    "suggesting. Consider things like: reply to a question, follow up on a "
    "stale thread, forward to the right person, summarise a long thread, "
    "extract a clear action item or deadline, nudge someone waiting on a "
    "reply, or mark a thread as done/something the user can archive.\n\n"
    "Return a JSON object with one key: \"tasks\", a list of at most 6 tasks. "
    "Each task is an object with keys: \"email_id\" (the Gmail id or \"#N\"), "
    "\"subject\", \"why\" (one sentence: why this task is worth doing), "
    "\"suggested_action\" (one of: reply, follow_up, forward, summarize, "
    "action_item, nudge, archive, none), and \"suggested_next\" (the concrete "
    "next step, one short sentence; empty when there is no action). Do NOT "
    "invent tasks for emails that are newsletters, spam, system notifications, "
    "or otherwise not actionable. Use \"none\" when an email is not worth a "
    "task. Do NOT mention money, account numbers, passwords, or other secret "
    "details in the output — keep the summaries generic."
)


def _format_email(idx: int, e: dict[str, Any]) -> str:
    body = (e.get("body") or "").strip()
    if not body:
        body = "(no body — only headers available)"
    return (
        f"--- Email #{idx} (id={e.get('id', '')}) ---\n"
        f"From:    {e.get('from', '')}\n"
        f"Subject: {e.get('subject', '(no subject)')}\n"
        f"Date:    {e.get('date', '')}\n"
        f"Body:\n{body}\n"
    )


def _build_emails_text(emails: list[dict[str, Any]]) -> str:
    if not emails:
        return "(no emails)"
    return "\n".join(_format_email(i, e) for i, e in enumerate(emails, 1))


def _parse_tasks(raw: str) -> list[dict[str, Any]]:
    """Best-effort JSON parse of the model's task list."""
    import json as _json
    import re as _re

    body = raw.strip()
    # Try a direct parse first.
    try:
        parsed = _json.loads(body)
        if isinstance(parsed, dict) and isinstance(parsed.get("tasks"), list):
            return parsed["tasks"]
    except ValueError:
        pass

    # Try to fish out a JSON object from the response.
    m = _re.search(r"\{[^\}]*\"tasks\"\s*:\s*\[[^\]]*\]", body, _re.S)
    if m:
        try:
            parsed = _json.loads(m.group(0))
            if isinstance(parsed, dict) and isinstance(parsed.get("tasks"), list):
                return parsed["tasks"]
        except ValueError:
            pass

    return []


_KINDS = {
    "reply", "follow_up", "forward", "summarize",
    "action_item", "nudge", "archive", "none",
}


def _prune_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        suggestions = str(t.get("suggested_action", "") or "").strip().lower()
        if suggestions not in _KINDS:
            suggestions = "none"
        subject = str(t.get("subject", "") or "").strip()
        why = str(t.get("why", "") or "").strip()
        nxt = str(t.get("suggested_next", "") or "").strip()
        eid = str(t.get("email_id", "") or "").strip()
        if not subject and not why and not nxt:
            continue
        out.append({
            "email_id": eid or "(unknown)",
            "subject": subject or "(no subject)",
            "why": why or "No reason recorded.",
            "suggested_action": suggestions,
            "suggested_next": nxt,
        })
    return out[:6]


# ---------------------------------------------------------------------------
# Public action
# ---------------------------------------------------------------------------

def suggest_inbox_tasks(
    parameters: dict[str, Any] | None,
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
) -> str:
    """
    Tool shape:
      parameters: {
        "max_emails": <int, default 12>,
        "query": <optional Gmail search query, e.g. "is:unread">,
      }
    """
    params = parameters or {}
    max_emails = params.get("max_emails", 12)
    try:
        max_emails = int(max_emails)
    except (TypeError, ValueError):
        max_emails = 12
    max_emails = max(1, min(max_emails, 20))

    query = (params.get("query") or "").strip() or ""

    if not fb.is_signed_in():
        return "Not signed in with Google. Say 'sign in with Google' first to read your inbox."

    try:
        emails = fb.list_emails(query, max_emails)
    except Exception as exc:  # noqa: BLE001
        hint = fb._gmail_api_hint(exc) if hasattr(fb, "_gmail_api_hint") else ""
        msg = f"Could not read your inbox right now: {str(exc)[:160]}"
        return (msg + " " + hint) if hint else msg

    if not emails:
        suffix = f" (query: {query})" if query else ""
        return "No emails found in your inbox." + suffix

    try:
        email_text = _build_emails_text(emails)
        user_prompt = _USER_TEMPLATE.format(emails=email_text)
        reply = _chat(
            "suggest_inbox_tasks",
            user_prompt,
            system=_SYSTEM,
            max_tokens=1024,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[SuggestInboxTasks] LLM parse failed: {exc}")
        return (
            "I could read your inbox but not turn it into suggestions just now. "
            f"{str(exc)[:120]}"
        )

    tasks = _prune_tasks(_parse_tasks(reply or ""))

    if not tasks:
        return (
            "I read your recent emails but nothing stood out as an actionable "
            "task I could help with. Want me to read a specific email in full "
            "instead — say 'read email #N' or 'read the email from <name>'."
        )

    lines: list[str] = [f"I found {len(emails)} recent emails and {len(tasks)} possible task(s):"]
    for i, t in enumerate(tasks, 1):
        lines.append(f"\n{i}. [{t['suggested_action']}] {t['subject']}")
        lines.append(f"   Why: {t['why']}")
        if t["suggested_next"]:
            lines.append(f"   Next: {t['suggested_next']}")
        lines.append(f"   Email: {t['email_id']}")
    lines.append(
        "\nThese are only suggestions. Say 'do task N' to act on one, or ask me "
        "to read any email in full first."
    )
    return "\n".join(lines)
