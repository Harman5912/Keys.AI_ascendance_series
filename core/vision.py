"""
core/vision.py — provider-aware SCREEN VISION.

Everything that asks an AI model to LOOK at a screenshot goes through here.
The screen automation stack (computer_control, whatsapp takeover, call/message
verification) previously hardcoded Google Gemini; now it follows the user's
active provider from config/api_keys.json, exactly like the brain does:

    gemini     -> Google Gemini (genai SDK, model fallback chain)
    openai     -> OpenAI (gpt-4o family)
    openrouter -> OpenRouter (vision-capable models)
    nvidia     -> NVIDIA NIM (vision-capable models)
    anthropic  -> Anthropic Claude (Messages API, image blocks)
    ollama     -> local Ollama (llava / llama3.2-vision / ...)
    custom     -> any OpenAI-compatible endpoint

Design goals:
  * ONE entry point:  vision_generate_text(prompt, image_bytes, mime) -> str|None
  * Graceful: returns None when vision is unavailable (no key, quota, network)
    so the SEE->ACT->VERIFY loops keep their honest fallback behaviour.
  * Model fallback per provider — if the first vision model 404s/429s the
    next one is tried, mirroring the Gemini-only behaviour that existed.
"""

from __future__ import annotations

import base64

from core.api_config import get_api_key, get_base_url, get_provider_name
from core.model_catalog import base_url_for


# ── vision-capable model chains per provider ──────────────────────────────
# First entry is preferred; the chain is walked on failure (429/404/etc).
_VISION_MODELS = {
    "gemini": (
        "gemini-2.5-flash",
        "gemini-3.5-flash",
        "gemini-flash-lite-latest",
    ),
    "openai": (
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4.1",
    ),
    "openrouter": (
        "google/gemini-2.5-flash",
        "meta-llama/llama-3.2-11b-vision-instruct",
        "qwen/qwen-2.5-vl-72b-instruct",
    ),
    "nvidia": (
        "nvidia/llama-3.2-11b-vision-instruct",
        "meta/llama-3.2-11b-vision-instruct",
    ),
    "anthropic": (
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
    ),
    "ollama": (
        "llava",
        "llama3.2-vision",
        "minicpm-v",
        "qwen2.5vl",
    ),
    "custom": (
        "gpt-4o",
        "gpt-4o-mini",
    ),
}


def vision_models(provider: str | None = None) -> tuple[str, ...]:
    """Vision model chain for `provider` (default: active provider)."""
    provider = (provider or get_provider_name()).strip().lower()
    return _VISION_MODELS.get(provider, ("gpt-4o", "gpt-4o-mini"))


def _openai_compatible_chat(base_url: str, api_key: str, model: str,
                            prompt: str, image_b64: str,
                            mime: str = "image/png") -> str | None:
    """Call an OpenAI-compatible /chat/completions with an image part.

    Works for openai / openrouter / nvidia / ollama / custom.
    Returns the model text or None on failure.
    """
    url = (base_url or "").rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
            ],
        }],
        "max_tokens": 512,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        import requests
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        if r.status_code >= 400:
            print(f"[Vision] WARN {model} HTTP {r.status_code}: "
                  f"{r.text[:160]}")
            return None
        data = r.json()
        choices = data.get("choices") or []
        if not choices:
            return None
        content = choices[0].get("message", {}).get("content")
        if isinstance(content, list):          # some providers return parts
            content = "".join(
                str(p.get("text", "")) for p in content if isinstance(p, dict))
        return content if isinstance(content, str) and content.strip() else None
    except Exception as e:
        print(f"[Vision] WARN openai-compatible {model} error: {str(e)[:150]}")
        return None


def _anthropic_chat(api_key: str, model: str, prompt: str, image_b64: str,
                    mime: str = "image/png") -> str | None:
    """Call Anthropic Messages API with a base64 image block."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 512,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": mime,
                            "data": image_b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    }
    try:
        import requests
        r = requests.post("https://api.anthropic.com/v1/messages",
                          json=payload, headers=headers, timeout=60)
        if r.status_code >= 400:
            print(f"[Vision] WARN {model} HTTP {r.status_code}: "
                  f"{r.text[:160]}")
            return None
        data = r.json()
        blocks = data.get("content") or []
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    except Exception as e:
        print(f"[Vision] WARN anthropic {model} error: {str(e)[:150]}")
        return None


def vision_generate_text(prompt: str, image_bytes: bytes,
                         mime: str = "image/png",
                         provider: str | None = None) -> str | None:
    """Ask the active provider's vision model about a screenshot.

    Returns the model's raw text, or None when vision is unavailable for the
    active provider (missing key, quota, network, no vision model pulled
    locally). NEVER raises — callers treat None as "could not see".
    """
    provider = (provider or get_provider_name()).strip().lower()
    api_key = get_api_key(provider)

    # ── gemini (the original path, model fallback chain) ────────────────
    if provider == "gemini":
        if not api_key:
            return None
        try:
            from google import genai
            from google.genai import types as gtypes
            client = genai.Client(api_key=api_key)
            last_err = None
            for model in vision_models("gemini"):
                try:
                    resp = client.models.generate_content(
                        model=model,
                        contents=[gtypes.Part.from_bytes(data=image_bytes,
                                                         mime_type=mime),
                                  prompt],
                    )
                    return (resp.text or "").strip() or None
                except Exception as e:
                    last_err = e
                    print(f"[Vision] WARN gemini {model} failed: {str(e)[:120]}")
            print(f"[Vision] WARN all gemini models failed: {str(last_err)[:120]}")
            return None
        except Exception as e:
            print(f"[Vision] WARN gemini client error: {str(e)[:150]}")
            return None

    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    # ── anthropic ───────────────────────────────────────────────────────
    if provider == "anthropic":
        if not api_key:
            return None
        for model in vision_models("anthropic"):
            text = _anthropic_chat(api_key, model, prompt, image_b64, mime)
            if text:
                return text.strip()
        return None

    # ── OpenAI-compatible: openai / openrouter / nvidia / ollama / custom ─
    base_url = get_base_url() or base_url_for(provider)
    if provider == "ollama":
        # Ollama's OpenAI-compat endpoint lives under /v1. A bare host URL
        # from llm_url must not produce /chat/completions on the root.
        base_url = (base_url or "http://localhost:11434").rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
    for model in vision_models(provider):
        # Ollama keys may be absent by design — that's fine.
        text = _openai_compatible_chat(base_url, api_key, model, prompt,
                                       image_b64, mime)
        if text:
            return text.strip()
    return None
