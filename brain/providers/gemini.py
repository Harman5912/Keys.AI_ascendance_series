"""
Gemini provider — wraps the google-genai SDK exactly the way the rest of
Keys.ai already uses it (client.models.generate_content), so the existing
API key keeps working with zero extra setup.
"""

from __future__ import annotations

import base64

from brain.providers.base import LLMProvider, ProviderError, parse_json


class GeminiProvider(LLMProvider):
    name = "gemini"

    # Every attempt carries a deadline so a single unwell model alias can never
    # hang a request forever (the failure mode this provider used to have).
    DEFAULT_TIMEOUT_S = 20.0
    # Gemma 4 on the Gemini API is slower than the Gemini Flash aliases; the
    # 20s chat deadline cut off responses that were still generating.
    GEMMA_TIMEOUT_S = 60.0

    def __init__(self, api_key: str = "", model: str = "gemini-2.5-flash",
                 http_options: dict | None = None):
        self.api_key     = api_key or ""
        self.model       = model
        self.http_options = http_options
        self._client     = None
        self.timeout_s   = (self.GEMMA_TIMEOUT_S if model.lower().startswith("gemma")
                            else self.DEFAULT_TIMEOUT_S)

    # ── lazy client (heavy import on first call only) ────────────────────
    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise ProviderError(
                    "No gemini_api_key configured in config/api_keys.json."
                )
            from google import genai
            opts = {"api_key": self.api_key}
            # Merge rather than replace: the factory passes
            # {"api_version": "v1beta"} for the Live-compatible surface, and
            # taking that branch used to drop the deadline entirely, so a
            # stalled model held a chat turn open until the SDK gave up.
            params = dict(self.http_options or {})
            params.setdefault("timeout", int(self.timeout_s * 1000))
            opts["http_options"] = params
            self._client = genai.Client(**opts)
        return self._client

    def _contents(self, prompt: str, system: str | None) -> list:
        parts = []
        if system:
            parts.append({"text": system})
        parts.append({"text": prompt})
        return parts

    def generate(self, prompt: str, system: str | None = None,
                 temperature: float = 0.2,
                 max_tokens: int | None = None) -> str:
        try:
            cfg = {"temperature": temperature}
            if max_tokens:
                cfg["max_output_tokens"] = max_tokens
            resp = self._get_client().models.generate_content(
                model=self.model,
                contents=self._contents(prompt, system),
                config=cfg,
            )
            text = getattr(resp, "text", "")
            if text is None:
                text = ""
            return text.strip()
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"Gemini generate failed: {e}") from e

    def structured_output(self, prompt: str, system: str | None = None,
                          temperature: float = 0.0) -> dict | None:
        try:
            client = self._get_client()
            cfg = {"temperature": temperature,
                   "response_mime_type": "application/json"}
            resp = client.models.generate_content(
                model=self.model,
                contents=self._contents(prompt, system),
                config=cfg,
            )
            return parse_json(getattr(resp, "text", "") or "")
        except ProviderError:
            raise
        except Exception as e:
            # Fall back to prompt-only JSON + robust parsing.
            try:
                resp = self._get_client().models.generate_content(
                    model=self.model,
                    contents=self._contents(prompt, system),
                )
                return parse_json(getattr(resp, "text", "") or "")
            except Exception as e2:
                raise ProviderError(f"Gemini structured output failed: {e2}") from e

    def describe_image(self, image_bytes: bytes, mime_type: str,
                       question: str) -> str:
        try:
            from google.genai import types
            b64 = base64.b64encode(image_bytes).decode("ascii")
            resp = self._get_client().models.generate_content(
                model=self.model,
                contents=[
                    {"inline_data": {"mime_type": mime_type, "data": b64}},
                    {"text": question},
                ],
            )
            return (getattr(resp, "text", "") or "").strip()
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"Gemini vision failed: {e}") from e
