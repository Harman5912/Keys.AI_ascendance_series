"""
core/api_config.py — central API-key & LLM-provider config manager.

Everything that reads or writes `config/api_keys.json` for the AI provider
goes through here, so the desktop UI, the dashboard REST API and the
ai_settings tool all share one safe, merge-preserving implementation.

Config shape (config/api_keys.json):
    llm_provider   — gemini | nvidia | anthropic | openrouter | openai |
                     ollama | custom
    llm_model      — the selected model id for that provider
    llm_url        — base URL (ollama/custom; optional override for the others)
    gemini_api_key / nvidia_api_key / anthropic_api_key / openrouter_api_key
    / openai_api_key — the per-provider API keys
    ... + everything else (Google accounts, Firebase, os_system ...) is
    NEVER touched by this module — saves always merge into the existing file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from core.model_catalog import (default_model_for, key_field_for, needs_key,
                                provider_info)


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


CONFIG_PATH = _base_dir() / "config" / "api_keys.json"

DEFAULT_PROVIDER = "gemini"


# ── read / write (merge-preserving) ────────────────────────────────────────

def load_config() -> dict:
    """Full api_keys.json as a dict ({} when missing/corrupt)."""
    from core import config_store
    return config_store.load()


def save_config(patch: dict) -> dict:
    """Merge `patch` into api_keys.json and persist. Returns the new config.

    Goes through core.config_store, which holds one lock across the
    read-modify-write cycle and replaces the file atomically — the two things
    that used to let a settings save erase OAuth tokens written by
    firebase_client at the same moment.
    """
    from core import config_store
    cfg = config_store.update(patch or {})
    _invalidate_provider_cache()
    return cfg


def clear_config_keys(*keys: str) -> dict:
    """Remove keys from api_keys.json and persist. Returns the new config."""
    from core import config_store
    cfg = config_store.update(remove=keys)
    _invalidate_provider_cache()
    return cfg


def _invalidate_provider_cache() -> None:
    """Drop cached provider clients after a settings change.

    Without this, switching provider or editing a key left the old client (and
    the old credential) in `core.llm_client`'s cache until restart.
    """
    try:
        from core import llm_client
        fn = getattr(llm_client, "invalidate_cache", None)
        if callable(fn):
            fn()
    except Exception:
        pass


# ── provider helpers ───────────────────────────────────────────────────────

def get_provider_name() -> str:
    return str(load_config().get("llm_provider", "") or DEFAULT_PROVIDER)


def get_model() -> str:
    return str(load_config().get("llm_model", "") or "")


def get_base_url() -> str:
    cfg = load_config()
    return str(cfg.get("llm_url", "") or "")


def get_api_key(provider: str | None = None) -> str:
    """The API key stored for `provider` (default: current provider).

    This is intentionally generic on purpose: document builders use it for any
    service that stores a key in `config/api_keys.json`, not only LLM
    providers. When the named service is not an LLM provider, the field lookup
    falls back to the raw provider name as its key field.
    """
    provider = provider or get_provider_name()
    field = key_field_for(provider) or provider.lower()
    if not field:
        return ""
    return str(load_config().get(field, "") or "")


def get_backup_api_keys(provider: str | None = None) -> list[str]:
    """Return the list of backup API keys for `provider` (default: current).

    Backup keys are stored as `<key_field>_backups` (a JSON array) in
    api_keys.json.  For backward-compatibility the legacy single-key field
    `<key_field>_backup` is also migrated into the list on first access.
    When the primary key fails (rate limit, quota, invalid), the system
    automatically falls back through this list in order."""
    provider = provider or get_provider_name()
    field = key_field_for(provider)
    if not field:
        return []
    cfg = load_config()
    backups_field = field + "_backups"
    legacy_field = field + "_backup"

    # Normalise into a list --------------------------------------------
    backups = cfg.get(backups_field)
    if isinstance(backups, list):
        return [k for k in backups if isinstance(k, str) and k.strip()]

    # Migrate legacy single-key storage into the new list format
    legacy = str(cfg.get(legacy_field, "") or "").strip()
    if legacy:
        patch = {backups_field: [legacy]}
        save_config(patch)
        return [legacy]
    return []


def get_backup_api_key(provider: str | None = None) -> str:
    """Return the first (highest-priority) backup key, or empty string.

    Kept for backward-compatibility; prefer get_backup_api_keys() when
    you need the full rotation list."""
    keys = get_backup_api_keys(provider)
    return keys[0] if keys else ""


def add_backup_api_key(provider: str, backup_key: str) -> dict:
    """Append a backup key to the rotation list for `provider`.

    Duplicate keys are silently ignored.  Returns the updated config."""
    provider = (provider or get_provider_name()).strip().lower()
    field = key_field_for(provider)
    if not field:
        return load_config()
    key = (backup_key or "").strip()
    if not key:
        return load_config()
    backups_field = field + "_backups"
    current = get_backup_api_keys(provider)
    if key in current:
        return load_config()  # already present
    current.append(key)
    return save_config({backups_field: current})


def remove_backup_api_key(provider: str, backup_key: str) -> dict:
    """Remove a specific backup key from the rotation list for `provider`.

    If multiple copies exist, only the first occurrence is removed.
    Returns the updated config."""
    provider = (provider or get_provider_name()).strip().lower()
    field = key_field_for(provider)
    if not field:
        return load_config()
    key = (backup_key or "").strip()
    backups_field = field + "_backups"
    current = get_backup_api_keys(provider)
    if key in current:
        current.remove(key)
    return save_config({backups_field: current})


def set_backup_api_keys(provider: str, backup_keys: list[str]) -> dict:
    """Replace the entire backup key list for `provider`.

    Pass an empty list to clear all backup keys."""
    provider = (provider or get_provider_name()).strip().lower()
    field = key_field_for(provider)
    if not field:
        return load_config()
    backups_field = field + "_backups"
    cleaned = [k.strip() for k in (backup_keys or []) if isinstance(k, str) and k.strip()]
    return save_config({backups_field: cleaned})


def set_backup_api_key(provider: str, backup_key: str) -> dict:
    """Set a single backup key (replaces the entire list).

    Kept for backward-compatibility.  Prefer add_backup_api_key / remove_backup_api_key
    when managing individual keys in a rotation list."""
    provider = (provider or get_provider_name()).strip().lower()
    field = key_field_for(provider)
    if not field:
        return load_config()
    key = (backup_key or "").strip()
    return set_backup_api_keys(provider, [key] if key else [])


def clear_backup_api_keys(provider: str | None = None) -> dict:
    """Remove all backup keys for `provider`.  Returns the updated config."""
    provider = (provider or get_provider_name()).strip().lower()
    field = key_field_for(provider)
    if not field:
        return load_config()
    backups_field = field + "_backups"
    legacy_field = field + "_backup"
    return clear_config_keys(backups_field, legacy_field)


def get_all_api_keys(provider: str | None = None) -> dict:
    """Return {primary: str, backups: list[str]} for the given provider."""
    provider = provider or get_provider_name()
    return {
        "primary": get_api_key(provider),
        "backups": get_backup_api_keys(provider),
    }


def has_api_key(provider: str | None = None) -> bool:
    """True when the provider is configured with a key (or needs none).
    Also returns True if any backup keys are available."""
    provider = provider or get_provider_name()
    if not needs_key(provider):
        return True
    return bool(get_api_key(provider).strip()) or bool(get_backup_api_keys(provider))


def provider_status() -> dict:
    """Summary for UIs / REST: current provider, model, url, key presence."""
    provider = get_provider_name()
    info = provider_info(provider)
    key = get_api_key(provider)
    backups = get_backup_api_keys(provider)
    return {
        "provider": provider,
        "provider_label": info.get("label", provider),
        "model": get_model() or default_model_for(provider),
        "base_url": get_base_url() or info.get("base_url", ""),
        "key_field": key_field_for(provider),
        "key_present": bool(key.strip()),
        "key_masked": (key[:6] + "..." + key[-4:]) if len(key) > 12
                      else ("set" if key else ""),
        "backup_keys_count": len(backups),
        "needs_key": bool(info.get("needs_key", True)),
        "providers": _provider_ids(),
    }


def _provider_ids() -> list[str]:
    from core.model_catalog import PROVIDER_ORDER
    return list(PROVIDER_ORDER)


# ── mutations ──────────────────────────────────────────────────────────────

def set_provider(provider: str, model: str = "", api_key: str = "",
                 base_url: str = "") -> dict:
    """Switch the active LLM provider and persist provider/model/key/url.

    - provider: id from the catalog
    - model:    model id (empty → provider default)
    - api_key:  new key for the provider (empty string keeps the existing one)
    - base_url: custom endpoint (empty → provider default)
    """
    provider = (provider or DEFAULT_PROVIDER).strip().lower()
    info = provider_info(provider)
    key_field = key_field_for(provider)
    patch: dict = {"llm_provider": provider}

    model = (model or "").strip()
    patch["llm_model"] = model or default_model_for(provider)

    # Always write llm_url (empty clears it) so a stale URL from a PREVIOUS
    # provider (e.g. ollama's localhost) can never hijack the new provider's
    # endpoint — get_provider() falls back to the provider default when empty.
    patch["llm_url"] = base_url.strip()

    if key_field and api_key.strip():
        patch[key_field] = api_key.strip()

    return save_config(patch)


def reset_api_key(provider: str | None = None) -> str:
    """Clear the API key for `provider` (default: current provider).

    Returns a human-readable message. The key stays cleared until the user
    enters a new one — this is the "reset my API key" entry point used by the
    UI button, the dashboard endpoint and the ai_settings tool.
    """
    provider = (provider or get_provider_name()).strip().lower()
    info = provider_info(provider)
    label = info.get("label", provider)
    key_field = key_field_for(provider)
    if not key_field:
        return f"{label} does not use an API key — nothing to reset."
    had_key = bool(load_config().get(key_field))
    clear_config_keys(key_field)
    if had_key:
        return (f"API key for {label} was reset. Enter a new key in "
                "Settings → AI Provider to continue.")
    return f"API key for {label} is already empty."


# ── per-task model assignment ─────────────────────────────────────────────
# config/api_keys.json shape:
#   "task_models": {
#     "brain":         {"provider": "gemini", "model": "gemini-2.5-flash"},
#     "code_helper":   {"provider": "gemini", "model": "gemini-2.5-flash"},
#     "dev_agent":     {"provider": "ollama", "model": "llama3.3"},
#     "file_processor": {"provider": "gemini", "model": "gemini-2.5-flash"}
#   }
# When a task has no entry, it falls back to the global llm_provider/model.

TASK_NAMES = ["brain", "code_helper", "dev_agent", "file_processor"]
TASK_LABELS = {
    "brain":         "Brain (General Chat)",
    "code_helper":   "Code Helper",
    "dev_agent":     "Dev Agent",
    "file_processor": "File Processor / Docs",
}


def get_task_model(task: str) -> dict:
    """Return {provider, model, url} for `task`, falling back to global config."""
    cfg = load_config()
    task_models = cfg.get("task_models") or {}
    t = task_models.get(task) or {}
    provider = t.get("provider") or cfg.get("llm_provider") or DEFAULT_PROVIDER
    model = t.get("model") or cfg.get("llm_model") or default_model_for(provider)
    url = t.get("url") or cfg.get("llm_url") or ""
    return {"provider": provider, "model": model, "url": url}


def set_task_model(task: str, provider: str, model: str,
                   url: str = "") -> dict:
    """Set per-task provider+model. Pass empty strings to clear (revert to global)."""
    cfg = load_config()
    task_models = cfg.get("task_models") or {}
    if provider and model:
        task_models[task] = {"provider": provider, "model": model}
        if url:
            task_models[task]["url"] = url
    else:
        task_models.pop(task, None)
    patch = {"task_models": task_models}
    return save_config(patch)


def get_all_task_models() -> dict:
    """Return the full task_models dict."""
    cfg = load_config()
    return cfg.get("task_models") or {}
