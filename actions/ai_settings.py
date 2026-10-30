"""
ai_settings — tool for viewing/switching the AI provider and resetting API
keys by voice: "which AI are you using?", "switch to openrouter",
"reset your api key", "use ollama with llama3.3".

Wraps core/api_config (the same layer the desktop UI and dashboard use), so
changes made here are instantly reflected everywhere.

Backup keys (rotation): when the primary key fails (rate limit, quota, auth),
the system automatically tries each backup key in order until one succeeds.
Manage backup keys via:
  - add_backup:    append a backup API key to the rotation list
  - remove_backup: remove a specific backup key from the rotation
  - clear_backups: remove all backup keys
  - list_backups:  show the current rotation list
  - get / status now shows backup key count
"""

from __future__ import annotations

from core import api_config
from core.model_catalog import provider_labels, provider_info


def ai_settings(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params  = parameters or {}
    action  = (params.get("action") or "get").strip().lower()

    if action in ("get", "status"):
        st = api_config.provider_status()
        provider = st["provider"]
        key_txt = "key set" if st["key_present"] else "NO KEY SET"
        backups = api_config.get_backup_api_keys(provider)
        if backups:
            backup_txt = f"{len(backups)} backup key(s) in rotation"
        else:
            backup_txt = "no backups"
        return (f"Provider: {st['provider_label']} ({st['provider']})\n"
                f"Model: {st['model']}\n"
                f"Endpoint: {st['base_url'] or 'default'}\n"
                f"API key: {key_txt}\n"
                f"Backup keys: {backup_txt}\n"
                f"Say 'switch to <provider>' or open Settings → AI Provider "
                f"to change.")

    if action in ("reset", "reset_key"):
        return api_config.reset_api_key(params.get("provider") or None)

    if action in ("add_backup", "set_backup", "setbackup"):
        provider = (params.get("provider") or "").strip().lower()
        backup_key = (params.get("api_key") or params.get("backup_key") or "").strip()
        if not provider:
            provider = api_config.get_provider_name()
        if not backup_key:
            return (f"Please provide the backup API key. Example: "
                    f"'add backup key for {provider}: sk-...'")
        info = provider_info(provider)
        existing = api_config.get_backup_api_keys(provider)
        if backup_key in existing:
            return (f"That key is already in the backup rotation for "
                    f"{info.get('label', provider)}.")
        api_config.add_backup_api_key(provider, backup_key)
        new_count = len(api_config.get_backup_api_keys(provider))
        return (f"Backup key added for {info.get('label', provider)} — "
                f"{new_count} backup key(s) in rotation now. "
                f"If the primary key fails, the system will try each "
                f"backup key in order.")

    if action in ("remove_backup", "clearbackup"):
        provider = (params.get("provider") or "").strip().lower()
        backup_key = (params.get("api_key") or params.get("backup_key") or "").strip()
        if not provider:
            provider = api_config.get_provider_name()
        info = provider_info(provider)
        if backup_key:
            api_config.remove_backup_api_key(provider, backup_key)
            remaining = len(api_config.get_backup_api_keys(provider))
            return (f"Backup key removed from {info.get('label', provider)} — "
                    f"{remaining} backup key(s) remaining.")
        # No specific key given — list them
        keys = api_config.get_backup_api_keys(provider)
        if not keys:
            return f"No backup keys configured for {info.get('label', provider)}."
        masked = [k[:6] + "..." + k[-4:] if len(k) > 12 else k[:3] + "..."
                  for k in keys]
        return (f"Backup keys for {info.get('label', provider)}:\n" +
                "\n".join(f"  {i+1}. {m}" for i, m in enumerate(masked)) +
                "\nSay 'remove backup key #<n>' to remove one, or "
                "'clear all backups' to remove all.")

    if action in ("clear_backups", "clear_backup", "clearbackup"):
        provider = (params.get("provider") or "").strip().lower()
        if not provider:
            provider = api_config.get_provider_name()
        info = provider_info(provider)
        api_config.clear_backup_api_keys(provider)
        return f"All backup keys cleared for {info.get('label', provider)}."

    if action in ("list_backups", "list_backup"):
        provider = (params.get("provider") or "").strip().lower()
        if not provider:
            provider = api_config.get_provider_name()
        info = provider_info(provider)
        keys = api_config.get_backup_api_keys(provider)
        if not keys:
            return f"No backup keys configured for {info.get('label', provider)}."
        masked = [k[:6] + "..." + k[-4:] if len(k) > 12 else k[:3] + "..."
                  for k in keys]
        lines = [f"Backup keys for {info.get('label', provider)} ({len(keys)}):"]
        for i, m in enumerate(masked, 1):
            lines.append(f"  {i}. {m}")
        lines.append("\nRotation order: tried in order on primary key failure.")
        return "\n".join(lines)

    if action in ("set", "switch", "change"):
        provider = (params.get("provider") or "").strip().lower()
        if not provider:
            labels = ", ".join(f"{pid} ({info['label']})"
                               for pid, info in provider_labels())
            return (f"Which provider? Available: {labels}. For example "
                    f"'switch to openrouter' or 'use ollama'.")
        info = provider_info(provider)
        model = (params.get("model") or "").strip()
        api_key = (params.get("api_key") or "").strip()
        api_config.set_provider(provider, model=model, api_key=api_key)
        st = api_config.provider_status()
        return (f"Switched to {info['label']} — model {st['model']}. "
                f"{'API key is set.' if st['key_present'] else 'Remember to add your ' + info['label'] + ' API key in Settings → AI Provider.'}")

    if action in ("list", "providers", "models"):
        lines = [f"Available providers ({len(provider_labels())}):"]
        for pid, label in provider_labels():
            info = provider_info(pid)
            lines.append(f"  • {pid:<10} {label} "
                         f"({len(info.get('models', []))} models)")
        return "\n".join(lines)

    return ("ai_settings actions: get | set (provider/model/api_key) | "
            "reset_key (provider) | add_backup (provider + api_key) | "
            "remove_backup (provider + api_key_or_#n) | clear_backups | "
            "list_backups | list. "
            "Try 'which AI are you using?'")
