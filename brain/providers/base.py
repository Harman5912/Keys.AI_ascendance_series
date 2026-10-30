"""
Model-agnostic LLM provider abstraction (spec §4).

The Brain talks to an `LLMProvider` — never to a specific vendor SDK.
Providers implement generate / stream / structured_output (JSON) and,
optionally, image description for vision steps.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Callable

log = logging.getLogger(__name__)


class ProviderError(Exception):
    """Raised when a provider call fails (network, auth, parse, ...)."""


def parse_json(text: str) -> dict | None:
    """
    Robustly extract the first JSON object from a model reply.

    Tolerates markdown fences, prose around the JSON, and minor issues.
    Returns None when no valid object is found.
    """
    if not text:
        return None

    # Strip markdown code fences
    text = re.sub(r"```(?:json)?", "", text).strip()

    # Try the whole thing first
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Find the first balanced { ... } block
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        pass
                    break
        start = text.find("{", start + 1)

    # Last resort: a simple key:value dict
    try:
        pairs = re.findall(r'"([^"]+)"\s*:\s*"([^"]*)"', text)
        if pairs:
            return dict(pairs)
    except Exception:
        pass
    return None


class LLMProvider(ABC):
    """Abstract interface every model provider implements."""

    name: str = "base"

    @abstractmethod
    def generate(self, prompt: str, system: str | None = None,
                 temperature: float = 0.2,
                 max_tokens: int | None = None) -> str:
        """Return a plain-text completion for `prompt`."""

    def stream(self, prompt: str, system: str | None = None,
               on_token: Callable[[str], None] | None = None) -> str:
        """Stream the completion; calls on_token per token. Defaults to generate."""
        text = self.generate(prompt, system=system)
        if on_token:
            for chunk in _chunk_text(text, 24):
                on_token(chunk)
        return text

    @abstractmethod
    def structured_output(self, prompt: str, system: str | None = None,
                          temperature: float = 0.0) -> dict | None:
        """Ask the model for a JSON object and return it (or None)."""

    def describe_image(self, image_bytes: bytes, mime_type: str,
                       question: str) -> str:
        """Describe an image. Default: not supported by this provider."""
        raise ProviderError(
            f"Provider '{self.name}' does not support image understanding."
        )

    def available(self) -> bool:
        return True


class FallbackProvider(LLMProvider):
    """Wraps a primary provider and retries with backup providers on failure.

    When the primary key hits a rate limit, quota, auth error, or network
    failure, the FallbackProvider automatically tries each backup key in
    order until one succeeds.  Backup keys come from
    core/api_config.get_backup_api_keys (stored as ``<key_field>_backups``
    in config/api_keys.json).

    When a *logger* (``brain.log.BrainLogger``) is provided, fallback events
    are emitted as ``EVT_FALLBACK`` so they appear in the on-screen log."""

    def __init__(self, primary: LLMProvider,
                 backups: list[LLMProvider] | None = None,
                 provider_name: str = "",
                 logger=None):
        self._primary = primary
        self._backups: list[LLMProvider] = backups or []
        self._provider_name = provider_name
        self._logger = logger  # BrainLogger | None
        n = len(self._backups)
        self.name = (f"{primary.name}_fallback(+{n})" if n
                     else primary.name)
        self._active_backup_index: int = -1  # -1 = using primary

    @classmethod
    def from_single_backup(cls, primary: LLMProvider,
                           backup: LLMProvider | None = None,
                           provider_name: str = "") -> "FallbackProvider":
        """Convenience constructor for a single backup (backward-compat)."""
        return cls(primary, backups=[backup] if backup else [],
                   provider_name=provider_name)

    def _is_retryable(self, err: Exception) -> bool:
        """Return True if *err* is a transient / key-related error we can
        retry with a different key."""
        err_msg = str(err).lower()
        if any(k in err_msg for k in (
            "rate limit", "quota", "429", "too many requests",
            "expired", "resource exhausted",
        )):
            return True
        # Google's real auth payloads do NOT contain the word "auth":
        #   400 INVALID_ARGUMENT … "API key not valid. Please pass a valid
        #   API key." / "reason": "API_KEY_INVALID". Without this clause an
        #   invalid or missing key propagated as a hard failure and the chat
        #   went silent even though a working backup existed.
        if any(k in err_msg for k in (
            "api key not valid", "api_key_invalid", "invalid api key",
            "api key is invalid", "api key expired", "api key missing",
            "unauthenticated", "invalid authentication",
            "permission denied", "access denied",
        )):
            return True
        if "key" in err_msg and any(k in err_msg for k in (
            "invalid", "not valid", "revoked",
        )):
            return True
        if (any(k in err_msg for k in ("authentication", "auth"))
                and any(k in err_msg for k in (
                    "key", "token", "credential", "api key",
                    "invalid", "expired",
                ))):
            return True
        return False

    def _emit(self, level: str, msg: str) -> None:
        """Emit *msg* to both the stdlib logger and the BrainLogger."""
        getattr(log, level, log.info)(msg)
        if self._logger is not None:
            from brain.log import EVT_FALLBACK  # local import to avoid circulars
            self._logger.event(EVT_FALLBACK, msg)

    def _try_with_fallback(self, method: str, *args, **kwargs):
        """Call *method* on primary, then rotate through backup providers."""
        try:
            return getattr(self._primary, method)(*args, **kwargs)
        except (ProviderError, Exception) as primary_err:
            if not self._backups or not self._is_retryable(primary_err):
                raise
            provider_label = self._provider_name or self._primary.name
            self._emit(
                "warning",
                f"Primary key failed ({type(primary_err).__name__}: "
                f"{str(primary_err)[:80]}) — trying "
                f"{len(self._backups)} backup key(s) for {provider_label}",
            )
            for idx, backup in enumerate(self._backups):
                self._emit(
                    "info",
                    f"Trying backup key {idx + 1}/{len(self._backups)} "
                    f"for {provider_label}",
                )
                try:
                    self._active_backup_index = idx
                    result = getattr(backup, method)(*args, **kwargs)
                    self._emit(
                        "info",
                        f"Backup key {idx + 1}/{len(self._backups)} "
                        f"succeeded for {provider_label}",
                    )
                    return result
                except Exception as backup_err:
                    remaining = len(self._backups) - idx - 1
                    self._emit(
                        "warning",
                        f"Backup key {idx + 1}/{len(self._backups)} also failed "
                        f"({type(backup_err).__name__}: "
                        f"{str(backup_err)[:60]})"
                        + (f" — {remaining} key(s) remaining"
                           if remaining else ""),
                    )
                    continue
            # All backups exhausted — raise the original error
            self._active_backup_index = -1
            self._emit(
                "error",
                f"All {len(self._backups)} backup key(s) exhausted for "
                f"{provider_label} — using primary",
            )
            raise primary_err from None

    # ── LLMProvider interface ───────────────────────────────────────────
    def generate(self, prompt: str, system: str | None = None,
                 temperature: float = 0.2,
                 max_tokens: int | None = None) -> str:
        return self._try_with_fallback(
            "generate", prompt, system=system,
            temperature=temperature, max_tokens=max_tokens)

    def stream(self, prompt: str, system: str | None = None,
               on_token=None) -> str:
        return self._try_with_fallback(
            "stream", prompt, system=system, on_token=on_token)

    def structured_output(self, prompt: str, system: str | None = None,
                          temperature: float = 0.0) -> dict | None:
        return self._try_with_fallback(
            "structured_output", prompt, system=system,
            temperature=temperature)

    def describe_image(self, image_bytes: bytes, mime_type: str,
                       question: str) -> str:
        return self._try_with_fallback(
            "describe_image", image_bytes, mime_type, question)

    def available(self) -> bool:
        return self._primary.available()

    @property
    def is_using_backup(self) -> bool:
        return self._active_backup_index >= 0

    @property
    def active_backup_index(self) -> int:
        """Index into the backups list of the currently-active backup, or -1."""
        return self._active_backup_index

    @property
    def backup_count(self) -> int:
        return len(self._backups)


def _chunk_text(text: str, size: int):
    for i in range(0, len(text), size):
        yield text[i:i + size]
