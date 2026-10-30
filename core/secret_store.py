"""Encrypted storage for credentials, backed by Windows DPAPI.

The audit found provider keys and Google OAuth tokens sitting in plaintext in
``config/api_keys.json`` (and a TLS private key in ``config/certs/``). Anyone
with a copy of the folder — a backup, a screenshot, a support bundle, a
generated project that copied the config — had working credentials.

This module encrypts credential *values* with DPAPI (``CryptProtectData``),
which ties the ciphertext to the current Windows user account. No new
dependency is required (ctypes only) and no master password has to be stored
anywhere: the OS holds the key.

The seam is ``core.config_store``: it splits credential-shaped keys out of the
JSON on write and injects the decrypted values back on read, so every existing
caller (``api_config``, ``firebase_client``, ``memory.config_manager``, the
tools) keeps seeing the same dict it always saw.

Availability: Windows only. On any other platform, or if DPAPI fails,
``available()`` is False and callers fall back to the previous plaintext
behaviour rather than losing access to configured credentials.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


SECRETS_PATH = _base_dir() / "config" / "secrets.enc"

_LOCK = threading.RLock()
_CACHE: dict | None = None
_AVAILABLE: bool | None = None

# A key is treated as a credential when its name ends with (or contains, as a
# whole segment) one of these. Deliberately conservative: a false positive only
# means the value is encrypted rather than stored as readable JSON.
_SECRET_SUFFIXES = (
    "api_key", "api_keys", "apikey", "token", "tokens", "secret", "password",
    "passwd", "private_key", "refresh_token", "access_token", "id_token",
    "client_secret", "session_key", "webhook_secret",
)
# Names that are not credentials themselves but hold them: every signed-in
# Google account carries refresh/access/id tokens inside the list, so leaving
# `google_accounts` in the JSON would leave those tokens readable.
_SECRET_CONTAINS = ("api_key_backups", "google_accounts")


def is_secret_name(name: str) -> bool:
    n = (name or "").strip().lower()
    if not n:
        return False
    if n in ("token_budget", "tokens_used", "max_tokens"):
        return False                     # counters, not credentials
    if n.endswith(_SECRET_SUFFIXES):
        return True
    return any(part in n for part in _SECRET_CONTAINS)


# ── DPAPI ─────────────────────────────────────────────────────────────────
def _dpapi(data: bytes, protect: bool) -> bytes:
    """Encrypt/decrypt with the current user's DPAPI key."""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(payload: bytes) -> DATA_BLOB:
        buf = ctypes.create_string_buffer(payload, len(payload))
        return DATA_BLOB(len(payload), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    in_blob, _keep = blob(data)
    out_blob = DATA_BLOB()
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(in_blob), None, None, None, None, 0,
            ctypes.byref(out_blob))
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0,
            ctypes.byref(out_blob))
    if not ok:
        raise OSError("DPAPI operation failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def available() -> bool:
    """True when credentials can be encrypted on this machine."""
    global _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    if not sys.platform.startswith("win"):
        _AVAILABLE = False
        return _AVAILABLE
    try:
        probe = b"keysai-probe"
        _AVAILABLE = _dpapi(_dpapi(probe, True), False) == probe
    except Exception:
        _AVAILABLE = False
    return _AVAILABLE


# ── storage ───────────────────────────────────────────────────────────────
def _read_raw() -> dict:
    global _CACHE
    if _CACHE is not None:
        return dict(_CACHE)
    try:
        raw = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
        items = raw.get("items") if isinstance(raw, dict) else None
        _CACHE = dict(items) if isinstance(items, dict) else {}
    except Exception:
        _CACHE = {}
    return dict(_CACHE)


def _write_raw(items: dict) -> None:
    global _CACHE
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SECRETS_PATH.with_suffix(SECRETS_PATH.suffix + f".tmp{os.getpid()}")
    try:
        tmp.write_text(json.dumps({"version": 1, "items": items}, indent=2),
                       encoding="utf-8")
        os.replace(tmp, SECRETS_PATH)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
    try:
        os.chmod(SECRETS_PATH, 0o600)
    except Exception:
        pass
    _CACHE = dict(items)


def _decode(blob_b64: str):
    raw = base64.b64decode(blob_b64.encode("ascii"))
    return json.loads(_dpapi(raw, False).decode("utf-8"))


def _encode(value) -> str:
    payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
    return base64.b64encode(_dpapi(payload, True)).decode("ascii")


def load_all() -> dict:
    """All stored credentials, decrypted. ``{}`` when unavailable or corrupt."""
    if not available():
        return {}
    with _LOCK:
        out: dict = {}
        for name, blob in _read_raw().items():
            try:
                out[name] = _decode(blob)
            except Exception:
                continue            # different user/machine, or corrupt blob
        return out


def store(values: dict) -> None:
    """Encrypt and persist ``values`` (merging into what is already stored)."""
    if not available() or not values:
        return
    with _LOCK:
        items = _read_raw()
        for name, value in values.items():
            try:
                items[name] = _encode(value)
            except Exception:
                continue
        _write_raw(items)


def delete(names) -> None:
    if not available() or not names:
        return
    with _LOCK:
        items = _read_raw()
        for name in names:
            items.pop(name, None)
        _write_raw(items)


def names() -> list[str]:
    return sorted(_read_raw().keys())


def reset_cache() -> None:
    global _CACHE
    with _LOCK:
        _CACHE = None


__all__ = ["available", "load_all", "store", "delete", "names", "is_secret_name",
           "reset_cache", "SECRETS_PATH"]
