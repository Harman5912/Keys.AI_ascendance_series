"""Tests for multi-Google-account support in core/firebase_client.py.

Uses a temp config file (no network): the account STORE (migration, add,
switch, remove, active-account overlay) is pure config logic.
"""

import json
import tempfile
import unittest
from pathlib import Path

from core import firebase_client as fb


TOKEN_SET = {
    "firebase_refresh_token": "FR1", "firebase_id_token": "FI1",
    "firebase_id_token_expires": "9999999999", "firebase_uid": "uid-1",
    "firebase_email": "first@gmail.com", "firebase_display_name": "First",
    "google_access_token": "GA1", "google_access_expires": "9999999999",
    "google_refresh_token": "GR1",
}


class AccountStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_path = fb._CONFIG_PATH
        fb._CONFIG_PATH = Path(self._tmp.name) / "api_keys.json"

    def tearDown(self):
        fb._CONFIG_PATH = self._orig_path
        self._tmp.cleanup()

    def _write(self, cfg: dict):
        fb._CONFIG_PATH.write_text(json.dumps(cfg), encoding="utf-8")

    def _configured(self):
        """Write the shared project keys so is_configured()/status() pass."""
        self._write({"google_oauth_client_id": "cid",
                     "google_oauth_client_secret": "cs",
                     "firebase_api_key": "k", "firebase_project_id": "p"})

    def _read(self) -> dict:
        return json.loads(fb._CONFIG_PATH.read_text(encoding="utf-8"))

    def _stamp(self, email: str, i: int) -> dict:
        t = dict(TOKEN_SET)
        t.update({"firebase_email": email, "firebase_uid": f"uid-{i}",
                  "firebase_display_name": email.split("@")[0]})
        return t

    # ── migration ───────────────────────────────────────────────────────
    def test_legacy_flat_config_migrates(self):
        self._write({"firebase_uid": "old", "firebase_email": "old@x.com",
                     "firebase_refresh_token": "OLD"})
        self.assertTrue(fb.is_signed_in())
        cfg = fb._load_cfg()
        fb._ensure_accounts(cfg)
        self.assertEqual(len(cfg["google_accounts"]), 1)
        self.assertEqual(cfg["google_accounts"][0]["firebase_uid"], "old")
        self.assertEqual(cfg["active_google_account"], "old@x.com")

    def test_no_accounts_when_never_signed_in(self):
        self._write({"os_system": "windows"})
        self.assertFalse(fb.is_signed_in())
        self.assertEqual(fb.accounts_count(), 0)

    # ── add / dedupe / active ───────────────────────────────────────────
    def test_store_account_adds_and_activates(self):
        who, total = fb._store_account(self._stamp("a@gmail.com", 1))
        self.assertEqual(who, "a")
        self.assertEqual(total, 1)
        self.assertTrue(fb.is_signed_in())
        self.assertEqual(fb._active_account_cfg()["firebase_uid"], "uid-1")

    def test_store_account_dedupes_by_email(self):
        fb._store_account(self._stamp("a@gmail.com", 1))
        fb._store_account(self._stamp("b@gmail.com", 2))
        who, total = fb._store_account(self._stamp("a@gmail.com", 9))
        self.assertEqual(total, 2, "same email must update, not duplicate")
        cfg = self._read()
        emails = [a["firebase_email"] for a in cfg["google_accounts"]]
        self.assertEqual(emails, ["a@gmail.com", "b@gmail.com"])
        # refreshed account becomes active
        self.assertEqual(cfg["active_google_account"], "a@gmail.com")
        self.assertEqual(fb._active_account_cfg()["firebase_uid"], "uid-9")

    # ── switch ──────────────────────────────────────────────────────────
    def test_switch_account_by_email_and_index(self):
        fb._store_account(self._stamp("a@gmail.com", 1))
        fb._store_account(self._stamp("b@gmail.com", 2))
        self.assertIn("Switched", fb.switch_account("b@gmail.com"))
        self.assertEqual(fb._active_account_cfg()["firebase_uid"], "uid-2")
        self.assertIn("Switched", fb.switch_account("1"))
        self.assertEqual(fb._active_account_cfg()["firebase_uid"], "uid-1")
        self.assertIn("No signed-in", fb.switch_account("zzz@nowhere.com"))

    def test_active_account_overlay_only(self):
        fb._store_account(self._stamp("a@gmail.com", 1))
        fb._store_account(self._stamp("b@gmail.com", 2))
        fb.switch_account("b@gmail.com")
        view = fb._active_account_cfg()
        self.assertEqual(view["firebase_uid"], "uid-2")
        self.assertEqual(view["firebase_email"], "b@gmail.com")

    # ── remove ──────────────────────────────────────────────────────────
    def test_remove_active_account_falls_back_to_another(self):
        fb._store_account(self._stamp("a@gmail.com", 1))
        fb._store_account(self._stamp("b@gmail.com", 2))
        out = fb.remove_account("a@gmail.com")
        self.assertIn("Removed", out)
        self.assertEqual(fb._active_account_cfg()["firebase_uid"], "uid-2")
        self.assertEqual(fb.accounts_count(), 1)

    def test_remove_account_rejects_empty_key(self):
        # regression: an empty key must NOT substring-match the first account
        fb._store_account(self._stamp("a@gmail.com", 1))
        out = fb.remove_account("")
        self.assertIn("No signed-in", out)
        self.assertEqual(fb.accounts_count(), 1)   # nothing was deleted

    def test_remove_last_account_clears_everything(self):
        fb._store_account(self._stamp("a@gmail.com", 1))
        out = fb.remove_account("1")
        self.assertIn("No accounts remain", out)
        self.assertFalse(fb.is_signed_in())
        self.assertEqual(fb.accounts_count(), 0)
        cfg = self._read()
        self.assertNotIn("firebase_refresh_token", cfg)

    # ── sign_out ────────────────────────────────────────────────────────
    def test_sign_out_removes_active_account_only(self):
        fb._store_account(self._stamp("a@gmail.com", 1))
        fb._store_account(self._stamp("b@gmail.com", 2))
        fb.switch_account("a@gmail.com")
        out = fb.sign_out()
        self.assertIn("1 other", out)
        self.assertEqual(fb.accounts_count(), 1)
        self.assertEqual(fb._active_account_cfg()["firebase_email"], "b@gmail.com")

    # ── listing / status ────────────────────────────────────────────────
    def test_list_accounts_marks_active(self):
        fb._store_account(self._stamp("a@gmail.com", 1))
        fb._store_account(self._stamp("b@gmail.com", 2))
        listing = fb.list_accounts()
        self.assertIn("a@gmail.com", listing)
        self.assertIn("b@gmail.com", listing)
        self.assertIn("2", listing)

    def test_status_shows_active_and_count(self):
        self._configured()
        fb._store_account(self._stamp("a@gmail.com", 1))
        fb._store_account(self._stamp("b@gmail.com", 2))
        fb.switch_account("a@gmail.com")   # make the first account active
        out = fb.status()
        self.assertIn("Signed in as a", out)
        self.assertIn("1 of 2", out)

    def test_list_accounts_empty(self):
        self._write({"os_system": "windows"})
        self.assertIn("No Google accounts", fb.list_accounts())

    def test_configured_status_when_not_signed_in(self):
        self._configured()
        self.assertIn("Not signed in", fb.status())


if __name__ == "__main__":
    unittest.main()
