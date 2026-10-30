"""
Provider factory — build an LLMProvider from brain + api config.

    get_provider(cfg, api_config) -> LLMProvider

Providers (see core/model_catalog.PROVIDERS for the full list + models):
    gemini     -> GeminiProvider        (Google; also the Live voice engine)
    anthropic  -> AnthropicProvider     (Claude Messages API)
    nvidia     -> OpenAICompatProvider  (https://integrate.api.nvidia.com/v1)
    openrouter -> OpenAICompatProvider  (https://openrouter.ai/api/v1)
    openai     -> OpenAICompatProvider  (https://api.openai.com/v1)
    ollama     -> OpenAICompatProvider  (llm_url, default localhost:11434)
    custom     -> OpenAICompatProvider  (llm_url, optional openai_api_key)

Never raises — always falls back to a working provider (Gemini).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from brain.providers.base import LLMProvider, ProviderError, parse_json, FallbackProvider  # noqa: F401
from brain.providers.gemini import GeminiProvider
from brain.providers.openai_compat import OpenAICompatProvider

try:
    from brain.providers.anthropic import AnthropicProvider
except Exception:  # pragma: no cover - module is trivial, but stay safe
    AnthropicProvider = None

try:
    from core.model_catalog import base_url_for, default_model_for, \
        key_field_for, needs_key, provider_info
except Exception:
    base_url_for = lambda p: ""                                  # noqa: E731
    default_model_for = lambda p: ""                             # noqa: E731
    key_field_for = lambda p: {"gemini": "gemini_api_key",
                               "openai": "openai_api_key",
                               "openrouter": "openrouter_api_key"}.get(p)  # noqa: E731
    needs_key = lambda p: True                                   # noqa: E731
    provider_info = lambda p: {}                                 # noqa: E731


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


def load_api_config() -> dict:
    """The app config with encrypted credentials decrypted.

    Reading the JSON directly here meant the provider list lost every key that
    had been moved into encrypted storage.
    """
    try:
        from core.config_store import load as _load_cfg
        data = _load_cfg()
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    path = _base_dir() / "config" / "api_keys.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _build_primary(provider_name: str, model: str, api: dict) -> LLMProvider:
    """Build the primary LLMProvider for the given provider."""
    api_key = api.get(key_field_for(provider_name) or "", "")

    if provider_name == "anthropic" and AnthropicProvider is not None:
        base_url = api.get("llm_url", "") or base_url_for(provider_name) \
            or "https://api.anthropic.com"
        return AnthropicProvider(api_key=api_key, model=model,
                                 base_url=base_url)

    if provider_name in ("openai", "openrouter", "nvidia", "ollama", "custom"):
        base_url = api.get("llm_url", "") or base_url_for(provider_name)
        # Chat is a LIVE conversation: the provider default of 600s meant a
        # hung local model held the user's message for 10 minutes and then
        # answered with nothing (observed: 602s and 604s empty turns). Local
        # generation normally completes in seconds-to-tens-of-seconds; a
        # bound turns a hang into a fast, honest fallback.
        timeout = 120.0
        if provider_name == "ollama":
            base_url = base_url or "http://localhost:11434"
            api_key = ""   # local Ollama needs no key
        else:
            timeout = 180.0   # cloud APIs are fast; this bounds a hang
        return OpenAICompatProvider(base_url=base_url, model=model,
                                    api_key=api_key, timeout=timeout)

    # Default: Gemini
    return GeminiProvider(
        api_key=api.get("gemini_api_key", ""),
        model=model,
        http_options={"api_version": "v1beta"},
    )


def _build_backups(provider_name: str, model: str, api: dict) -> list[LLMProvider]:
    """Build backup providers for each key in the rotation list.

    Backup keys are stored as ``<key_field>_backups`` (a JSON array) in
    api_keys.json.  Returns an empty list when no backup keys exist.
    """
    from core.api_config import get_backup_api_keys
    backup_keys = get_backup_api_keys(provider_name)
    if not backup_keys:
        return []
    # Keyless providers (ollama, custom) don't use backup keys
    field = key_field_for(provider_name)
    if not field:
        return []
    providers: list[LLMProvider] = []
    for backup_key in backup_keys:
        if not backup_key or not backup_key.strip():
            continue
        try:
            backup_api = dict(api)
            backup_api[field] = backup_key.strip()
            providers.append(_build_primary(provider_name, model, backup_api))
        except Exception:
            continue
    return providers


def _build_local_backup(api: dict) -> LLMProvider | None:
    """The app's own local Ollama model, as a silent last resort.

    The brain's primary (config/brain.json) is a cloud provider with a free
    tier — under burst use it returns 429 RESOURCE_EXHAUSTED, which used to
    leave the chat EMPTY because there was no other provider to try. The
    local model the app is already configured to use (api_keys.json
    llm_provider=ollama) answers slower instead of not answering at all.
    """
    if str(api.get("llm_provider", "")).strip().lower() != "ollama":
        return None
    model = str(api.get("llm_model") or "").strip()
    if not model:
        return None
    base = str(api.get("llm_url") or "").strip() or "http://localhost:11434"
    try:
        # Same bounded chat timeout as the primary: this is the last resort,
        # so a hang here must not stall the conversation for 10 minutes.
        return OpenAICompatProvider(base_url=base, model=model, api_key="",
                                    timeout=120.0)
    except Exception:
        return None


def get_provider(cfg=None, api_config: dict | None = None,
                 logger=None) -> LLMProvider:
    """Build the configured LLMProvider. Never raises — falls back to Gemini.

    When backup API keys are configured for the active provider, the returned
    provider automatically tries each backup key in order on rate-limit, auth,
    or quota failures (see FallbackProvider in base.py).

    When the app is configured to use a local Ollama model, that model is
    appended as the last backup too, so a cloud quota outage degrades to a
    slow answer instead of silence.

    When a *logger* (``brain.log.BrainLogger``) is supplied, fallback events
    are emitted as ``EVT_FALLBACK`` so they appear in the on-screen log."""
    api = api_config if api_config is not None else load_api_config()
    provider_name = (cfg.get("provider") if cfg else None) \
        or api.get("llm_provider", "") or "gemini"
    provider_name = str(provider_name).strip().lower()

    model = (cfg.get("model") if cfg else None) \
        or api.get("llm_model", "") \
        or default_model_for(provider_name) or "gemini-2.5-flash"

    primary = _build_primary(provider_name, model, api)
    backups = _build_backups(provider_name, model, api)
    if provider_name != "ollama":
        local = _build_local_backup(api)
        if local is not None:
            backups = backups + [local]
    if backups:
        return FallbackProvider(primary, backups, provider_name,
                                logger=logger)
    return primary
