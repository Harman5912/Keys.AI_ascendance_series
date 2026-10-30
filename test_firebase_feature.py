"""Offscreen unit tests for the Google-verified-contacts feature.

Run: python test_firebase_feature.py
Covers: firebase_client sign-in/refresh/CRUD, send_message gate,
google_account dispatch. All network calls are mocked.
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import firebase_client as fb
import actions.send_message as sm
import actions.google_account as ga


class _FakeResp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code = status
        self._data = data if data is not None else {}
        self.text = text or json.dumps(self._data)

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text}")


class _FakeStore:
    """In-memory fake for Firestore documents."""

    def __init__(self):
        self.docs = {}   # doc_id -> fields(dict)

    def handle(self, method, path, body=None):
        # path like /users/uid/contacts (collection, 3 parts)
        # or /users/uid/contacts/{doc} (document, 4 parts)
        parts = [p for p in path.split("/") if p]
        if len(parts) == 3:  # collection
            if method == "GET":
                return _FakeResp(200, {"documents": [
                    {"fields": fb._encode_fields(f)} for f in self.docs.values()
                ]})
            return _FakeResp(400, {"error": "bad"})
        if len(parts) != 4:  # document path expected
            return _FakeResp(400, {"error": f"bad path: {path}"})
        doc = parts[3]
        if method == "PATCH":
            merged = dict(self.docs.get(doc, {}))
            for k, v in body["fields"].items():
                merged[k] = fb._decode_fields({k: v})[k]
            self.docs[doc] = merged
            return _FakeResp(200, {"fields": body["fields"]})
        if method == "DELETE":
            self.docs.pop(doc, None)
            return _FakeResp(200, {})
        if method == "GET":
            if doc not in self.docs:
                return _FakeResp(404, {"error": "not found"})
            return _FakeResp(200, {"fields": fb._encode_fields(self.docs[doc])})
        return _FakeResp(400, {"error": "bad"})


class FirebaseClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg_path = Path(self.tmp) / "api_keys.json"
        fb._CONFIG_PATH = self.cfg_path
        self.store = _FakeStore()
        # A configured, signed-in baseline config
        fb._save_cfg({
            "google_oauth_client_id": "client-id.apps.googleusercontent.com",
            "google_oauth_client_secret": "GOCSPX-secret",
            "firebase_api_key": "AIza-test",
            "firebase_project_id": "test-proj",
            "firebase_refresh_token": "refresh-tok",
            "firebase_id_token": "id-tok",
            "firebase_id_token_expires": str(int(time.time()) + 3600),
            "firebase_uid": "uid123",
            "firebase_email": "me@gmail.com",
            "firebase_display_name": "Me",
        })

    def test_status_not_configured(self):
        fb._clear_cfg("google_oauth_client_id", "google_oauth_client_secret",
                      "firebase_api_key", "firebase_project_id")
        self.assertIn("not configured", fb.status())
        self.assertFalse(fb.is_configured())

    def test_status_signed_in(self):
        self.assertIn("Signed in as Me", fb.status())
        self.assertTrue(fb.is_signed_in())

    def test_doc_id_and_encoding(self):
        self.assertEqual(fb._doc_id("Papa Doe"), "papa_doe")
        enc = fb._encode_fields({"verified": True, "name": "Papa"})
        self.assertEqual(enc["verified"], {"booleanValue": True})
        self.assertEqual(enc["name"], {"stringValue": "Papa"})
        dec = fb._decode_fields(enc)
        self.assertTrue(dec["verified"])
        self.assertEqual(dec["name"], "Papa")

    def test_sign_in_full_flow(self):
        """Browser 'approves' via a simulated redirect; tokens minted."""
        captured = {}

        def fake_post(url, **kw):
            if "oauth2.googleapis.com/token" in url:
                captured["exchanged"] = True
                return _FakeResp(200, {
                    "id_token": "google-id-token",
                    "access_token": "google-access",
                    "refresh_token": "google-refresh",
                })
            if "identitytoolkit.googleapis.com/v1/accounts:signInWithIdp" in url:
                captured["firebase"] = True
                return _FakeResp(200, {
                    "idToken": "firebase-id-token",
                    "refreshToken": "firebase-refresh",
                    "localId": "uid-new",
                    "email": "user@gmail.com",
                    "displayName": "User",
                    "expiresIn": "3600",
                })
            raise AssertionError(f"unexpected url: {url}")

        def fake_open(url):
            # Simulate the user's browser redirecting with ?code=APPROVED
            def _cb():
                time.sleep(0.15)
                fb._CallbackHandler.code = "APPROVED"
            threading.Thread(target=_cb, daemon=True).start()

        with mock.patch.object(fb.requests, "post", side_effect=fake_post), \
             mock.patch.object(fb.webbrowser, "open", side_effect=fake_open):
            result = fb.sign_in(timeout=10)

        self.assertIn("Signed in with Google as User", result)
        self.assertTrue(captured.get("exchanged"))
        self.assertTrue(captured.get("firebase"))
        cfg = fb._load_cfg()
        # sign-in now stores the account in google_accounts[] (multi-account)
        _idx, acc = fb._resolve_active(cfg)   # the NEWLY signed-in account is active
        self.assertEqual(acc["firebase_refresh_token"], "firebase-refresh")
        self.assertEqual(acc["firebase_uid"], "uid-new")
        self.assertEqual(acc["firebase_email"], "user@gmail.com")
        self.assertEqual(cfg["active_google_account"], "user@gmail.com")
        # the legacy setUp flat keys are gone — no legacy firebase_refresh_token
        self.assertNotIn("firebase_refresh_token", cfg)

    def test_sign_in_not_configured(self):
        fb._clear_cfg("google_oauth_client_id", "google_oauth_client_secret",
                      "firebase_api_key")
        self.assertIn("not configured", fb.sign_in(timeout=0.2))

    def test_sign_in_denied_returns_promptly(self):
        """?error= (user denied) must return immediately, not wait the timeout."""
        def fake_open(url):
            def _cb():
                time.sleep(0.15)
                fb._CallbackHandler.error = "access_denied"
            threading.Thread(target=_cb, daemon=True).start()

        with mock.patch.object(fb.webbrowser, "open", side_effect=fake_open):
            started = time.time()
            result = fb.sign_in(timeout=10)
            elapsed = time.time() - started
        self.assertIn("denied/closed", result)
        self.assertLess(elapsed, 5.0)   # returns promptly, not the full 10s

    def test_token_refresh_when_expired(self):
        # seed an account with an expired id token (active account)
        fb._store_account({"firebase_email": "user@gmail.com",
                           "firebase_refresh_token": "refresh",
                           "firebase_id_token": "stale",
                           "firebase_id_token_expires": "0"})
        with mock.patch.object(fb.requests, "post", return_value=_FakeResp(200, {
            "access_token": "fresh-token", "expires_in": "3600",
        })):
            tok = fb._get_id_token()
        self.assertEqual(tok, "fresh-token")
        self.assertEqual(fb._active_account_cfg()["firebase_id_token"],
                         "fresh-token")

    def test_add_list_verify_confirm_remove(self):
        with mock.patch.object(fb, "_fs", side_effect=self.store.handle):
            r = fb.add_contact("Papa", "papa@gmail.com", "+123", "whatsapp")
            self.assertIn("added", r)
            self.assertEqual(fb.verify_contact("Papa")["google_email"], "papa@gmail.com")
            self.assertFalse(fb.verify_contact("Papa")["verified"])
            r = fb.confirm_contact("Papa")
            self.assertIn("confirmed", r)
            self.assertTrue(fb.verify_contact("Papa")["verified"])
            disp = fb.list_contacts_display()
            self.assertIn("Papa", disp)
            self.assertIn("\u2713", disp)
            r = fb.remove_contact("Papa")
            self.assertIn("Removed", r)
            self.assertIsNone(fb.verify_contact("Papa"))

    def test_list_contacts_server_error_raises(self):
        def bad_fs(method, path, body=None):
            return _FakeResp(500, {"error": "boom"}, text="boom")
        with mock.patch.object(fb, "_fs", side_effect=bad_fs):
            with self.assertRaises(RuntimeError):
                fb.list_contacts()

    def test_list_contacts_404_is_empty(self):
        def notfound_fs(method, path, body=None):
            return _FakeResp(404, {"error": "missing"})
        with mock.patch.object(fb, "_fs", side_effect=notfound_fs):
            self.assertEqual(fb.list_contacts(), [])

    def test_not_signed_in_gate_messages(self):
        fb._clear_cfg("firebase_refresh_token", "firebase_uid", "firebase_id_token")
        self.assertIsNone(fb.verify_contact("Papa"))
        self.assertIn("Not signed in", fb.list_contacts_display())


class SendMessageGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        fb._CONFIG_PATH = Path(self.tmp) / "api_keys.json"
        self.store = _FakeStore()

    def _sign_in_config(self):
        fb._save_cfg({
            "google_oauth_client_id": "cid.apps.googleusercontent.com",
            "google_oauth_client_secret": "GOCSPX-secret",
            "firebase_api_key": "AIza-test", "firebase_project_id": "p",
            "firebase_refresh_token": "r", "firebase_uid": "u",
            "firebase_id_token": "t",
            "firebase_id_token_expires": str(int(time.time()) + 3600),
        })

    def test_gate_off_no_lookup(self):
        self._sign_in_config()
        with mock.patch.object(fb, "_fs", side_effect=self.store.handle) as fs_mock:
            blocked, note = sm._verified_contact_note("Papa", require_verified=False)
        fs_mock.assert_not_called()
        self.assertEqual(blocked, "")
        self.assertEqual(note, "")

    def test_gate_requires_config(self):
        blocked, _ = sm._verified_contact_note("Papa", require_verified=True)
        self.assertIn("FIREBASE_SETUP.md", blocked)

    def test_gate_requires_sign_in(self):
        self._sign_in_config()
        fb._clear_cfg("firebase_refresh_token", "firebase_uid", "firebase_id_token")
        blocked, _ = sm._verified_contact_note("Papa", require_verified=True)
        self.assertIn("sign in with Google", blocked)

    def test_gate_blocks_unverified_contact(self):
        self._sign_in_config()
        self.store.docs["papa"] = {"name": "Papa", "google_email": "a@gmail.com",
                                   "verified": False}
        with mock.patch.object(fb, "_fs", side_effect=self.store.handle):
            blocked, _ = sm._verified_contact_note("Papa", require_verified=True)
        self.assertIn("NOT confirmed", blocked)

    def test_gate_blocks_unknown_contact(self):
        self._sign_in_config()
        with mock.patch.object(fb, "_fs", side_effect=self.store.handle):
            blocked, _ = sm._verified_contact_note("Nobody", require_verified=True)
        self.assertIn("NOT in your verified contacts", blocked)

    def test_gate_allows_verified_contact(self):
        self._sign_in_config()
        self.store.docs["papa"] = {"name": "Papa", "google_email": "a@gmail.com",
                                   "verified": True}
        with mock.patch.object(fb, "_fs", side_effect=self.store.handle):
            blocked, note = sm._verified_contact_note("Papa", require_verified=True)
        self.assertEqual(blocked, "")
        self.assertIn("verified Google contact: a@gmail.com", note)

    def test_gate_honest_network_error(self):
        self._sign_in_config()
        def bad_fs(method, path, body=None):
            raise RuntimeError("network down")
        with mock.patch.object(fb, "_fs", side_effect=bad_fs):
            blocked, _ = sm._verified_contact_note("Papa", require_verified=True)
        self.assertIn("Could not verify contact", blocked)


class PeopleContactLookupTests(unittest.TestCase):
    """Real mobile-contact resolution: People API, local vCards, find_contact."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        fb._CONFIG_PATH = Path(self.tmp) / "api_keys.json"
        self.store = _FakeStore()

    def _sign_in_full(self):
        """Signed in with BOTH Firebase + Google tokens (so People API works)."""
        fb._save_cfg({
            "google_oauth_client_id": "cid.apps.googleusercontent.com",
            "google_oauth_client_secret": "GOCSPX-secret",
            "firebase_api_key": "AIza-test", "firebase_project_id": "p",
            "firebase_refresh_token": "r", "firebase_uid": "u",
            "firebase_id_token": "t",
            "firebase_id_token_expires": str(int(time.time()) + 3600),
            "google_access_token": "ga-tok",
            "google_access_expires": str(int(time.time()) + 3600),
            "google_refresh_token": "g-refresh",
        })

    def test_search_google_contacts(self):
        self._sign_in_full()
        fake = _FakeResp(200, {"results": [
            {"person": {
                "names":         [{"displayName": "Papa Smith"}],
                "phoneNumbers":  [{"value": "+1 555 123 4567"}],
                "emailAddresses": [{"value": "papa@gmail.com"}],
            }},
        ]})
        with mock.patch.object(fb.requests, "get", return_value=fake) as m:
            res = fb.search_google_contacts("Papa")
        self.assertEqual(res[0]["name"], "Papa Smith")
        self.assertEqual(res[0]["phone"], "+1 555 123 4567")
        self.assertEqual(res[0]["source"], "google")
        self.assertIn("people:searchContacts", m.call_args.args[0])
        self.assertEqual(m.call_args.kwargs["params"]["readMask"],
                         "names,emailAddresses,phoneNumbers")
        self.assertEqual(m.call_args.kwargs["headers"]["Authorization"],
                         "Bearer ga-tok")

    def test_google_token_refresh_when_expired(self):
        self._sign_in_full()
        fb._save_active_account({"google_access_token": "stale",
                                 "google_access_expires": "0"})
        with mock.patch.object(fb.requests, "post", return_value=_FakeResp(200, {
            "access_token": "fresh-google", "expires_in": "3600",
        })):
            tok = fb._google_access_token()
        self.assertEqual(tok, "fresh-google")
        self.assertEqual(fb._active_account_cfg()["google_access_token"],
                         "fresh-google")

    def test_local_vcard_fallback(self):
        home = Path(self.tmp) / "home"
        (home / "Contacts").mkdir(parents=True)
        (home / "Contacts" / "papa.vcf").write_text(
            "BEGIN:VCARD\nFN:Papa Smith\nTEL:+15551234567\nEMAIL:papa@gmail.com\nEND:VCARD",
            encoding="utf-8")
        with mock.patch.object(fb.Path, "home", return_value=home):
            res = fb._local_vcard_contacts()
        self.assertEqual(res[0]["name"], "Papa Smith")
        self.assertEqual(res[0]["phone"], "+15551234567")
        self.assertEqual(res[0]["source"], "local")

    def test_find_contact_prefers_verified(self):
        """Verified Firestore contact beats a Google contact match."""
        self._sign_in_full()
        self.store.docs["papa"] = {"name": "Papa", "google_email": "papa@gmail.com",
                                   "phone": "+111", "verified": True}
        fake = _FakeResp(200, {"results": [
            {"person": {"names": [{"displayName": "Papa Smith"}],
                        "phoneNumbers": [{"value": "+999"}],
                        "emailAddresses": []}},
        ]})
        with mock.patch.object(fb, "_contacts_for_account",
                               side_effect=lambda acc: [dict(v) for v in self.store.docs.values()]), \
             mock.patch.object(fb.requests, "get", return_value=fake), \
             mock.patch.object(fb.Path, "home", return_value=Path(self.tmp) / "nohome"):
            c = fb.find_contact("Papa")
        self.assertEqual(c["source"], "verified")
        self.assertTrue(c["verified"])
        self.assertEqual(c["phone"], "+111")

    def test_find_contact_falls_back_to_google(self):
        """Not in verified contacts → the real Google/mobile contact is used."""
        self._sign_in_full()
        fake = _FakeResp(200, {"results": [
            {"person": {"names": [{"displayName": "Papa Smith"}],
                        "phoneNumbers": [{"value": "+999 555 0100"}],
                        "emailAddresses": []}},
        ]})
        with mock.patch.object(fb, "_contacts_for_account",
                               side_effect=lambda acc: [dict(v) for v in self.store.docs.values()]), \
             mock.patch.object(fb.requests, "get", return_value=fake), \
             mock.patch.object(fb.Path, "home", return_value=Path(self.tmp) / "nohome2"):
            c = fb.find_contact("Papa")
        self.assertEqual(c["source"], "google")
        self.assertEqual(c["phone"], "+999 555 0100")
        self.assertFalse(c["verified"])

    def test_find_contact_local_only_when_signed_out(self):
        """No sign-in → only local Windows Contacts vCards are searched."""
        fb._clear_cfg("firebase_refresh_token", "firebase_uid", "firebase_id_token",
                      "google_access_token", "google_access_expires", "google_refresh_token")
        home = Path(self.tmp) / "home3"
        (home / "Contacts").mkdir(parents=True)
        (home / "Contacts" / "papa.vcf").write_text("FN:Papa Smith\nTEL:+1555\n",
                                                     encoding="utf-8")
        with mock.patch.object(fb.Path, "home", return_value=home):
            c = fb.find_contact("Papa")
        self.assertEqual(c["source"], "local")
        self.assertEqual(c["phone"], "+1555")

    def test_find_contact_raises_honestly_on_network_error(self):
        """No match AND a network error → raise, never claim 'not in contacts'."""
        self._sign_in_full()
        def bad_get(*a, **kw):
            raise RuntimeError("network down")
        with mock.patch.object(fb, "_contacts_for_account",
                               side_effect=lambda acc: [dict(v) for v in self.store.docs.values()]), \
             mock.patch.object(fb.requests, "get", side_effect=bad_get), \
             mock.patch.object(fb.Path, "home", return_value=Path(self.tmp) / "nohome4"):
            with self.assertRaises(RuntimeError):
                fb.find_contact("Nobody")

    def test_find_contact_display(self):
        self._sign_in_full()
        self.store.docs["papa"] = {"name": "Papa", "google_email": "papa@gmail.com",
                                   "phone": "+111", "verified": True}
        with mock.patch.object(fb, "_contacts_for_account",
                               side_effect=lambda acc: [dict(v) for v in self.store.docs.values()]), \
             mock.patch.object(fb.requests, "get", return_value=_FakeResp(200, {"results": []})), \
             mock.patch.object(fb.Path, "home", return_value=Path(self.tmp) / "nohome5"):
            disp = fb.find_contact_display("Papa")
        self.assertIn("Papa", disp)
        self.assertIn("confirmed via Google", disp)

    def test_resolve_receiver_uses_phone_for_whatsapp(self):
        """send_message resolves a spoken name to the real phone number."""
        self._sign_in_full()
        self.store.docs["papa"] = {"name": "Papa", "google_email": "a@gmail.com",
                                   "phone": "+15551234567", "verified": True}
        with mock.patch.object(fb, "_contacts_for_account",
                               side_effect=lambda acc: [dict(v) for v in self.store.docs.values()]), \
             mock.patch.object(fb.requests, "get", return_value=_FakeResp(200, {"results": []})), \
             mock.patch.object(fb.Path, "home", return_value=Path(self.tmp) / "nohome6"):
            target, note = sm._resolve_receiver("Papa", "whatsapp")
        self.assertEqual(target, "+15551234567")
        self.assertIn("matched contact Papa", note)

    def test_resolve_receiver_uses_name_for_instagram(self):
        """Instagram/Messenger search by NAME or @username — never phone/email."""
        self._sign_in_full()
        self.store.docs["papa"] = {"name": "Papa", "google_email": "a@gmail.com",
                                   "phone": "+15551234567", "verified": True}
        with mock.patch.object(fb, "_fs", side_effect=self.store.handle), \
             mock.patch.object(fb.requests, "get", return_value=_FakeResp(200, {"results": []})), \
             mock.patch.object(fb.Path, "home", return_value=Path(self.tmp) / "nohome7"):
            target, note = sm._resolve_receiver("Papa", "instagram")
        self.assertEqual(target, "Papa")

    def test_resolve_receiver_keeps_explicit_email_for_instagram(self):
        """An explicit email/@handle the user gave is kept for Instagram."""
        self._sign_in_full()
        self.store.docs["papa"] = {"name": "Papa", "google_email": "a@gmail.com",
                                   "phone": "+15551234567", "verified": True}
        with mock.patch.object(fb, "_fs", side_effect=self.store.handle), \
             mock.patch.object(fb.requests, "get", return_value=_FakeResp(200, {"results": []})), \
             mock.patch.object(fb.Path, "home", return_value=Path(self.tmp) / "nohome8"):
            target, note = sm._resolve_receiver("@papa_cool", "instagram")
        self.assertEqual(target, "@papa_cool")

    def test_find_contact_merges_phone_from_google(self):
        """Verified record without a phone picks up the real number from Google
        when it is the same person (whole-word subset name)."""
        self._sign_in_full()
        self.store.docs["papa"] = {"name": "Papa", "google_email": "papa@gmail.com",
                                   "phone": "", "verified": True}
        fake = _FakeResp(200, {"results": [
            {"person": {"names": [{"displayName": "Papa Smith"}],
                        "phoneNumbers": [{"value": "+999 555 0100"}],
                        "emailAddresses": []}},
        ]})
        with mock.patch.object(fb, "_contacts_for_account",
                               side_effect=lambda acc: [dict(v) for v in self.store.docs.values()]), \
             mock.patch.object(fb.requests, "get", return_value=fake), \
             mock.patch.object(fb.Path, "home", return_value=Path(self.tmp) / "nohome9"):
            c = fb.find_contact("Papa")
        self.assertEqual(c["source"], "verified")
        self.assertEqual(c["phone"], "+999 555 0100")

    def test_find_contact_never_merges_wrong_person(self):
        """Partial-token match ('Papa' vs 'Papadopoulos') must NOT pull in
        a different person's phone number."""
        self._sign_in_full()
        self.store.docs["papa"] = {"name": "Papa", "google_email": "papa@gmail.com",
                                   "phone": "", "verified": True}
        fake = _FakeResp(200, {"results": [
            {"person": {"names": [{"displayName": "Papadopoulos"}],
                        "phoneNumbers": [{"value": "+777 555 0100"}],
                        "emailAddresses": []}},
        ]})
        with mock.patch.object(fb, "_contacts_for_account",
                               side_effect=lambda acc: [dict(v) for v in self.store.docs.values()]), \
             mock.patch.object(fb.requests, "get", return_value=fake), \
             mock.patch.object(fb.Path, "home", return_value=Path(self.tmp) / "nohome10"):
            c = fb.find_contact("Papa")
        self.assertEqual(c["source"], "verified")
        self.assertEqual(c.get("phone"), "")   # wrong person's number NOT merged
        self.assertNotIn("+777", c.get("phone", ""))


