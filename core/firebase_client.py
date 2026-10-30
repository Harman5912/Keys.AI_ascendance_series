"""
Firebase + Google account integration for Keys.ai.

Pure REST (no Firebase SDK needed - only `requests`, already a dependency).

FLOW
  1. Google OAuth 2.0 "installed app" flow with a localhost loopback redirect:
     we open the system browser to Google, the user approves, and Google
     redirects to http://127.0.0.1:<port>/ with an authorization code.
  2. Exchange the code for Google tokens (id_token + refresh_token).
  3. Hand the Google id_token to Firebase Auth's `signInWithIdp` endpoint to
     mint a Firebase session (idToken + refreshToken + uid).
  4. Store the Firebase refresh token in config; ID tokens are auto-refreshed
     through the Secure Token endpoint whenever they expire.
  5. Verified contacts live in Firestore under users/{uid}/contacts/{name}.

CONFIG (config/api_keys.json) - see FIREBASE_SETUP.md for how to obtain them:
    google_oauth_client_id      - OAuth 2.0 Client ID (Desktop app type)
    google_oauth_client_secret  - matching client secret
    firebase_api_key            - Firebase Web API key
    firebase_project_id         - Firebase project ID    (After sign-in the module stores: firebase_refresh_token, firebase_id_token,
firebase_id_token_expires, firebase_uid, firebase_email, firebase_display_name,
google_access_token + google_refresh_token + google_access_expires)
Google's own tokens let Keys.ai read the user's REAL mobile contacts via the
People API so it can confirm the name you ask to message or call.
"""

import json
import os
import re
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

# -- Endpoints (confirmed current) --------------------------------------------
GOOGLE_AUTH_URL    = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL   = "https://oauth2.googleapis.com/token"
FIREBASE_AUTH      = "https://identitytoolkit.googleapis.com/v1"
FIREBASE_SECURE    = "https://securetoken.googleapis.com/v1/token"
FIRESTORE_BASE     = "https://firestore.googleapis.com/v1"
PEOPLE_API         = "https://people.googleapis.com/v1"
GMAIL_API          = "https://gmail.googleapis.com/gmail/v1"

# Read-only access to the user's real Google (phone-synced) contacts so Keys.ai
# can CONFIRM the name you ask to message/call. This is a sensitive scope — it
# works for the signed-in user (see FIREBASE_SETUP.md notes).
CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"

# Read-only access to the user's Gmail so Keys.ai can read/answer emails.
# Restricted scope — works in Testing status with the owner's Gmail as a test
# user (no verification needed for personal use); see FIREBASE_SETUP.md.
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

# Sending emails FROM the user's Gmail (send_email tool). Also restricted —
# approved together with gmail.readonly at sign-in for the same project.
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

# Console page where the Gmail API is enabled. The API itself is a separate
# switch from the OAuth scopes — a 403 accessNotConfigured means this page
# hasn't been opened/enabled for the project yet.
GMAIL_ENABLE_URL = (
    "https://console.developers.google.com/apis/api/gmail.googleapis.com/overview"
)

_SIGN_IN_TIMEOUT = 180.0   # seconds the user has to approve in the browser


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE        = _base_dir()
_CONFIG_PATH = _BASE / "config" / "api_keys.json"


# -- Config helpers -----------------------------------------------------------

# Reads and writes of the LIVE config go through core.config_store, so a token
# refresh cannot overwrite a provider setting saved at the same moment (and
# vice versa), and OAuth tokens are encrypted rather than stored in plaintext.
#
# A redirect of _CONFIG_PATH (tests, or a caller pointing this module at an
# isolated file) keeps using that file directly: it is a separate store and
# must not be mixed with the app's real configuration.
def _store():
    try:
        from core import config_store
        if Path(_CONFIG_PATH) == Path(config_store.CONFIG_PATH):
            return config_store
    except Exception:
        pass
    return None


