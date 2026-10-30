"""
Anthropic provider — talks to the Anthropic Messages API over plain HTTP
(requests), so no extra dependency beyond `requests` (already shipped).

Endpoint: POST {base}/v1/messages
Headers:  x-api-key, anthropic-version: 2023-06-01
Body:     {model, max_tokens, system, messages: [{role, content}]}
"""

from __future__ import annotations

from brain.providers.base import LLMProvider, ProviderError, parse_json

_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str = "", model: str = "claude-sonnet-4-5",
                 base_url: str = "https://api.anthropic.com",
                 timeout: float = 90.0):
        self.api_key  = api_key or ""
        self.model    = model
        self.base_url = base_url.rstrip("/")
        self.timeout  = timeout

    # ── request plumbing ────────────────────────────────────────────────
    def _post(self, system: str | None, messages: list[dict],
              temperature: float, max_tokens: int | None) -> str:
        if not self.api_key:
            raise ProviderError(
                "No anthropic_api_key configured in config/api_keys.json."
            )
        import requests
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
        }
        payload: dict = {
            "model": self.model,
            "max_tokens": max_tokens or _DEFAULT_MAX_TOKENS,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        try:
            resp = requests.post(
                f"{self.base_url}/v1/messages", json=payload,
                headers=headers, timeout=self.timeout,
            )
            if resp.status_code == 401:
                raise ProviderError(
                    "Anthropic API key is invalid or expired — reset the key "
                    "and enter a new one."
                )
            resp.raise_for_status()
            data = resp.json()
            parts = data.get("content") or []
            text = "".join(
                p.get("text", "") for p in parts
                if isinstance(p, dict) and p.get("type") == "text"
            )
            return text.strip()
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(
                f"Anthropic request failed: {e}"
            ) from e

    def _messages(self, prompt: str) -> list[dict]:
        return [{"role": "user", "content": prompt}]

    # ── LLMProvider interface ───────────────────────────────────────────
    def generate(self, prompt: str, system: str | None = None,
                 temperature: float = 0.2,
                 max_tokens: int | None = None) -> str:
        return self._post(system, self._messages(prompt), temperature,
                          max_tokens)

    def stream(self, prompt: str, system: str | None = None,
               on_token=None) -> str:
        # Streams via the HTTP API in one shot; tokens are still delivered
        # incrementally so callers see progressive output.
        text = self.generate(prompt, system=system)
        if on_token:
            for chunk in _chunk(text, 24):
                on_token(chunk)
        return text

    def structured_output(self, prompt: str, system: str | None = None,
                          temperature: float = 0.0) -> dict | None:
        json_prompt = (
            prompt
            + "\n\nIMPORTANT: Reply with ONLY a valid JSON object. "
            "No prose, no markdown fences."
        )
        text = self._post(system, self._messages(json_prompt),
                          temperature, None)
        return parse_json(text)


def _chunk(text: str, size: int):
    for i in range(0, len(text), size):
        yield text[i:i + size]
