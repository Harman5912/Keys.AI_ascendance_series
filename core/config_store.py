"""Single writer for ``config/api_keys.json``.

Three modules used to read-modify-write this file independently:
``core/api_config.py`` (provider settings), ``memory/config_manager.py``
(voice, theme, devices) and ``core/firebase_client.py`` (OAuth tokens and
accounts). Each loaded the whole file, changed one key and wrote the whole file
back, so a settings save that overlapped a Google token refresh silently erased
whichever keys the other writer had just added.

This module is the one place that touches the file:

    * one process-wide re-entrant lock around the read-modify-write cycle;
    * atomic replacement (write to ``.tmp`` in the same directory, then
      ``os.replace``) so a crash mid-write cannot leave a half-written config;
    * a corrupt file is preserved as ``.corrupt-<ts>`` and treated as empty
      instead of raising or being overwritten without trace.

Callers never see secret handling change: the dict they get is the same dict
they had before.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = _base_dir() / "config" / "api_keys.json"

_LOCK = threading.RLock()
_migrated = False


def _secrets():
    """The encrypted store, or None when it is unavailable on this machine."""
    try:
        from core import secret_store
        return secret_store if secret_store.available() else None
    except Exception:
        return None


def _split(data: dict) -> tuple[dict, dict]:
    """Split credential-shaped keys from everything else."""
    store = _secrets()
    if store is None:
        return dict(data or {}), {}
    plain, secrets = {}, {}
    for key, value in (data or {}).items():
        (secrets if store.is_secret_name(key) else plain)[key] = value
    return plain, secrets


def _migrate_plaintext_once() -> None:
    """Move credentials that are still sitting in the JSON into the store.

    Idempotent and failure-tolerant: if anything goes wrong the plaintext file
    is left exactly as it was, so a user can never lose access to a working
    configuration because of this migration.
    """
    global _migrated
    if _migrated:
        return
    _migrated = True
    store = _secrets()
    if store is None:
        return
    try:
        data = _read_json()
        secrets = {k: v for k, v in data.items()
                   if store.is_secret_name(k) and v not in (None, "")}
        if not secrets:
            return
        store.store(secrets)
        plain = {k: v for k, v in data.items() if k not in secrets}
        _write_json(plain)
        print(f"[config] moved {len(secrets)} credential(s) into encrypted storage")
    except Exception as exc:
        print(f"[config] credential migration skipped: {exc}")


# ── read ──────────────────────────────────────────────────────────────────
def _read_json() -> dict:
    try:
        raw = CONFIG_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        _quarantine_corrupt()
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + f".tmp{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data or {}, fh, indent=2, ensure_ascii=False)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except Exception:
                pass
        os.replace(tmp, CONFIG_PATH)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def load() -> dict:
    """The whole config as a dict. Missing or corrupt → ``{}``.

    Credentials live in the encrypted store and are decrypted into the
    returned dict, so callers see exactly the shape they always saw. A corrupt
    JSON file is moved aside first, so the next write cannot destroy the only
    copy of anything a human could still recover by hand.
    """
    with _LOCK:
        _migrate_plaintext_once()
        data = _read_json()
        store = _secrets()
        if store is not None:
            try:
                data.update(store.load_all())
            except Exception:
                pass
        return data


def _quarantine_corrupt() -> None:
    try:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = CONFIG_PATH.with_suffix(f".corrupt-{stamp}.json")
        os.replace(CONFIG_PATH, target)
        print(f"[config] unreadable config preserved as {target.name}")
    except Exception:
        pass


# ── write ─────────────────────────────────────────────────────────────────
def atomic_write(data: dict) -> None:
    """Persist ``data``: credentials encrypted, everything else as JSON.

    Splitting here rather than in each caller is what makes the change
    complete — every module that saves settings (api_config, firebase_client,
    config_manager, screen_processor) goes through this function.
    """
    with _LOCK:
        plain, secrets = _split(data)
        store = _secrets()
        if store is not None:
            if secrets:
                store.store(secrets)
            # A credential removed from the config must not survive in the
            # encrypted store, or a reset would silently re-appear on read.
            stale = [n for n in store.names() if n not in secrets]
            if stale:
                store.delete(stale)
        else:
            plain = dict(data or {})
        _write_json(plain)


def update(patch: dict | None = None, *, mutate=None,
           remove=()) -> dict:
    """Merge ``patch`` (and optionally ``mutate(cfg)``) into the config.

    The whole load → change → write cycle happens under one lock, so two
    threads saving different settings cannot lose each other's keys.
    Returns the new config.
    """
    with _LOCK:
        cfg = load()
        if patch:
            cfg.update({k: v for k, v in patch.items() if v is not None})
        if mutate is not None:
            result = mutate(cfg)
            if isinstance(result, dict):
                cfg = result
        for key in remove or ():
            cfg.pop(key, None)
        atomic_write(cfg)
        return cfg


__all__ = ["CONFIG_PATH", "load", "update", "atomic_write"]
