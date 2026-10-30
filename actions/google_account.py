"""
google_account — tool wrapper around core/firebase_client.

Signs into the user's Google account (via Firebase) and manages a list of
VERIFIED contacts whose identity is confirmed through Google. send_message
consults these contacts to gate messaging.

actions: sign_in | sign_out | status | add_contact | list_contacts |
         verify_contact | confirm_contact | remove_contact | find_contact |
         list_emails | read_email
"""

from core import firebase_client as fb


def google_account(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    action = (params.get("action") or "status").strip().lower()

    try:
        if action in ("sign_in", "add_account"):
            # sign_in shows Google's account picker (prompt=select_account) so
            # the user can add ANOTHER account or re-select an existing one.
            return fb.sign_in()

        if action in ("sign_out", "remove_active_account"):
            return fb.sign_out()

        if action == "list_accounts":
            return fb.list_accounts()

        if action in ("switch_account", "use_account"):
            return fb.switch_account(
                params.get("account")
                or params.get("email")
                or params.get("index")
                or params.get("name")
            )

        if action == "remove_account":
            return fb.remove_account(
                params.get("account")
                or params.get("email")
                or params.get("index")
                or params.get("name")
            )

        if action == "status":
            return fb.status()

        if action == "add_contact":
            # Explicit truthy check — bool("false") would be True.
            _verified = str(params.get("verified", "")).lower() in (
                "1", "true", "yes", "y"
            )
            return fb.add_contact(
                name=params.get("name", ""),
                google_email=params.get("google_email", ""),
                phone=params.get("phone", ""),
                platform=params.get("platform", ""),
                verified=_verified,
            )

        if action == "list_contacts":
            return fb.list_contacts_display()

        if action in ("list_all_contacts", "all_contacts"):
            # Contacts aggregated across EVERY signed-in Google account
            # (verified Firestore + People API) — see send_email which also
            # searches these when resolving a recipient NAME.
            return fb.list_all_contacts_display()

        if action == "verify_contact":
            return fb.verify_contact_display(params.get("name", ""))

        if action == "confirm_contact":
            return fb.confirm_contact(params.get("name", ""))

        if action == "remove_contact":
            return fb.remove_contact(params.get("name", ""))

        if action == "find_contact":
            # Look up a spoken name/phone in the user's REAL mobile contacts
            # (Google People API + local vCards + verified contacts) and return
            # the person's phone/email so messaging/calling can target it.
            return fb.find_contact_display(params.get("name", ""))

        if action == "list_emails":
            # Read the user's Gmail inbox (requires Gmail API + gmail.readonly).
            _q  = params.get("query", "")
            _mr = params.get("max_results", 8)
            try:
                _mr = int(_mr)
            except Exception:
                _mr = 8
            return fb.list_emails_display(_q, _mr)

        if action == "read_email":
            # Open one message by Gmail id (or the "#N" short form from list_emails).
            _eid = params.get("email_id", "")
            if _eid.startswith("#"):
                _n = _eid[1:]
                try:
                    _n = int(_n)
                except Exception:
                    _n = 0
                _emails = fb.list_emails("", 20)
                if 1 <= _n <= len(_emails):
                    _eid = _emails[_n - 1]["id"]
                else:
                    return f"No email #{_n} — only {len(_emails)} recent messages available."
            return fb.read_email_display(_eid)

        return (
            f"Unknown google_account action: '{action}'. Valid: sign_in, sign_out, "
            "list_accounts, switch_account, remove_account, status, add_contact, "
            "list_contacts, verify_contact, confirm_contact, remove_contact, "
            "find_contact, list_emails, read_email."
        )
    except Exception as e:
        print(f"[GoogleAccount] ❌ {action}: {e}")
        return f"google_account '{action}' failed: {str(e)[:200]}"