def _raw_load() -> dict:
    try:
        data = json.loads(Path(_CONFIG_PATH).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _raw_write(cfg: dict) -> None:
    path = Path(_CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cfg or {}, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _load_cfg() -> dict:
    store = _store()
    if store is not None:
        try:
            return store.load()
        except Exception:
            return {}
    return _raw_load()


def _save_cfg(patch: dict) -> None:
    store = _store()
    if store is not None:
        store.update(patch or {})
        return
    cfg = _raw_load()
    cfg.update({k: v for k, v in (patch or {}).items() if v is not None})
    _raw_write(cfg)


def _clear_cfg(*keys: str) -> None:
    store = _store()
    if store is not None:
        store.update(remove=keys)
        return
    cfg = _raw_load()
    for key in keys:
        cfg.pop(key, None)
    _raw_write(cfg)


# -- MULTI-ACCOUNT STORAGE ---------------------------------------------------
# Multiple Google accounts can be signed in at once. Each account owns its own
# token set; exactly one is ACTIVE and drives contacts / calls / email. The
# OAuth client id/secret and Firebase project config stay top-level (they are
# shared by every account).
#
#   config/api_keys.json:
#     google_accounts: [ { firebase_email, firebase_display_name, firebase_uid,
#                          firebase_refresh_token, firebase_id_token,
#                          firebase_id_token_expires, google_access_token,
#                          google_access_expires, google_refresh_token }, ... ]
#     active_google_account: <email or 0-based index>
#
# Legacy single-account configs (flat firebase_uid/firebase_refresh_token/...
# keys) are migrated into google_accounts[] automatically on first access.

_ACCOUNT_KEYS = (
    "firebase_refresh_token", "firebase_id_token", "firebase_id_token_expires",
    "firebase_uid", "firebase_email", "firebase_display_name",
    "google_access_token", "google_access_expires", "google_refresh_token",
)


def _write_cfg(cfg: dict) -> None:
    store = _store()
    if store is not None:
        store.atomic_write(cfg)
        return
    _raw_write(cfg)


def _ensure_accounts(cfg: dict) -> dict:
    """Migrate a legacy flat-token config into google_accounts[]. In-place."""
    accts = cfg.get("google_accounts")
    if not isinstance(accts, list) or not accts:
        legacy = {k: cfg.get(k) for k in _ACCOUNT_KEYS if cfg.get(k)}
        if legacy:
            cfg["google_accounts"] = [legacy]
            cfg.setdefault("active_google_account",
                           legacy.get("firebase_email") or "0")
        else:
            cfg["google_accounts"] = []
    if not cfg.get("active_google_account") and cfg.get("google_accounts"):
        cfg["active_google_account"] = (
            cfg["google_accounts"][0].get("firebase_email") or "0")
    # drop the legacy flat keys now that they live in google_accounts[]
    # (only ever mutates the loaded copy — writers persist this cleanup)
    for k in _ACCOUNT_KEYS:
        cfg.pop(k, None)
    return cfg


def _resolve_active(cfg: dict) -> tuple[int, dict | None]:
    """(index, account) of the active account; (-1, None) when none exist."""
    accts = cfg.get("google_accounts") or []
    if not accts:
        return -1, None
    active = cfg.get("active_google_account")
    if isinstance(active, str) and active.lstrip("-").isdigit():
        active = int(active)
    if isinstance(active, int):
        idx = active if 0 <= active < len(accts) else 0
    elif isinstance(active, str):
        al = active.strip().lower()
        idx = next((i for i, a in enumerate(accts)
                    if str(a.get("firebase_email", "")).strip().lower() == al), 0)
    else:
        idx = 0
    return idx, accts[idx]


def _active_account_cfg() -> dict:
    """Full config view with the ACTIVE account's tokens overlaid on top, so
    existing code that reads firebase_uid / firebase_refresh_token / etc.
    works unchanged."""
    cfg = _load_cfg()
    _ensure_accounts(cfg)
    _idx, acc = _resolve_active(cfg)
    view = {k: v for k, v in cfg.items()
            if k not in ("google_accounts", "active_google_account")}
    if acc:
        view.update({k: v for k, v in acc.items() if v})
    return view


def _save_active_account(patch: dict) -> None:
    """Merge token updates into the ACTIVE account entry (keeps it active)."""
    cfg = _load_cfg()
    _ensure_accounts(cfg)
    accts = cfg["google_accounts"]
    idx, _acc = _resolve_active(cfg)
    if idx < 0:
        accts.append({})
        idx = 0
        cfg["active_google_account"] = "0"
    accts[idx].update({k: v for k, v in patch.items() if v is not None})
    email = accts[idx].get("firebase_email")
    if email:
        cfg["active_google_account"] = email
    _write_cfg(cfg)


def _store_account(patch: dict) -> tuple[str, int]:
    """Add or refresh an account entry (dedup by email) and make it active.
    Returns (display label, total account count)."""
    cfg = _load_cfg()
    _ensure_accounts(cfg)
    accts = cfg["google_accounts"]
    email = (patch.get("firebase_email") or "").strip().lower()
    idx = None
    if email:
        idx = next((i for i, a in enumerate(accts)
                    if str(a.get("firebase_email", "")).strip().lower() == email),
                   None)
    if idx is None:
        accts.append({})
        idx = len(accts) - 1
    accts[idx].update({k: v for k, v in patch.items() if v is not None})
    cfg["active_google_account"] = email or str(idx)
    _write_cfg(cfg)
    who = (patch.get("firebase_display_name")
           or email or f"account #{idx + 1}")
    return who, len(accts)


def accounts_count() -> int:
    cfg = _load_cfg()
    _ensure_accounts(cfg)
    return len(cfg.get("google_accounts") or [])


def list_accounts() -> str:
    """Numbered list of signed-in Google accounts with the active one marked."""
    cfg = _load_cfg()
    _ensure_accounts(cfg)
    accts = cfg.get("google_accounts") or []
    if not accts:
        return "No Google accounts signed in. Say 'sign in with Google' first."
    idx, _ = _resolve_active(cfg)
    lines = [f"Google accounts ({len(accts)}):"]
    for i, a in enumerate(accts, 1):
        marker = "\u25b6 " if i - 1 == idx else "    "
        email = a.get("firebase_email") or "(unknown email)"
        name = a.get("firebase_display_name") or ""
        lines.append(f"  {marker}{i}. {email}" + (f" ({name})" if name else ""))
    lines.append("Say 'switch to Google account <number or email>' to change.")
    return "\n".join(lines)


def get_accounts() -> list[dict]:
    """Structured list of every signed-in Google account.

    Returns [{email, display_name, uid, active, index}] — the ACTIVE account
    drives contacts / calls / email by default, but contacts can be aggregated
    across ALL accounts (see all_contacts / find_contact)."""
    cfg = _load_cfg()
    _ensure_accounts(cfg)
    accts = cfg.get("google_accounts") or []
    active_idx, _ = _resolve_active(cfg)
    out = []
    for i, a in enumerate(accts):
        out.append({
            "email":        a.get("firebase_email", ""),
            "display_name": a.get("firebase_display_name", ""),
            "uid":          a.get("firebase_uid", ""),
            "active":       i == active_idx,
            "index":        i,
        })
    return out


def available_from_accounts() -> list[str]:
    """Emails of all signed-in accounts — used by send_email to pick the FROM."""
    return [a.get("email") for a in get_accounts() if a.get("email")]


def _accounts_full() -> list[dict]:
    """Full account dicts (WITH token fields) for internal contact/email
    logic. `get_accounts()` intentionally strips tokens for the UI/API;
    contact aggregation needs them, so it iterates this instead. The tokens
    never leave this module through public helpers."""
    cfg = _load_cfg()
    _ensure_accounts(cfg)
    accts = cfg.get("google_accounts") or []
    active_idx, _ = _resolve_active(cfg)
    out = []
    for i, a in enumerate(accts):
        rec = dict(a)
        rec["active"] = i == active_idx
        rec["index"] = i
        out.append(rec)
    return out


def _find_account_index(key) -> int | None:
    """Resolve a 1-based index, email fragment, or display-name fragment to an
    account index (0-based). None when nothing matches."""
    cfg = _load_cfg()
    _ensure_accounts(cfg)
    accts = cfg.get("google_accounts") or []
    if not accts:
        return None
    if key is None:
        return None
    k = str(key).strip()
    if not k:
        return None          # never match an empty key
    if k.isdigit():
        i = int(k) - 1
        return i if 0 <= i < len(accts) else None
    kl = k.lower()
    for i, a in enumerate(accts):
        if kl in str(a.get("firebase_email", "")).lower() \
                or kl in str(a.get("firebase_display_name", "")).lower():
            return i
    return None


def switch_account(key) -> str:
    """Make a different signed-in Google account the active one."""
    idx = _find_account_index(key)
    if idx is None:
        if key is None or str(key).strip() == "":
            return list_accounts()
        return f"No signed-in Google account matches '{key}'.\n{list_accounts()}"
    cfg = _load_cfg()
    _ensure_accounts(cfg)
    who = cfg["google_accounts"][idx].get("firebase_email") \
        or f"account #{idx + 1}"
    cfg["active_google_account"] = who
    _write_cfg(cfg)
    return (f"Switched to Google account {who}. Verified contacts, calls and "
            f"email now use this account.")


def remove_account(key) -> str:
    """Remove a signed-in Google account. If it was active, another becomes
    active; when none remain the legacy flat keys are cleared too."""
    idx = _find_account_index(key)
    if idx is None:
        return f"No signed-in Google account matches '{key}'.\n{list_accounts()}"
    cfg = _load_cfg()
    _ensure_accounts(cfg)
    accts = cfg["google_accounts"]
    active_idx, _ = _resolve_active(cfg)
    who = accts[idx].get("firebase_email") or f"account #{idx + 1}"
    del accts[idx]
    if not accts:
        cfg.pop("google_accounts", None)
        cfg.pop("active_google_account", None)
        for k in _ACCOUNT_KEYS:
            cfg.pop(k, None)
        _write_cfg(cfg)   # persist the removal BEFORE returning
        return f"Removed Google account {who}. No accounts remain signed in."
    if idx == active_idx or active_idx >= len(accts):
        cfg["active_google_account"] = accts[0].get("firebase_email") or "0"
    _write_cfg(cfg)
    return (f"Removed Google account {who}. {len(accts)} account(s) remain.\n"
            + list_accounts())


# -- Status helpers -----------------------------------------------------------

def is_configured() -> bool:
    cfg = _load_cfg()
    return bool(
        cfg.get("google_oauth_client_id")
        and cfg.get("google_oauth_client_secret")
        and cfg.get("firebase_api_key")
        and cfg.get("firebase_project_id")
    )


def is_signed_in() -> bool:
    cfg = _load_cfg()
    if cfg.get("google_accounts"):
        return True
    return bool(cfg.get("firebase_refresh_token")) or bool(cfg.get("firebase_uid"))


def status() -> str:
    cfg = _load_cfg()
    if not is_configured():
        return (
            "Google sign-in is not configured yet. Add google_oauth_client_id, "
            "google_oauth_client_secret, firebase_api_key and firebase_project_id "
            "to config/api_keys.json (full steps in FIREBASE_SETUP.md), then say "
            "'sign in with Google'."
        )
    if not is_signed_in():
        return "Not signed in. Say 'sign in with Google' to connect your Google account."
    _ensure_accounts(cfg)
    accts = cfg.get("google_accounts") or []
    if accts:
        idx, acc = _resolve_active(cfg)
        email = acc.get("firebase_email", "")
        name  = acc.get("firebase_display_name", "")
        uid   = acc.get("firebase_uid", "")
        who   = name or email or "your Google account"
        out = f"Signed in as {who} ({email}) - Google identity confirmed. uid={uid}"
        if len(accts) > 1:
            out += (f" | {idx + 1} of {len(accts)} accounts — say "
                    f"'list Google accounts' to switch.")
        return out
    # legacy single-account fallback
    email = cfg.get("firebase_email", "")
    name  = cfg.get("firebase_display_name", "")
    uid   = cfg.get("firebase_uid", "")
    who   = name or email or "your Google account"
    return f"Signed in as {who} ({email}) - Google identity confirmed. uid={uid}"


# -- Google OAuth (localhost loopback) ----------------------------------------

class _CallbackHandler(BaseHTTPRequestHandler):
    """Catches the OAuth redirect on 127.0.0.1:<port>/ and stores ?code=."""
    code: str | None = None
    error: str | None = None   # set when Google returns ?error= (user denied)

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        if "code" in query:
            type(self).code = query["code"][0]
            body = (
                b"<html><body style='font-family:sans-serif'>"
                b"<h2 style='text-align:center;margin-top:15%'>&#10003; "
                b"KeysAI signed in &mdash; you can close this tab.</h2>"
                b"</body></html>"
            )
            self.send_response(200)
        elif "error" in query:
            type(self).error = query["error"][0]
            body = (
                b"<html><body style='font-family:sans-serif'>"
                b"<h2 style='text-align:center;margin-top:15%'>Sign-in was not "
                b"completed &mdash; you can close this tab.</h2>"
                b"</body></html>"
            )
            self.send_response(200)
        else:
            body = (
                b"<html><body style='font-family:sans-serif'>"
                b"<h2 style='text-align:center;margin-top:15%'>Authentication "
                b"failed &mdash; close this tab and try again.</h2>"
                b"</body></html>"
            )
            self.send_response(400)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence the default "GET / ..." logging
        pass


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _sign_in_hint(msg: str) -> str:
    """Map known Firebase sign-in failure messages to an actionable hint."""
    m = (msg or "").lower()
    if "api key not valid" in m or "api_key_invalid" in m:
        return (
            "The firebase_api_key in config/api_keys.json is invalid. Re-copy the "
            "Web API key (apiKey, starts with 'AIza') from Firebase Project "
            "Settings > Your apps > Web (</>) config for the SAME project where "
            "Google sign-in is enabled. Make sure the key has no referrer/IP "
            "restrictions in Google Cloud > APIs & Services > Credentials."
        )
    if "google_signin_not_enabled" in m:
        return (
            "Enable the Google provider: Firebase > Build > Authentication > "
            "Sign-in method > Google > Enable > Save."
        )
    if "operation_not_allowed" in m or "configuration_not_found" in m:
        return (
            "The Google provider isn't fully configured in this Firebase project. "
            "Verify Authentication > Sign-in method > Google is enabled and that "
            "the apiKey/projectId are from that same project."
        )
    return ""


def _api_error(r) -> str:
    """Extract a human-readable error code/message from a REST error response.

    Handles both Firebase style
    {"error": {"message": "GOOGLE_SIGNIN_NOT_ENABLED", "status": "..."}}
    and Google OAuth token style
    {"error": "invalid_grant", "error_description": "..."}."""
    try:
        err = r.json().get("error", {})
        if isinstance(err, dict):
            msg = (err.get("message") or err.get("error_description")
                   or err.get("status") or "")
            if msg:
                return str(msg)[:300]
        elif isinstance(err, str):
            desc = r.json().get("error_description") or ""
            return f"{err}: {desc}"[:300] if desc else err[:300]
        return (r.text or "")[:300]
    except Exception:
        return (r.text or "")[:300] or f"HTTP {r.status_code}"


def _exchange_google_code(code: str, client_id: str, client_secret: str,
                          redirect_uri: str) -> dict:
    r = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Google token exchange failed (HTTP {r.status_code}): {_api_error(r)}")
    data = r.json()
    if "id_token" not in data:
        raise RuntimeError(f"Google token exchange failed: {data.get('error_description', data)}")
    return data


def _firebase_sign_in(google_id_token: str, api_key: str) -> dict:
    r = requests.post(
        f"{FIREBASE_AUTH}/accounts:signInWithIdp",
        params={"key": api_key},
        json={
            "postBody": f"id_token={google_id_token}&providerId=google.com",
            "requestUri": "http://localhost",
            "returnIdpCredential": True,
            "returnSecureToken": True,
        },
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Firebase sign-in failed (HTTP {r.status_code}): {_api_error(r)}")
    data = r.json()
    if "idToken" not in data or "refreshToken" not in data:
        raise RuntimeError(f"Firebase sign-in failed: {data.get('error', {}).get('message', data)}")
    return data


def sign_in(timeout: float = _SIGN_IN_TIMEOUT) -> str:
    cfg = _load_cfg()
    client_id     = cfg.get("google_oauth_client_id", "")
    client_secret = cfg.get("google_oauth_client_secret", "")
    api_key       = cfg.get("firebase_api_key", "")

    if not (client_id and client_secret and api_key):
        return (
            "Google sign-in is not configured. Follow FIREBASE_SETUP.md and add "
            "google_oauth_client_id, google_oauth_client_secret, firebase_api_key "
            "and firebase_project_id to config/api_keys.json."
        )

    port         = _free_port()
    redirect_uri = f"http://127.0.0.1:{port}/"
    _CallbackHandler.code  = None
    _CallbackHandler.error = None

    server   = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    deadline = time.time() + timeout

    def _serve_until_code() -> None:
        # Browsers sometimes fire a favicon/prefetch request first — keep
        # serving requests until the real ?code= redirect arrives, the user
        # denies (?error=), or we time out.
        while (time.time() < deadline
               and _CallbackHandler.code is None
               and _CallbackHandler.error is None):
            try:
                server.handle_request()
            except Exception:
                break

    server_thread = threading.Thread(target=_serve_until_code, daemon=True)
    server_thread.start()

    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode({
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile ' + CONTACTS_SCOPE + ' ' + GMAIL_SCOPE
                 + ' ' + GMAIL_SEND_SCOPE,
        'access_type': 'offline',
        # 'select_account' shows the Google account picker every time, so the
        # user can ADD another account or choose which one to sign in with.
        'prompt': 'select_account',
    })}"

    try:
        webbrowser.open(auth_url)
        while (time.time() < deadline
               and _CallbackHandler.code is None
               and _CallbackHandler.error is None):
            time.sleep(0.2)
        code = _CallbackHandler.code
        if _CallbackHandler.error:
            return "Sign-in was not completed (you denied/closed the Google approval). Try again when ready."
        if not code:
            return "Sign-in timed out - no authorization code received. Try again."
        google_tokens = _exchange_google_code(code, client_id, client_secret, redirect_uri)
        fb            = _firebase_sign_in(google_tokens["id_token"], api_key)
        expires       = int(fb.get("expiresIn", "3600") or 3600)
        who, total = _store_account({
            "firebase_refresh_token":    fb["refreshToken"],
            "firebase_id_token":         fb["idToken"],
            "firebase_id_token_expires": str(int(time.time()) + expires),
            "firebase_uid":              fb.get("localId", ""),
            "firebase_email":            fb.get("email", ""),
            "firebase_display_name":     fb.get("displayName", ""),
            # Google's own tokens let us read the user's real contacts (People API)
            "google_access_token":       google_tokens.get("access_token", ""),
            "google_access_expires":     str(int(time.time()) + int(google_tokens.get("expires_in", 3600) or 3600)),
            "google_refresh_token":      google_tokens.get("refresh_token", ""),
        })
        who = who or fb.get("email") or "your Google account"
        extra = f" Now active. {total} account(s) signed in — say 'list Google accounts' to switch." if total > 1 else ""
        return f"Signed in with Google as {who}. Your contacts are now backed by Firebase.{extra}"
    except Exception as e:
        msg = f"Google sign-in failed: {str(e)[:200]}"
        hint = _sign_in_hint(str(e))
        if hint:
            msg += f"\nHINT: {hint}"
        return msg
    finally:
        server.server_close()
        server_thread.join(timeout=2)


def sign_out() -> str:
    """Remove the ACTIVE Google account (other accounts stay signed in)."""
    cfg = _load_cfg()
    _ensure_accounts(cfg)
    accts = cfg.get("google_accounts") or []
    if not accts:
        _clear_cfg(*_ACCOUNT_KEYS)
        return "You were not signed in with Google."
    idx, acc = _resolve_active(cfg)
    who = acc.get("firebase_email") or acc.get("firebase_display_name") \
        or "your account"
    if 0 <= idx < len(accts):
        del accts[idx]
    if not accts:
        cfg.pop("google_accounts", None)
        cfg.pop("active_google_account", None)
        for k in _ACCOUNT_KEYS:
            cfg.pop(k, None)
        _write_cfg(cfg)   # persist the removal BEFORE returning
        return (f"Signed out of Google account {who}. No accounts remain — "
                f"say 'sign in with Google' to reconnect.")
    cfg["active_google_account"] = accts[0].get("firebase_email") or "0"
    _write_cfg(cfg)
    return (f"Signed out of Google account {who}. {len(accts)} other "
            f"account(s) remain — say 'list Google accounts' to switch.")


# -- Firebase session / token refresh -----------------------------------------

def _get_id_token() -> str:
    cfg = _active_account_cfg()
    tok = cfg.get("firebase_id_token", "")
    exp = float(cfg.get("firebase_id_token_expires", 0) or 0)
    if tok and exp > time.time() + 60:
        return tok
    refresh = cfg.get("firebase_refresh_token", "")
    api_key = cfg.get("firebase_api_key", "")
    if not refresh or not api_key:
        raise RuntimeError("Not signed in with Google (missing refresh token).")
    r = requests.post(
        f"{FIREBASE_SECURE}",
        params={"key": api_key},
        data={"grant_type": "refresh_token", "refresh_token": refresh},
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Firebase token refresh failed (HTTP {r.status_code}): {_api_error(r)}")
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"Token refresh failed: {data.get('error', {}).get('message', data)}")
    _save_active_account({
        "firebase_id_token":         data["access_token"],
        "firebase_id_token_expires": str(int(time.time()) + int(data.get("expires_in", 3600))),
    })
    return data["access_token"]


# -- Firestore helpers --------------------------------------------------------

def _project_id() -> str:
    pid = _load_cfg().get("firebase_project_id", "")
    if not pid:
        raise RuntimeError("firebase_project_id is not set (see FIREBASE_SETUP.md).")
    return pid


def _uid() -> str:
    uid = _active_account_cfg().get("firebase_uid", "")
    if not uid:
        raise RuntimeError("Not signed in with Google yet.")
    return uid


def _fs(method: str, path: str, body: dict | None = None) -> requests.Response:
    url = (
        f"{FIRESTORE_BASE}/projects/{_project_id()}"
        f"/databases/(default)/documents{path}"
    )
    headers = {
        "Authorization": f"Bearer {_get_id_token()}",
        "Content-Type":  "application/json",
    }
    if body is not None:
        return requests.request(method, url, headers=headers, json=body, timeout=30)
    return requests.request(method, url, headers=headers, timeout=30)


def _id_token_for(acc: dict) -> str:
    """A valid Firebase ID token for a SPECIFIC account dict, refreshing it
    through the Secure Token endpoint when near expiry."""
    tok = acc.get("firebase_id_token", "")
    exp = float(acc.get("firebase_id_token_expires", 0) or 0)
    if tok and exp > time.time() + 60:
        return tok
    refresh = acc.get("firebase_refresh_token", "")
    api_key = _load_cfg().get("firebase_api_key", "")
    if not refresh or not api_key:
        raise RuntimeError("Not signed in with Google (missing refresh token).")
    r = requests.post(
        f"{FIREBASE_SECURE}",
        params={"key": api_key},
        data={"grant_type": "refresh_token", "refresh_token": refresh},
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Firebase token refresh failed (HTTP {r.status_code}): {_api_error(r)}")
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"Token refresh failed: {data.get('error', {}).get('message', data)}")
    _save_account_token(acc, {
        "firebase_id_token":         data["access_token"],
        "firebase_id_token_expires": str(int(time.time()) + int(data.get("expires_in", 3600))),
    })
    return data["access_token"]


def _fs_for(acc: dict, method: str, path: str, body: dict | None = None) -> requests.Response:
    """Firestore REST call scoped to a SPECIFIC account's tokens."""
    url = (
        f"{FIRESTORE_BASE}/projects/{_project_id()}"
        f"/databases/(default)/documents{path}"
    )
    headers = {
        "Authorization": f"Bearer {_id_token_for(acc)}",
        "Content-Type":  "application/json",
    }
    if body is not None:
        return requests.request(method, url, headers=headers, json=body, timeout=30)
    return requests.request(method, url, headers=headers, timeout=30)


def _contacts_for_account(acc: dict) -> list[dict]:
    """Verified contacts stored in Firestore for ONE account (by its uid).

    Matches list_contacts()'s honest-error contract: 404 (collection not
    created yet) → [], any other non-200 (403/429/500…) RAISES so callers
    report "could not check right now" instead of a false "not found"."""
    uid = acc.get("firebase_uid", "")
    if not uid or not is_signed_in():
        return []
    r = _fs_for(acc, "GET", f"/users/{uid}/contacts")
    if r.status_code == 200:
        docs = r.json().get("documents", [])
        return [_decode_fields(d.get("fields", {})) for d in docs]
    if r.status_code == 404:
        return []
    raise RuntimeError(
        f"Firestore list contacts failed (HTTP {r.status_code}): {r.text[:150]}"
    )


def _person_from_people(p: dict) -> dict:
    """Extract {name, phone, email, source:'google'} from a Google People API
    person dict (used by connections.list and searchContacts). Returns {}
    when the person carries no usable fields."""
    name = ""
    for n in (p.get("names") or []):
        if n.get("displayName"):
            name = n["displayName"]
            break
    phones = [ph.get("value", "") for ph in (p.get("phoneNumbers") or [])
              if ph.get("value")]
    emails = [em.get("value", "") for em in (p.get("emailAddresses") or [])
              if em.get("value")]
    if not (name or phones or emails):
        return {}
    return {
        "name":   name,
        "phone":  phones[0] if phones else "",
        "email":  emails[0] if emails else "",
        "source": "google",
    }


def _people_connections(acc: dict, limit: int = 200) -> list[dict]:
    """ALL of one account's real Google/phone contacts via People API
    connections.list. Returns [{name, phone, email, source:'google'}]"""
    r = requests.get(
        f"{PEOPLE_API}/people/me/connections",
        params={
            "personFields": "names,emailAddresses,phoneNumbers",
            "pageSize":     str(limit),
        },
        headers={"Authorization": f"Bearer {_google_access_token(acc)}"},
        timeout=30,
    )
    r.raise_for_status()
    out = []
    for p in (r.json().get("connections") or []):
        person = _person_from_people(p)
        if person:
            out.append(person)
    return out


def _search_people_for(acc: dict, query: str, limit: int = 8) -> list[dict]:
    """searchContacts on ONE specific account (query-based, cheaper than
    listing all connections when just resolving a name)."""
    q = (query or "").strip()
    if not q:
        return []
    r = requests.get(
        f"{PEOPLE_API}/people:searchContacts",
        params={
            "query":    q,
            "readMask": "names,emailAddresses,phoneNumbers",
            "pageSize": str(limit),
        },
        headers={"Authorization": f"Bearer {_google_access_token(acc)}"},
        timeout=30,
    )
    r.raise_for_status()
    out = []
    for res in (r.json().get("results") or []):
        person = _person_from_people(res.get("person", {}))
        if person:
            out.append(person)
    return out


def _doc_id(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip()).strip("._").lower()
    return slug or "contact"


def _encode_fields(data: dict) -> dict:
    fields = {}
    for k, v in data.items():
        if isinstance(v, bool):
            fields[k] = {"booleanValue": v}
        elif isinstance(v, (int, float)):
            fields[k] = {"doubleValue": v}
        else:
            fields[k] = {"stringValue": str(v or "")}
    return fields


def _decode_fields(fields: dict) -> dict:
    out = {}
    for k, v in (fields or {}).items():
        if "stringValue" in v:
            out[k] = v["stringValue"]
        elif "booleanValue" in v:
            out[k] = v["booleanValue"]
        elif "integerValue" in v:
            try:
                out[k] = int(v["integerValue"])
            except Exception:
                out[k] = v["integerValue"]
        elif "doubleValue" in v:
            out[k] = v["doubleValue"]
        else:
            out[k] = v
    return out


# -- Verified contacts CRUD ---------------------------------------------------

def add_contact(name: str, google_email: str = "", phone: str = "",
                platform: str = "", verified: bool = False) -> str:
    """Add (or update) a contact in the signed-in user's Firestore collection."""
    name = (name or "").strip()
    if not name:
        return "Please provide a contact name."
    if not is_signed_in():
        return "Not signed in with Google. Say 'sign in with Google' first."
    doc = _doc_id(name)
    r = _fs("PATCH", f"/users/{_uid()}/contacts/{doc}", {
        "fields": _encode_fields({
            "name":         name,
            "google_email": google_email.strip(),
            "phone":        phone.strip(),
            "platform":     platform.strip() or "whatsapp",
            "verified":     bool(verified),
        }),
    })
    if r.status_code in (200, 201):
        state = "confirmed" if verified else "added (not yet confirmed)"
        return f"Contact '{name}' {state} to your verified Google contacts."
    return f"Could not add contact (HTTP {r.status_code}): {r.text[:200]}"


def list_contacts() -> list[dict]:
    """All contacts for the signed-in user, sorted by name.

    Returns [] when not signed in or when the collection does not exist yet
    (404). Any other non-200 status (403/429/500...) RAISES so callers report
    "could not verify right now" honestly instead of mistaking a server error
    for an empty contact list."""
    if not is_signed_in():
        return []
    r = _fs("GET", f"/users/{_uid()}/contacts")
    if r.status_code == 200:
        docs = r.json().get("documents", [])
        contacts = [_decode_fields(d.get("fields", {})) for d in docs]
        contacts.sort(key=lambda c: c.get("name", "").lower())
        return contacts
    if r.status_code == 404:
        return []  # collection not created yet — genuinely no contacts
    raise RuntimeError(f"Firestore list contacts failed (HTTP {r.status_code}): {r.text[:150]}")


def list_contacts_display() -> str:
    if not is_signed_in():
        return "Not signed in with Google."
    note = ""
    try:
        contacts = list_contacts()
    except Exception as e:
        # Firestore is unavailable (expired/invalid firebase_api_key, outage).
        # The Google People API contacts are still real contacts and may be
        # readable with the Google token, so show those instead of failing the
        # whole request — saying why the verified list is missing.
        note = f"\n(Verified list unavailable: {str(e)[:120]})"
        contacts = all_contacts()
        if contacts:
            lines = [f"Google contacts ({len(contacts)}):"]
            for c in contacts[:120]:
                bits = [f"  • {c.get('name', '?')}"]
                if c.get("email"):
                    bits.append(c["email"])
                if c.get("phone"):
                    bits.append(c["phone"])
                lines.append(" ".join(bits))
            lines.append(note.strip())
            return "\n".join(lines)
        return ("Could not read your contacts right now: " + str(e)[:160]
                + "\nRe-copy a valid firebase_api_key into config/api_keys.json "
                  "(see FIREBASE_SETUP.md) or sign in with Google again.")
    if not contacts:
        return "No verified contacts yet. Say 'add contact <name> with Google account <email>'."
    lines = ["Verified contacts:"]
    for c in contacts:
        flag = "\u2713" if c.get("verified") else "\u25cb"
        email = c.get("google_email", "") or "no email"
        lines.append(f"  {flag} {c.get('name', '?')} - {email} ({c.get('platform', 'whatsapp')})")
    return "\n".join(lines)


def _person_key(c: dict) -> str:
    """Dedupe key for a contact across accounts: email, else phone digits,
    else normalized full name. Empty when the record carries nothing."""
    em = (c.get("email") or c.get("google_email") or "").strip().lower()
    if em:
        return em
    ph = re.sub(r"\D", "", c.get("phone") or "")
    if ph:
        return f"p:{ph}"
    nm = " ".join((c.get("name") or "").strip().lower().split())
    return f"n:{nm}" if nm else ""


def all_contacts() -> list[dict]:
    """Contacts aggregated across EVERY signed-in Google account.

    Combines each account's Firestore verified contacts with their real
    Google/People API contacts, deduped by email/phone/name. Every record
    gains an `account` field (the email it came from) so tools can tell the
    user which account the contact belongs to.

    Network errors on one account are skipped so a blip never hides contacts
    that other accounts DID return."""
    out: list[dict] = []
    seen: set = set()
    for acc in _accounts_full():
        email = acc.get("firebase_email", "") or ""
        try:
            for c in _contacts_for_account(acc):
                key = _person_key(c)
                rec = dict(c)
                rec["account"] = email
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                out.append(rec)
        except Exception:
            pass
        try:
            for c in _people_connections(acc):
                key = _person_key(c)
                rec = dict(c)
                rec["account"] = email
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                out.append(rec)
        except Exception:
            pass
    out.sort(key=lambda c: (c.get("name") or "").lower())
    return out


def list_all_contacts_display() -> str:
    """Human-readable list of contacts from ALL signed-in Google accounts."""
    if not is_signed_in():
        return "Not signed in with Google."
    try:
        contacts = all_contacts()
    except Exception as e:
        return f"Could not load contacts right now: {str(e)[:150]}"
    accounts = get_accounts()
    if not contacts:
        return (f"No contacts found across your {len(accounts) or 'signed-in'} "
                "Google account(s).")
    lines = [f"Contacts across {len(accounts)} Google account(s) ({len(contacts)} total):"]
    for c in contacts[:150]:
        acct = c.get("account") or ""
        bits = [f"  • {c.get('name', '?')}"]
        if c.get("email"):
            bits.append(c["email"])
        if c.get("phone"):
            bits.append(c["phone"])
        if c.get("verified"):
            bits.append("✓")
        if acct:
            bits.append(f"[{acct}]")
        lines.append(" ".join(bits).rstrip())
    if len(contacts) > 150:
        lines.append(f"  … and {len(contacts) - 150} more.")
    lines.append("Say 'send email to <name>' to email someone — I'll pick the account.")
    return "\n".join(lines)


def verify_contact(name: str) -> dict | None:
    """Find a contact by name or Google email. Returns its record (which has a
    'verified' bool) or None if unknown.

    Does NOT raise when the user is not signed in (returns None). Network/API
    errors DO propagate so callers can report "could not verify right now"
    honestly instead of mistaking a blip for "contact not in list"."""
    key = (name or "").strip().lower()
    if not key:
        return None
    try:
        contacts = list_contacts()
    except Exception:
        if not is_signed_in():
            raise
        # Firestore down/credential invalid — verify against the real Google
        # contacts that ARE readable rather than reporting a false "not found".
        contacts = all_contacts()
    for c in contacts:
        haystacks = (c.get("name", ""), c.get("google_email", ""), c.get("email", ""))
        if any(key in (h or "").lower() for h in haystacks):
            return c
    return None


def verify_contact_display(name: str) -> str:
    c = verify_contact(name)
    if c is None:
        return f"'{name}' is not in your verified contacts."
    status_txt = "confirmed via Google" if c.get("verified") else "added but NOT yet confirmed via Google"
    email = c.get("google_email", "") or "no Google email on file"
    return f"'{c.get('name', name)}' - {status_txt}. Google account: {email}."


def confirm_contact(name: str) -> str:
    """Mark an existing contact as confirmed via Google (verified=true)."""
    c = verify_contact(name)
    if c is None:
        return (
            f"'{name}' is not in your contacts. Add it first with google_account "
            "action='add_contact' (include the person's Google account email)."
        )
    doc = _doc_id(c.get("name", name))
    r = _fs("PATCH", f"/users/{_uid()}/contacts/{doc}", {
        "fields": _encode_fields({"verified": True}),
    })
    if r.status_code in (200, 201):
        return f"Contact '{c.get('name', name)}' is now confirmed via Google."
    return f"Could not confirm contact (HTTP {r.status_code}): {r.text[:200]}"


def remove_contact(name: str) -> str:
    c = verify_contact(name)
    if c is None:
        return f"'{name}' is not in your contacts."
    doc = _doc_id(c.get("name", name))
    r = _fs("DELETE", f"/users/{_uid()}/contacts/{doc}")
    if r.status_code in (200, 204):
        return f"Removed contact '{c.get('name', name)}'."
    return f"Could not remove contact (HTTP {r.status_code}): {r.text[:200]}"


# -- Google People API (the user's REAL mobile/Google contacts) --------------

def _save_account_token(acc: dict, patch: dict) -> None:
    """Merge a token refresh into a SPECIFIC account entry (not necessarily
    the active one) by matching its firebase_email."""
    email = (acc.get("firebase_email") or "").strip().lower()
    cfg = _load_cfg()
    _ensure_accounts(cfg)
    accts = cfg.get("google_accounts") or []
    idx = None
    if email:
        idx = next((i for i, a in enumerate(accts)
                    if str(a.get("firebase_email", "")).strip().lower() == email),
                   None)
    if idx is None:
        idx, _ = _resolve_active(cfg)
        if idx < 0:
            return
    accts[idx].update({k: v for k, v in patch.items() if v is not None})
    _write_cfg(cfg)


def _google_access_token(acc: dict | None = None) -> str:
    """A valid Google access token for the People/Gmail API, refreshing when
    expired. `acc` is an account dict from google_accounts[]; when omitted the
    ACTIVE account is used (matches the old behaviour).

    The offline refresh token is captured during sign_in (access_type=offline
    + prompt=select_account) and stored with each account."""
    if acc is None:
        cfg = _active_account_cfg()
        acc = {
            "google_access_token":   cfg.get("google_access_token", ""),
            "google_access_expires": cfg.get("google_access_expires", ""),
            "google_refresh_token":  cfg.get("google_refresh_token", ""),
            "firebase_email":        cfg.get("firebase_email", ""),
        }
    tok = acc.get("google_access_token", "")
    exp = float(acc.get("google_access_expires", 0) or 0)
    if tok and exp > time.time() + 60:
        return tok
    refresh      = acc.get("google_refresh_token", "")
    client_id    = _load_cfg().get("google_oauth_client_id", "")
    client_secret = _load_cfg().get("google_oauth_client_secret", "")
    if not (refresh and client_id and client_secret):
        raise RuntimeError(
            "Google contacts access is not available — sign in with Google again."
        )
    r = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id":     client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
            "grant_type":    "refresh_token",
        },
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Google token refresh failed (HTTP {r.status_code}): {_api_error(r)}")
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(
            f"Google token refresh failed: {data.get('error_description', data)}"
        )
    _save_account_token(acc, {
        "google_access_token":   data["access_token"],
        "google_access_expires": str(int(time.time()) + int(data.get("expires_in", 3600) or 3600)),
    })
    return data["access_token"]


def search_google_contacts(query: str, limit: int = 8) -> list[dict]:
    """Search the user's REAL Google (phone-synced) contacts by name/phone/email.

    Returns [{name, phone, email, source:'google'}]. Network/auth errors
    RAISE so callers report "could not check right now" honestly instead of
    mistaking a blip for "not in contacts" (same rule as list_contacts)."""
    q = (query or "").strip()
    if not q:
        return []
    r = requests.get(
        f"{PEOPLE_API}/people:searchContacts",
        params={
            "query":    q,
            "readMask": "names,emailAddresses,phoneNumbers",
            "pageSize": str(limit),
        },
        headers={"Authorization": f"Bearer {_google_access_token()}"},
        timeout=30,
    )
    r.raise_for_status()
    out = []
    for res in (r.json().get("results") or []):
        person = _person_from_people(res.get("person", {}))
        if person:
            out.append(person)
    return out


def _local_vcard_contacts() -> list[dict]:
    """Contacts saved on THIS PC (Windows Contacts folder .vcf files).

    Fallback so names can still be confirmed when Google access is off-line or
    not configured. Returns [{name, phone, email, source:'local'}]."""
    out = []
    try:
        folder = Path.home() / "Contacts"
        if not folder.is_dir():
            return []
        for f in sorted(folder.glob("*.vcf"))[:200]:
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            name = email = phone = ""
            for raw in text.splitlines():
                line = raw.strip()
                up   = line.upper()
                if not name and up.startswith("FN:"):
                    name = line.split(":", 1)[1].strip()
                elif not name and up.startswith("N:"):
                    # N:Last;First;Middle;Prefix;Suffix  (vCard standard)
                    parts = line.split(":", 1)[1].split(";")
                    if len(parts) >= 2:
                        name = f"{parts[1]} {parts[0]}".strip()
                elif not email and up.startswith("EMAIL"):
                    email = line.split(":", 1)[1].strip()
                elif not phone and up.startswith("TEL"):
                    phone = line.split(":", 1)[1].strip()
            if name or phone or email:
                out.append({"name": name, "phone": phone, "email": email, "source": "local"})
    except Exception:
        pass
    return out


def _same_person(a: dict, b: dict) -> bool:
    """True when two records plausibly refer to the same person: equal
    normalized names, or one name is a whole-word subset of the other.
    Guards the phone-merge so a partial-token match (e.g. 'Papa' vs
    'Papadopoulos') can never attach a DIFFERENT person's number."""
    na = (a.get("name") or "").strip().lower()
    nb = (b.get("name") or "").strip().lower()
    if not na or not nb:
        return False
    if na == nb:
        return True
    wa = {w for w in na.split() if w}
    wb = {w for w in nb.split() if w}
    return bool(wa) and bool(wb) and (wa <= wb or wb <= wa)


def _contact_score(c: dict, key: str) -> int:
    """0 = no match; higher = a better match for the given name/phone/email."""
    key = (key or "").strip().lower()
    if not key:
        return 0
    cname      = (c.get("name") or "").strip().lower()
    phone      = (c.get("phone") or "").strip().lower()
    email      = (c.get("email") or "").strip().lower()
    key_digits = re.sub(r"\D", "", key)
    score = 0
    if cname and cname == key:
        score += 100
    elif cname and (key in cname or cname in key or any(
            key == tok or tok.startswith(key) for tok in cname.split())):
        score += 60
    if email and (email == key or key in email or key in email.split("@")[0]):
        score += 40
    if phone and key_digits and key_digits in re.sub(r"\D", "", phone):
        score += 40
    if score and (phone or email):
        score += 15   # prefer entries that can actually be messaged/called
    return score


def find_contact(query: str) -> dict | None:
    """Resolve a spoken name / phone / email to a REAL contact.

    Priority: 1) verified Firestore contacts, 2) Google People API (the user's
    actual mobile contacts), 3) local Windows Contacts vCards. Returns the best
    match {name, phone, email, source, verified} or None if not found.
    If the winning record lacks a phone but the SAME person (equal / whole-word
    subset name) has one in another source, the phone is merged in so
    messaging/calling targets the actual number — never a partial-token match
    from an unrelated contact.
    Network errors RAISE (when signed in) so callers honestly say "could not
    check right now" instead of claiming the person isn't in contacts."""
    key = (query or "").strip()
    if not key:
        return None
    best, best_score, errors = None, 0, []
    best_with_phone, best_phone_score = None, 0   # for phone merging below

    def _consider(c: dict, score: int, extra: dict) -> None:
        nonlocal best, best_score, best_with_phone, best_phone_score
        if score <= 0:
            return
        rec = dict(c)
        rec.update(extra)
        if score > best_score:
            best, best_score = rec, score
        if rec.get("phone") and score > best_phone_score:
            best_with_phone, best_phone_score = rec, score

    # 1) verified Firestore contacts — searched across EVERY signed-in account
    if is_signed_in():
        for acc in _accounts_full():
            try:
                for c in _contacts_for_account(acc):
                    s = _contact_score(c, key)
                    extra = {"source": "verified",
                             "verified": bool(c.get("verified"))}
                    if acc.get("firebase_email"):
                        extra["account"] = acc["firebase_email"]
                    _consider(c, s, extra)
            except Exception as e:
                errors.append(e)

    # 2) Google People API — every account's real mobile/Google contacts
    if is_signed_in():
        for acc in _accounts_full():
            try:
                for c in _search_people_for(acc, key):
                    s = _contact_score(c, key)
                    extra = {"source": "google", "verified": False}
                    if acc.get("firebase_email"):
                        extra["account"] = acc["firebase_email"]
                    _consider(c, s, extra)
            except Exception as e:
                errors.append(e)

    # 3) local Windows Contacts vCards (works even without sign-in)
    for c in _local_vcard_contacts():
        s = _contact_score(c, key)
        _consider(c, s, {"source": "local", "verified": False})

    if best:
        # Only merge contact details from a DIFFERENT record when it is the
        # same person (equal/whole-word-subset name) — never a partial-token
        # match from an unrelated contact.
        if (not best.get("phone") and best_with_phone
                and _same_person(best, best_with_phone)):
            best["phone"] = best_with_phone.get("phone", "")
            if not best.get("email"):
                best["email"] = best_with_phone.get("email", "")
        return best
    if errors:
        raise RuntimeError(f"could not check contacts right now: {str(errors[0])[:120]}")
    return None


def find_contact_display(query: str) -> str:
    """Human-readable result of resolving a name to a real contact."""
    try:
        c = find_contact(query)
    except Exception as e:
        return f"Could not check contacts right now: {str(e)[:150]}"
    if c is None:
        return (
            f"'{query}' was not found in your Google/phone contacts or "
            "verified contacts."
        )
    name  = c.get("name") or query
    bits  = [f"Found {name}"]
    if c.get("phone"):
        bits.append(f"phone {c['phone']}")
    if c.get("email"):
        bits.append(f"email {c['email']}")
    src = c.get("source", "")
    if c.get("verified"):
        bits.append("confirmed via Google")
    elif src:
        bits.append(f"from {src} contacts")
    return " ".join(b for b in bits if b) + "."


# -- Gmail API (read the user's emails) -------------------------------------

def list_emails(query: str = "", max_results: int = 8) -> list[dict]:
    """List the user's recent Gmail messages (metadata only).

    Returns [{id, from, subject, date, snippet}]. Requires Gmail API enabled
    in the Cloud Console and the gmail.readonly scope approved at sign-in.
    Raises on network/API errors so callers report honestly."""
    q = (query or "").strip()
    r = requests.get(
        f"{GMAIL_API}/users/me/messages",
        params={
            "q":         q,
            "maxResults": str(max(1, min(int(max_results), 20))),
        },
        headers={"Authorization": f"Bearer {_google_access_token()}"},
        timeout=30,
    )
    r.raise_for_status()
    ids = [m.get("id", "") for m in (r.json().get("messages") or []) if m.get("id")]
    if not ids:
        return []
    # One batched metadata fetch for all ids (max 100 ids per request).
    # ids / metadataHeaders are REPEATED query params per Gmail docs.
    meta = requests.get(
        f"{GMAIL_API}/users/me/messages/batchGet",
        params={
            "ids":             ids,
            "format":          "metadata",
            "metadataHeaders": ["From", "Subject", "Date"],
        },
        headers={"Authorization": f"Bearer {_google_access_token()}"},
        timeout=30,
    )
    meta.raise_for_status()
    out = []
    for item in (meta.json().get("messages") or []):
        payload = item.get("payload", {})
        hdrs = {h.get("name", "").lower(): h.get("value", "")
                for h in (payload.get("headers") or [])}
        out.append({
            "id":      item.get("id", ""),
            "from":    hdrs.get("from", ""),
            "subject": hdrs.get("subject", "(no subject)"),
            "date":    hdrs.get("date", ""),
            "snippet": (item.get("snippet") or "")[:200],
        })
    return out


def _extract_body(payload: dict) -> str:
    """Walk a Gmail payload tree and return the best plain-text body.
    Falls back to text/html (tags stripped) so HTML-only emails still read."""
    import base64 as _b64
    import re as _re
    parts = payload.get("parts") or []
    if parts:
        for p in parts:
            body = _extract_body(p)
            if body.strip():
                return body
    mime = (payload.get("mimeType") or "")
    data = (payload.get("body") or {}).get("data", "")
    if not data:
        return ""
    try:
        raw = _b64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    except Exception:
        return ""
    if mime == "text/plain":
        return raw
    if mime == "text/html":
        raw = _re.sub(r"<br\s*/?>\s*", "\n", raw)
        raw = _re.sub(r"<[^>]+>", " ", raw)
        raw = _re.sub(r"\s+", " ", raw)
        return raw.strip()
    return ""


def read_email(email_id: str) -> dict:
    """Fetch one Gmail message with its full text body."""
    eid = (email_id or "").strip()
    if not eid:
        raise ValueError("No email id provided.")
    r = requests.get(
        f"{GMAIL_API}/users/me/messages/{eid}",
        params={"format": "full"},
        headers={"Authorization": f"Bearer {_google_access_token()}"},
        timeout=30,
    )
    r.raise_for_status()
    m       = r.json()
    payload = m.get("payload", {})
    hdrs    = {h.get("name", "").lower(): h.get("value", "")
               for h in (payload.get("headers") or [])}
    return {
        "id":      m.get("id", eid),
        "from":    hdrs.get("from", ""),
        "to":      hdrs.get("to", ""),
        "subject": hdrs.get("subject", "(no subject)"),
        "date":    hdrs.get("date", ""),
        "body":    _extract_body(payload)[:4000],
    }


def _gmail_hint_from_text(text: str, note: str = "") -> str:
    """Actionable message when the Gmail API itself is disabled.

    The Gmail API being "not enabled" (403 accessNotConfigured) is a one-time
    Google Cloud console switch, separate from the OAuth scopes. Returns ""
    for every other failure so callers keep their generic text. `note` is an
    optional trailing clause (e.g. "contacts still work") that callers can
    customise per context."""
    text = text or ""
    if "accessNotConfigured" in text or "has not been used in project" in text:
        m = re.search(r"project (\d+)", text)
        url = GMAIL_ENABLE_URL
        if m:
            url += f"?project={m.group(1)}"
        return (
            "The Gmail API is disabled in your Google Cloud project"
            + (f" ({m.group(1)})" if m else "")
            + ". Enable it once at " + url + " then try again"
            + ((" — " + note) if note else "")
            + "."
        )
    return ""


def _gmail_api_hint(exc: Exception, note: str = "") -> str:
    """Same as _gmail_hint_from_text but unwraps a requests exception's
    response text (403 accessNotConfigured bodies live on .response)."""
    resp = getattr(exc, "response", None)
    if resp is None:
        return ""
    return _gmail_hint_from_text(getattr(resp, "text", ""), note)


def list_emails_display(query: str = "", max_results: int = 8) -> str:
    if not is_signed_in():
        return "Not signed in with Google. Say 'sign in with Google' first."
    try:
        emails = list_emails(query, max_results)
    except Exception as e:
        hint = _gmail_api_hint(e, "contacts and verified contact lookup still work")
        base = f"Could not check email right now: {str(e)[:150]}."
        if hint:
            return base + " " + hint
        return base + " Make sure the Gmail API is enabled (FIREBASE_SETUP.md)."
    if not emails:
        return "No emails found." + (f" (query: {query})" if query else "")
    lines = [f"Recent emails ({len(emails)}):"]
    for i, e in enumerate(emails, 1):
        lines.append(f"  {i}. [{e['id']}] {e['subject']} — {e['from']}")
    lines.append("Say 'read email <number or id>' to open one.")
    return "\n".join(lines)


def read_email_display(email_id: str) -> str:
    if not is_signed_in():
        return "Not signed in with Google. Say 'sign in with Google' first."
    try:
        e = read_email(email_id)
    except Exception as ex:
        hint = _gmail_api_hint(ex)
        msg = f"Could not read email right now: {str(ex)[:150]}"
        return (msg + " " + hint) if hint else msg
    return (
        f"From: {e['from']}\n"
        f"Subject: {e['subject']}\n"
        f"Date: {e['date']}\n\n"
        f"{e['body']}"
    )


# -- Gmail SEND (choose the FROM account) ---------------------------------

def _resolve_send_account(key) -> dict:
    """Resolve which account an email is sent FROM.

    - key empty/None   → the ACTIVE account
    - key given        → matched by number / email / display-name fragment
    Returns the account dict. Raises RuntimeError when nothing matches."""
    cfg = _load_cfg()
    _ensure_accounts(cfg)
    accts = cfg.get("google_accounts") or []
    if not accts:
        raise RuntimeError(
            "No Google account signed in — say 'sign in with Google' first."
        )
    if key is None or not str(key).strip():
        _idx, acc = _resolve_active(cfg)
        return acc
    idx = _find_account_index(key)
    if idx is None:
        emails = ", ".join(a.get("firebase_email", "?") for a in accts)
        raise RuntimeError(
            f"No signed-in Google account matches '{key}'. "
            f"Signed-in accounts: {emails}"
        )
    return accts[idx]


def send_email(to: str, subject: str, body: str = "",
               from_account: str | None = None) -> dict:
    """Send an email through the user's Gmail via the Gmail API.

    `from_account` picks WHICH signed-in account sends it (email / number /
    name fragment); empty uses the ACTIVE account. The recipient `to` can be
    a raw email address or a contact NAME — a name is resolved to the real
    email via find_contact (which searches all signed-in accounts).

    Requires the gmail.send scope approved at sign-in (new sign-ins get it
    automatically; accounts signed in before this feature must re-sign-in).

    Returns {ok, id, from, to} or {ok: False, error}."""
    if not is_signed_in():
        return {"ok": False, "error": "Not signed in with Google. Say 'sign in with Google' first."}

    to = (to or "").strip()
    subject = (subject or "").strip()
    if not to or not subject:
        return {"ok": False, "error": "Recipient and subject are required."}

    # Resolve a NAME to a real email address (all accounts searched).
    if "@" not in to:
        try:
            c = find_contact(to)
        except Exception:
            c = None
        if c is not None and c.get("email"):
            to = c["email"]

    try:
        acc = _resolve_send_account(from_account)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    from_email = acc.get("firebase_email", "") or "your Gmail"
    token = _google_access_token(acc)

    import base64 as _b64
    import email.message as _em
    msg = _em.EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    if from_email and from_email != "your Gmail":
        msg["From"] = from_email
    msg.set_content((body or "").strip() or " ")
    raw = _b64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

    r = requests.post(
        f"{GMAIL_API}/users/me/messages/send",
        json={"raw": raw},
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        timeout=30,
    )
    if r.status_code >= 400:
        # The Gmail API being disabled is a console switch, not a scope issue —
        # report it with the exact enable link so the user can fix it once.
        hint = _gmail_hint_from_text(r.text)
        if hint:
            return {"ok": False, "error": hint}
        if r.status_code == 403 and "scope" in (r.text or "").lower():
            return {"ok": False,
                    "error": ("Gmail send permission is missing for this account. "
                               "Sign out and sign back in with Google — the new "
                               "sign-in includes the send permission.")}
        return {"ok": False,
                "error": f"Gmail send failed (HTTP {r.status_code}): {(r.text or '')[:200]}"}
    data = r.json()
    return {"ok": True, "id": data.get("id", ""),
            "from": from_email, "to": to}


def send_email_display(to: str, subject: str, body: str = "",
                       from_account: str | None = None) -> str:
    """Human-readable result of send_email — never raises."""
    if not is_signed_in():
        return "Not signed in with Google. Say 'sign in with Google' first."
    try:
        res = send_email(to, subject, body, from_account)
    except Exception as ex:
        return f"Could not send email right now: {str(ex)[:200]}"
    if not res.get("ok"):
        return res.get("error", "Could not send email.")
    return (f"Email sent from {res['from']} to {res['to']} "
            f"(subject: {subject}).")