class GmailTests(unittest.TestCase):
    """list_emails / read_email via the Gmail API (mocked)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        fb._CONFIG_PATH = Path(self.tmp) / "api_keys.json"
        fb._save_cfg({
            "firebase_refresh_token": "refresh-tok",
            "firebase_id_token": "id-tok",
            "firebase_id_token_expires": str(int(time.time()) + 3600),
            "firebase_uid": "uid123",
            "google_refresh_token": "google-rt",
            "google_access_token": "gatok",
            "google_access_expires": str(int(time.time()) + 3600),
            "google_oauth_client_id": "c",
            "google_oauth_client_secret": "s",
        })

    def test_list_emails_parses_batch_metadata(self):
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            if url.endswith("/users/me/messages"):
                return _FakeResp(200, {"messages": [{"id": "m1"}, {"id": "m2"}]})
            return _FakeResp(200, {"messages": [
                {"id": "m1", "payload": {"headers": [
                    {"name": "From", "value": "boss@x.com"},
                    {"name": "Subject", "value": "Q3 report"},
                    {"name": "Date", "value": "Tue, 1 Aug 2026"},
                ]}, "snippet": "Please review..."},
                {"id": "m2", "payload": {"headers": [
                    {"name": "From", "value": "news@y.com"},
                    {"name": "Subject", "value": "Hello"},
                ]}, "snippet": "Welcome"},
            ]})

        with mock.patch.object(fb.requests, "get", side_effect=fake_get):
            emails = fb.list_emails("from:boss", 5)
        self.assertEqual(len(emails), 2)
        self.assertEqual(emails[0]["subject"], "Q3 report")
        self.assertEqual(emails[0]["from"], "boss@x.com")
        self.assertTrue(any("batchGet" in c for c in calls))

    def test_read_email_extracts_body(self):
        import base64
        body = base64.urlsafe_b64encode(b"Hi Papa, the deal is done.").decode()

        def fake_get(url, **kw):
            return _FakeResp(200, {
                "id": "m1",
                "payload": {
                    "mimeType": "multipart/alternative",
                    "headers": [
                        {"name": "From", "value": "boss@x.com"},
                        {"name": "To", "value": "me@gmail.com"},
                        {"name": "Subject", "value": "Deal"},
                        {"name": "Date", "value": "Tue, 1 Aug 2026"},
                    ],
                    "parts": [{"mimeType": "text/plain", "body": {"data": body}}],
                },
            })

        with mock.patch.object(fb.requests, "get", side_effect=fake_get):
            e = fb.read_email("m1")
        self.assertEqual(e["subject"], "Deal")
        self.assertIn("deal is done", e["body"])

    def test_list_emails_display_requires_signin(self):
        fb._clear_cfg("firebase_refresh_token", "firebase_uid")
        self.assertIn("Not signed in", fb.list_emails_display())

    def test_gmail_api_disabled_hint_text(self):
        """A 403 accessNotConfigured body must produce the exact enable link."""
        hint = fb._gmail_hint_from_text(
            '{"error": {"message": "Gmail API has not been used in project '
            '391390301019 before or it is disabled. Enable it by visiting '
            'https://console.developers.google.com/apis/api/gmail.googleapis.com/'
            'overview?project=391390301019 then retry.", "reason": "accessNotConfigured"}}'
        )
        self.assertIn("Gmail API is disabled", hint)
        self.assertIn("391390301019", hint)
        self.assertIn("console.developers.google.com/apis/api/gmail.googleapis.com", hint)

    def test_gmail_api_disabled_hint_empty_for_other_errors(self):
        self.assertEqual(fb._gmail_hint_from_text("boom"), "")
        self.assertEqual(fb._gmail_hint_from_text(""), "")

    def test_gmail_api_hint_unwraps_response_text(self):
        class _Resp:
            text = '{"error": {"reason": "accessNotConfigured"}}'
        err = RuntimeError("403 Client Error")
        err.response = _Resp()
        self.assertIn("Gmail API is disabled", fb._gmail_api_hint(err))

    def test_list_emails_display_surfaces_enable_link(self):
        """When Gmail API is disabled, the display path must name the fix,
        not a bare 403."""
        class _Resp:
            text = ('{"error": {"message": "Gmail API has not been used in '
                    'project 123 before or it is disabled.", '
                    '"reason": "accessNotConfigured"}}')
        err = RuntimeError("403 Client Error: Forbidden")
        err.response = _Resp()
        with mock.patch.object(fb, "list_emails", side_effect=err):
            out = fb.list_emails_display("", 5)
        self.assertIn("Gmail API is disabled", out)
        self.assertIn("console.developers.google.com", out)
        self.assertIn("123", out)

    def test_read_email_display_surfaces_enable_link(self):
        class _Resp:
            text = ('{"error": {"message": "Gmail API has not been used in '
                    'project 123 before.", "reason": "accessNotConfigured"}}')
        err = RuntimeError("403 Client Error: Forbidden")
        err.response = _Resp()
        with mock.patch.object(fb, "read_email", side_effect=err):
            out = fb.read_email_display("m1")
        self.assertIn("Gmail API is disabled", out)
        self.assertIn("console.developers.google.com", out)

    def test_send_email_reports_gmail_disabled(self):
        """send_email must return the enable link when the API is disabled
        (403 accessNotConfigured), not a generic HTTP failure."""
        resp = _FakeResp(403, {},
                         text='{"error": {"message": "Gmail API has not been '
                              'used in project 123 before.", '
                              '"reason": "accessNotConfigured"}}')
        with mock.patch.object(fb, "_google_access_token", return_value="tok"), \
             mock.patch.object(fb.requests, "post", return_value=resp):
            res = fb.send_email("a@b.com", "Hi")
        self.assertFalse(res["ok"])
        self.assertIn("Gmail API is disabled", res["error"])
        self.assertIn("console.developers.google.com", res["error"])

    def test_send_email_scope_missing_still_hints_resign(self):
        """403 with a scope message keeps the re-sign-in hint (not the API
        enable link — different failure)."""
        resp = _FakeResp(403, {},
                         text="Request had insufficient authentication scopes.")
        with mock.patch.object(fb, "_google_access_token", return_value="tok"), \
             mock.patch.object(fb.requests, "post", return_value=resp):
            res = fb.send_email("a@b.com", "Hi")
        self.assertFalse(res["ok"])
        self.assertIn("permission is missing", res["error"])
        self.assertNotIn("console.developers.google.com", res["error"])

    def test_scope_includes_gmail(self):
        scope = "openid email profile " + fb.CONTACTS_SCOPE + " " + fb.GMAIL_SCOPE
        self.assertIn(fb.GMAIL_SCOPE, scope)
        self.assertIn(fb.CONTACTS_SCOPE, scope)
        self.assertEqual(fb.GMAIL_SCOPE, "https://www.googleapis.com/auth/gmail.readonly")

    def test_batch_get_uses_repeated_params(self):
        """Gmail batchGet ids/metadataHeaders must be repeated query params
        (lists), not comma-joined single values."""
        captured = {}

        def fake_get(url, **kw):
            if url.endswith("/users/me/messages"):
                return _FakeResp(200, {"messages": [{"id": "m1"}, {"id": "m2"}]})
            captured.update(kw)
            return _FakeResp(200, {"messages": []})

        with mock.patch.object(fb.requests, "get", side_effect=fake_get):
            fb.list_emails("", 5)
        self.assertEqual(captured["params"]["ids"], ["m1", "m2"])
        self.assertEqual(captured["params"]["metadataHeaders"], ["From", "Subject", "Date"])

    def test_api_error_firebase_style(self):
        r = _FakeResp(400, {"error": {"message": "GOOGLE_SIGNIN_NOT_ENABLED",
                                          "status": "INVALID_ARGUMENT"}})
        self.assertIn("GOOGLE_SIGNIN_NOT_ENABLED", fb._api_error(r))

    def test_api_error_google_token_style(self):
        r = _FakeResp(400, {"error": "invalid_grant",
                            "error_description": "Token has been expired or revoked."})
        self.assertIn("invalid_grant", fb._api_error(r))
        self.assertIn("expired", fb._api_error(r))

    def test_api_error_non_json(self):
        r = _FakeResp(502, {}, text="<html>Bad gateway</html>")
        self.assertIn("Bad gateway", fb._api_error(r))

    def test_firebase_sign_in_surfaces_real_error(self):
        """signInWithIdp 400 must include the actual Firebase error message
        instead of a blind '400 Client Error: Bad Request'."""
        with mock.patch.object(fb.requests, "post", return_value=_FakeResp(
            400, {"error": {"message": "GOOGLE_SIGNIN_NOT_ENABLED"}})):
            err = None
            try:
                fb._firebase_sign_in("id-token", "AIza-key")
            except RuntimeError as e:
                err = str(e)
        self.assertIsNotNone(err)
        self.assertIn("GOOGLE_SIGNIN_NOT_ENABLED", err)

    def test_sign_in_hint_for_invalid_api_key(self):
        hint = fb._sign_in_hint(
            "Firebase sign-in failed (HTTP 400): API key not valid. "
            "Please pass a valid API key."
        )
        self.assertIn("firebase_api_key", hint)
        self.assertIn("AIza", hint)
        self.assertIn("Web API key", hint)

    def test_sign_in_hint_for_google_not_enabled(self):
        hint = fb._sign_in_hint("Firebase sign-in failed: GOOGLE_SIGNIN_NOT_ENABLED")
        self.assertIn("Authentication", hint)
        self.assertIn("Enable", hint)

    def test_sign_in_hint_empty_for_unknown(self):
        self.assertEqual(fb._sign_in_hint("Some random error"), "")


class GoogleAccountDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        fb._CONFIG_PATH = Path(self.tmp) / "api_keys.json"

    def test_unknown_action(self):
        self.assertIn("Unknown google_account action",
                      ga.google_account({"action": "nope"}))

    def test_add_contact_string_false_is_false(self):
        """bool('false') == True footgun regression test."""
        with mock.patch.object(fb, "add_contact", return_value="ok") as m:
            ga.google_account({"action": "add_contact", "name": "Papa",
                               "verified": "false"})
        kw = m.call_args.kwargs
        self.assertFalse(kw["verified"])

    def test_verified_true_variants(self):
        for v in ["true", "1", "yes", "y", True]:
            with mock.patch.object(fb, "add_contact", return_value="ok") as m:
                ga.google_account({"action": "add_contact", "name": "A",
                                   "verified": v})
            kw = m.call_args.kwargs
            self.assertTrue(kw["verified"], f"variant {v!r}")

    def test_status_dispatch(self):
        with mock.patch.object(fb, "status", return_value="st"):
            r = ga.google_account({"action": "status"})
        self.assertEqual(r, "st")

    def test_sign_in_dispatch(self):
        with mock.patch.object(fb, "sign_in", return_value="done"):
            self.assertEqual(ga.google_account({"action": "sign_in"}), "done")

    def test_find_contact_dispatch(self):
        with mock.patch.object(fb, "find_contact_display", return_value="Found Papa") as m:
            r = ga.google_account({"action": "find_contact", "name": "Papa"})
        self.assertEqual(r, "Found Papa")
        self.assertEqual(m.call_args.args[0], "Papa")

    def test_list_emails_dispatch(self):
        with mock.patch.object(fb, "list_emails_display", return_value="emails") as m:
            r = ga.google_account({"action": "list_emails", "query": "from:boss",
                                   "max_results": "5"})
        self.assertEqual(r, "emails")
        self.assertEqual(m.call_args.args[0], "from:boss")
        self.assertEqual(m.call_args.args[1], 5)

    def test_read_email_dispatch_with_hash_number(self):
        """'read email #2' resolves the short form to the real Gmail id."""
        with mock.patch.object(fb, "list_emails", return_value=[
            {"id": "aaa"}, {"id": "bbb"}
        ]), mock.patch.object(fb, "read_email_display", return_value="body") as m:
            r = ga.google_account({"action": "read_email", "email_id": "#2"})
        self.assertEqual(r, "body")
        self.assertEqual(m.call_args.args[0], "bbb")

    def test_read_email_dispatch_out_of_range(self):
        with mock.patch.object(fb, "list_emails", return_value=[{"id": "aaa"}]), \
             mock.patch.object(fb, "read_email_display", return_value="body") as m:
            r = ga.google_account({"action": "read_email", "email_id": "#9"})
        self.assertIn("No email #9", r)
        m.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
