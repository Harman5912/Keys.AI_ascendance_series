"""Optional prompt enhancement through the app's existing Ollama models.

Requirements this module follows:

* enhancement is never required — generation works with the user's own prompt;
* the model is whatever the app is already configured to use locally. Nothing
  is hard-coded and no cloud provider is ever involved (if Ollama is not
  reachable, enhancement reports that and stops);
* the rewrite is instructed to preserve the user's subject, action and setting,
  and the original prompt is always kept alongside the enhanced one.

No claim is made that the result is better — that needs evaluation, which this
build does not perform.
"""

from __future__ import annotations

import re

_SYSTEM = (
    "You rewrite short descriptions into prompts for a Stable Diffusion image "
    "generator. Preserve the user's subject, action, setting and any named "
    "details exactly. Add concrete visual detail only: composition, lighting, "
    "materials, atmosphere, camera framing. Return ONE paragraph of at most "
    "90 words. No preamble, no headings, no quotes, no negative prompt, no "
    "explanation. Never add people, text or objects the user did not mention."
)

_PREFIXES = re.compile(
    r"^\s*(enhanced\s+)?prompt\s*[:\-]\s*", re.IGNORECASE)


class EnhanceError(RuntimeError):
    pass


def _ollama_base() -> str:
    """The local Ollama endpoint, from the app's own settings."""
    from core.image_studio import settings
    studio = settings.load()
    try:
        from core.model_catalog import PROVIDERS
        from core.config_store import load as load_config
        cfg = load_config()
    except Exception:
        return "http://localhost:11434"
    provider = str(cfg.get("llm_provider") or "").lower()
    url = str(cfg.get("llm_url") or "").strip()
    if provider == "ollama" and url:
        return url.rstrip("/")
    if url and any(h in url for h in ("localhost", "127.0.0.1", "::1")):
        # Custom/local endpoint already configured — respect it.
        return url.rstrip("/")
    return str(PROVIDERS["ollama"]["base_url"]).rstrip("/")


def _installed_models(base_url: str) -> list[str]:
    import requests
    try:
        resp = requests.get(base_url.rstrip("/") + "/api/tags", timeout=3)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    names = []
    for m in data.get("models") or []:
        name = str(m.get("name") or "").strip()
        if name:
            names.append(name)
    names.sort()
    return names


def resolve() -> dict:
    """{'ok', 'url', 'model', 'source', 'error'} for the enhancement model."""
    base = _ollama_base()
    installed = _installed_models(base)
    if not installed:
        return {"ok": False, "url": base, "model": "", "source": "",
                "error": (f"Ollama is not reachable at {base}. Prompt "
                          "enhancement is optional — generation still works.")}

    from core.image_studio import settings
    studio = settings.load()
    chosen, source = "", ""
    override = str(studio.get("prompt_model") or "").strip()
    if override:
        if override in installed:
            return {"ok": True, "url": base, "model": override,
                    "source": "AI Image Studio setting", "error": ""}
        chosen, source = "", ""

    try:
        from core.config_store import load as load_config
        cfg = load_config()
    except Exception:
        cfg = {}

    if not chosen and str(cfg.get("llm_provider") or "").lower() == "ollama":
        candidate = str(cfg.get("llm_model") or "").strip()
        if candidate in installed:
            chosen, source = candidate, "configured chat model"

    if not chosen:
        for task in ("brain", "code_helper", "dev_agent", "file_processor"):
            entry = (cfg.get("task_models") or {}).get(task) or {}
            if str(entry.get("provider") or "").lower() != "ollama":
                continue
            candidate = str(entry.get("model") or "").strip()
            if candidate in installed:
                chosen, source = candidate, f"{task} model"
                break

    if not chosen:
        # Last resort: any installed model the server reports. This is a real
        # model id from the running server, not a hard-coded name.
        chosen, source = installed[0], "first installed Ollama model"

    return {"ok": True, "url": base, "model": chosen, "source": source,
            "error": "", "installed": installed}


def _clean(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text).strip()
    text = _PREFIXES.sub("", text)
    text = text.strip().strip('"').strip("'").strip()
    text = " ".join(text.split())
    return text[:1500]


def enhance(prompt: str, timeout: float = 120.0) -> dict:
    """Return {'ok', 'prompt', 'model', 'note'} or {'ok': False, 'error'}."""
    original = " ".join(str(prompt or "").split())
    if not original:
        return {"ok": False, "error": "There is no prompt to enhance."}
    resolved = resolve()
    if not resolved.get("ok"):
        return {"ok": False, "error": resolved.get("error", "Ollama unavailable.")}

    try:
        from brain.providers.openai_compat import OpenAICompatProvider
        provider = OpenAICompatProvider(
            base_url=resolved["url"], model=resolved["model"], timeout=timeout)
        raw = provider.generate(
            original,
            system=_SYSTEM + "\n\nDescription: " + original,
            temperature=0.7,
            max_tokens=320,
        )
    except Exception as exc:
        return {"ok": False,
                "error": f"{resolved['model']} could not enhance the prompt: "
                         f"{str(exc)[:200]}"}

    enhanced = _clean(raw)
    if len(enhanced) < 10:
        return {"ok": False,
                "error": "The local model returned nothing usable."}
    return {"ok": True, "prompt": enhanced, "model": resolved["model"],
            "source": resolved.get("source", ""),
            "note": "Generated by a local Ollama model; the original prompt is "
                    "kept with the generation record."}


__all__ = ["enhance", "resolve", "EnhanceError"]
