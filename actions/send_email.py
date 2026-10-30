"""
send_email — tool wrapper around core/firebase_client.send_email.

Sends an email from the user's Gmail. When several Google accounts are
signed in, `from_account` decides WHICH account sends it:

    - omitted        → the ACTIVE account
    - "work@gmail"   → matched by email/display-name fragment or number

The recipient can be a NAME — it is resolved to a real email address from
the user's contacts, which now includes contacts from EVERY signed-in
Google account (verified Firestore + People API).
"""

from core import firebase_client as fb


def send_email(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    to           = (params.get("to") or "").strip()
    subject      = (params.get("subject") or "").strip()
    body         = (params.get("body") or "").strip()
    from_account = (params.get("from_account") or "").strip() or None

    if not to:
        return "Please specify who the email goes to (a name or an email address)."
    if not subject:
        return "Please specify the email subject."

    # Tell the caller which account(s) can send, so it can pick/ask.
    available = fb.available_from_accounts()

    try:
        res = fb.send_email(to, subject, body, from_account)
    except Exception as e:
        print(f"[SendEmail] ❌ {e}")
        return f"Could not send email: {str(e)[:200]}"

    if not res.get("ok"):
        print(f"[SendEmail] ⛔ {res.get('error', '')}")
        return res.get("error", "Could not send email.")

    note = ""
    if not from_account and len(available) > 1:
        note = (f" ({len(available)} Google accounts available — say 'send "
                f"from <email>' to use a different one)")
    return (f"Email sent from {res['from']} to {res['to']} — "
            f"subject '{subject}'.{note}")
