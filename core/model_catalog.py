"""
core/model_catalog.py — AI provider & model catalog for Keys.ai.

Single source of truth for the providers Keys.ai can talk to and the model
list the UI/tools offer for each one. Every provider here maps to an
`LLMProvider` built by brain/providers (see get_provider()).

Providers:
    gemini     — Google Gemini (also powers the Live voice session)
    nvidia     — NVIDIA NIM (https://integrate.api.nvidia.com/v1)
    anthropic  — Anthropic Claude (https://api.anthropic.com)
    openrouter — OpenRouter aggregation (https://openrouter.ai/api/v1)
    openai     — OpenAI (https://api.openai.com/v1)
    ollama     — local Ollama (default http://localhost:11434)

Each provider lists ~40 real model IDs (the ones actually valid on that
endpoint as of writing). The model dropdown is editable, so users can
always type a brand-new model id too.
"""

from __future__ import annotations

# ── Provider registry ──────────────────────────────────────────────────────
# key_field:  config/api_keys.json key that holds the API key (None = keyless)
# base_url:   default endpoint the OpenAI-compatible providers talk to
# docs_url:   where to get a key
# placeholder: hint shown in the API key input
PROVIDERS: dict[str, dict] = {
    "gemini": {
        "label": "Google Gemini",
        "key_field": "gemini_api_key",
        "base_url": "",
        "docs_url": "https://aistudio.google.com/apikey",
        "placeholder": "AIza...",
        "needs_key": True,
        "default_model": "gemini-2.5-flash",
        "models": [
            # Gemma 4 on the Gemini API (same google-genai client/API key).
            "gemma-4-31b-it", "gemma-4-26b-a4b-it",
            "gemini-2.5-pro", "gemini-2.5-pro-001", "gemini-2.5-pro-002",
            "gemini-2.5-pro-003", "gemini-2.5-pro-preview-03-25",
            "gemini-2.5-pro-preview-05-20",
            "gemini-2.5-flash", "gemini-2.5-flash-001", "gemini-2.5-flash-002",
            "gemini-2.5-flash-003", "gemini-2.5-flash-preview-04-17",
            "gemini-2.5-flash-preview-06-05",
            "gemini-2.5-flash-lite", "gemini-2.5-flash-lite-001",
            "gemini-2.5-flash-lite-002", "gemini-2.5-flash-lite-preview-05-06",
            "gemini-2.5-flash-thinking-preview",
            "gemini-2.5-flash-thinking-preview-05-06",
            "gemini-2.5-flash-thinking-exp-01-15",
            "gemini-2.5-flash-native-audio-preview",
            "gemini-2.5-flash-native-audio-preview-04-17",
            "gemini-2.5-flash-native-audio-preview-06-05",
            "gemini-2.5-flash-native-audio-preview-12-2025",
            "gemini-2.0-flash", "gemini-2.0-flash-001",
            "gemini-2.0-flash-lite", "gemini-2.0-flash-lite-001",
            "gemini-2.0-flash-exp", "gemini-2.0-flash-exp-01-21",
            "gemini-2.0-flash-thinking-exp",
            "gemini-2.0-flash-thinking-exp-01-21",
            "gemini-2.0-flash-thinking-exp-1219",
            "gemini-2.0-pro-exp", "gemini-2.0-pro-exp-02-05",
            "gemini-2.0-flash-exp-image-generation",
            "gemini-1.5-pro", "gemini-1.5-pro-001", "gemini-1.5-pro-002",
            "gemini-1.5-flash", "gemini-1.5-flash-001", "gemini-1.5-flash-002",
            "gemini-1.5-flash-8b", "gemini-1.5-flash-8b-001",
            "gemini-1.5-flash-lite",
        ],
    },
    "nvidia": {
        "label": "NVIDIA NIM",
        "key_field": "nvidia_api_key",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "docs_url": "https://build.nvidia.com",
        "placeholder": "nvapi-...",
        "needs_key": True,
        "default_model": "nvidia/llama-3.1-nemotron-70b-instruct",
        "models": [
            "nvidia/llama-3.1-nemotron-ultra-253b-v1",
            "nvidia/llama-3.3-nemotron-super-49b-v1",
            "nvidia/llama-3.1-nemotron-70b-instruct",
            "nvidia/llama-3.1-nemotron-70b-instruct-preview",
            "nvidia/nemotron-4-340b-instruct",
            "meta/llama-3.3-70b-instruct",
            "meta/llama-3.1-405b-instruct",
            "meta/llama-3.1-70b-instruct",
            "meta/llama-3.1-8b-instruct",
            "meta/llama-3.2-3b-instruct",
            "meta/llama-3.2-1b-instruct",
            "meta/llama-3.2-11b-vision-instruct",
            "meta/llama-3.2-90b-vision-instruct",
            "deepseek-ai/deepseek-r1",
            "deepseek-ai/deepseek-r1-distill-llama-70b",
            "deepseek-ai/deepseek-r1-distill-qwen-32b",
            "deepseek-ai/deepseek-v3",
            "deepseek-ai/deepseek-v2.5",
            "qwen/qwen2.5-72b-instruct",
            "qwen/qwen2.5-coder-32b-instruct",
            "qwen/qwen2.5-7b-instruct",
            "qwen/qwq-32b",
            "mistralai/mistral-large",
            "mistralai/mixtral-8x22b-instruct",
            "mistralai/mistral-7b-instruct-v0.3",
            "microsoft/phi-4",
            "microsoft/phi-3.5-mini-instruct",
            "microsoft/phi-3-medium-128k-instruct",
            "google/gemma-2-27b-it",
            "google/gemma-2-9b-it",
            "google/gemma-2-2b-it",
            "databricks/dbrx-instruct",
            "ai21labs/jamba-1-5-large",
            "ai21labs/jamba-1-5-mini",
            "cohere/command-r-plus",
            "baichuan-inc/baichuan2-13b-chat",
            "01-ai/yi-1.5-34b-chat",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "minimax/minimax-01",
            "Qwen/Qwen3-32B",
            "nvidia/phi-3.5-mini-instruct",
        ],
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "key_field": "anthropic_api_key",
        "base_url": "https://api.anthropic.com",
        "docs_url": "https://console.anthropic.com/settings/keys",
        "placeholder": "sk-ant-...",
        "needs_key": True,
        "default_model": "claude-sonnet-4-5",
        "models": [
            "claude-sonnet-4-5", "claude-sonnet-4-5-20250929",
            "claude-opus-4-1", "claude-opus-4-1-20250805",
            "claude-opus-4", "claude-opus-4-20250514",
            "claude-sonnet-4", "claude-sonnet-4-20250514",
            "claude-haiku-4-5", "claude-haiku-4-5-20251001",
            "claude-3-7-sonnet", "claude-3-7-sonnet-20250219",
            "claude-3-7-sonnet-latest",
            "claude-3-5-sonnet", "claude-3-5-sonnet-20241022",
            "claude-3-5-sonnet-20240620",
            "claude-3-5-haiku", "claude-3-5-haiku-20241022",
            "claude-3-opus", "claude-3-opus-20240229", "claude-3-opus-latest",
            "claude-3-sonnet", "claude-3-sonnet-20240229",
            "claude-3-haiku", "claude-3-haiku-20240307",
            "claude-2.1", "claude-2.1-20240514",
            "claude-2.0", "claude-2.0-20240514",
            "claude-instant-1.2", "claude-instant-1.2-20240514",
        ],
    },
    "openrouter": {
        "label": "OpenRouter",
        "key_field": "openrouter_api_key",
        "base_url": "https://openrouter.ai/api/v1",
        "docs_url": "https://openrouter.ai/keys",
        "placeholder": "sk-or-v1-...",
        "needs_key": True,
        "default_model": "openai/gpt-4o",
        "models": [
            "openai/gpt-4o", "openai/gpt-4o-mini", "openai/gpt-4.1",
            "openai/gpt-4.1-mini", "openai/gpt-4.1-nano",
            "openai/gpt-4-turbo", "openai/o3", "openai/o3-mini",
            "openai/o4-mini", "openai/o1", "openai/o1-mini",
            "anthropic/claude-3.7-sonnet", "anthropic/claude-3.5-sonnet",
            "anthropic/claude-3.5-haiku", "anthropic/claude-opus-4",
            "anthropic/claude-sonnet-4", "anthropic/claude-haiku-4.5",
            "google/gemini-2.5-pro", "google/gemini-2.5-flash",
            "google/gemini-2.5-flash-lite", "google/gemini-2.0-flash-001",
            "google/gemini-2.5-pro-preview-05-20",
            "meta-llama/llama-3.3-70b-instruct",
            "meta-llama/llama-3.1-405b-instruct",
            "meta-llama/llama-3.1-70b-instruct",
            "meta-llama/llama-3.1-8b-instruct",
            "meta-llama/llama-3.2-3b-instruct",
            "meta-llama/llama-4-maverick", "meta-llama/llama-4-scout",
            "deepseek/deepseek-chat", "deepseek/deepseek-chat-v3-0324",
            "deepseek/deepseek-r1", "deepseek/deepseek-r1-0528",
            "qwen/qwen-2.5-72b-instruct", "qwen/qwen3-235b-a22b",
            "qwen/qwen3-32b", "qwen/qwen3-coder-480b-a35b",
            "mistralai/mistral-large", "mistralai/mistral-small-3.1",
            "mistralai/mistral-7b-instruct", "moonshotai/kimi-k2",
            "moonshotai/kimi-k2-instruct", "x-ai/grok-2", "x-ai/grok-2-1212",
            "x-ai/grok-3", "perplexity/sonar", "perplexity/sonar-pro",
            "cohere/command-r-plus", "nvidia/llama-3.1-nemotron-70b-instruct",
            "microsoft/phi-4", "databricks/dbrx-instruct",
        ],
    },
    "openai": {
        "label": "OpenAI",
        "key_field": "openai_api_key",
        "base_url": "https://api.openai.com/v1",
        "docs_url": "https://platform.openai.com/api-keys",
        "placeholder": "sk-...",
        "needs_key": True,
        "default_model": "gpt-4o",
        "models": [
            "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini",
            "gpt-4.1-nano", "gpt-4-turbo", "gpt-4",
            "gpt-4o-2024-11-20", "gpt-4o-2024-08-06", "gpt-4o-2024-05-13",
            "gpt-4-turbo-2024-04-09", "o1", "o1-mini", "o1-preview",
            "o3", "o3-mini", "o4-mini", "gpt-3.5-turbo",
            "chatgpt-4o-latest",
        ],
    },
    "ollama": {
        "label": "Ollama (local)",
        "key_field": None,
        "base_url": "http://localhost:11434",
        "docs_url": "https://ollama.com/library",
        "placeholder": "",
        "needs_key": False,
        "default_model": "gemma4:12b",
        "models": [
            # Light, tool-capable models verified on this machine first —
            # the settings UI prepends the actually-installed list at runtime.
            "gemma4:12b", "gemma4:e4b", "gemma4",
            "qwen3:8b", "qwen3.5:4b", "qwen3:30b",
            "qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen2.5-coder:14b",
            "qwen2.5-coder:32b", "deepseek-r1:8b", "deepseek-r1:1.5b",
            "tinyllama", "llava", "llama3.2-vision",
            "llama3.3", "llama3.3:70b", "llama3.2", "llama3.2:1b",
            "llama3.2:3b", "llama3.1", "llama3.1:8b", "llama3.1:70b",
            "llama3", "llama3:8b", "llama3:70b",
            "qwen3", "qwen3:4b", "qwen3:8b", "qwen3:14b",
            "qwen3:30b-a3b", "qwen3:32b",
            "qwen2.5", "qwen2.5:0.5b", "qwen2.5:1.5b", "qwen2.5:3b",
            "qwen2.5:7b", "qwen2.5:14b", "qwen2.5:32b", "qwen2.5:72b",
            "qwen2.5-coder", "qwen2.5-coder:7b", "qwen2.5-coder:14b",
            "qwen2.5-coder:32b",
            "gemma3", "gemma3:1b", "gemma3:4b", "gemma3:12b", "gemma3:27b",
            "gemma2", "gemma2:2b", "gemma2:9b", "gemma2:27b",
            "phi4", "phi4-mini", "phi3.5", "phi3",
            "mistral", "mistral:7b", "mixtral", "mixtral:8x7b",
            "deepseek-r1", "deepseek-r1:1.5b", "deepseek-r1:7b",
            "deepseek-r1:8b", "deepseek-r1:14b", "deepseek-r1:32b",
            "deepseek-r1:70b", "deepseek-v2", "deepseek-v2.5",
            "llava", "llava:13b", "tinyllama", "codellama", "codellama:7b",
            "dolphin-mistral", "neural-chat", "starling-lm", "solar",
            "orca-mini",
        ],
    },
    "custom": {
        "label": "Custom (OpenAI-compatible)",
        "key_field": "openai_api_key",
        "base_url": "http://localhost:8000/v1",
        "docs_url": "",
        "placeholder": "optional sk-...",
        "needs_key": False,
        "default_model": "custom-model",
        "models": ["custom-model"],
    },
}

# Order shown in provider dropdowns
PROVIDER_ORDER = ["gemini", "nvidia", "anthropic", "openrouter", "openai",
                  "ollama", "custom"]


def provider_info(provider: str) -> dict:
    """Registry entry for a provider id (falls back to a generic entry)."""
    p = PROVIDERS.get(provider or "")
    if p is not None:
        return p
    return {
        "label": (provider or "custom").upper(),
        "key_field": "openai_api_key",
        "base_url": "http://localhost:11434",
        "docs_url": "",
        "placeholder": "API key",
        "needs_key": False,
        "default_model": "",
        "models": ["custom-model"],
    }


def models_for(provider: str) -> list[str]:
    return list(provider_info(provider).get("models", []))


def provider_labels() -> list[tuple[str, str]]:
    """[(id, label)] for dropdowns, in display order."""
    return [(pid, provider_info(pid)["label"]) for pid in PROVIDER_ORDER]


def key_field_for(provider: str) -> str | None:
    """config/api_keys.json key that stores this provider's API key (None = none)."""
    return provider_info(provider).get("key_field")


def needs_key(provider: str) -> bool:
    return bool(provider_info(provider).get("needs_key", True))


def base_url_for(provider: str) -> str:
    return provider_info(provider).get("base_url", "")


def default_model_for(provider: str) -> str:
    return provider_info(provider).get("default_model", "") or (
        models_for(provider)[0] if models_for(provider) else ""
    )


# ── Ollama auto-detection ─────────────────────────────────────────────────

def ollama_is_running(base_url: str = "") -> bool:
    """Check whether an Ollama server is reachable at the given URL."""
    import urllib.request
    import urllib.error
    url = (base_url or PROVIDERS["ollama"]["base_url"]).rstrip("/")
    try:
        req = urllib.request.Request(url + "/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def detect_ollama_models(base_url: str = "") -> list[str]:
    """Query the local Ollama server and return the list of installed models.
    Falls back to the hardcoded catalog list if the server is unreachable."""
    import urllib.request
    import urllib.error
    url = (base_url or PROVIDERS["ollama"]["base_url"]).rstrip("/")
    try:
        req = urllib.request.Request(url + "/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = __import__("json").loads(resp.read().decode())
        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            if name:
                models.append(name)
        if models:
            models.sort()
            return models
    except Exception:
        pass
    # Fallback: return the hardcoded catalog list
    return list(PROVIDERS["ollama"]["models"])


def ensure_ollama_running(base_url: str = "") -> bool:
    """Ensure the Ollama server is running. Starts it if not reachable.
    Returns True if Ollama is (now) reachable."""
    if ollama_is_running(base_url):
        return True
    # Try to start ollama serve in the background
    import subprocess
    import platform as _plat
    try:
        if _plat.system() == "Windows":
            subprocess.Popen(
                ["ollama", "serve"],
                creationflags=(subprocess.CREATE_NO_WINDOW
                               | subprocess.DETACHED_PROCESS),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    except FileNotFoundError:
        return False  # ollama not installed
    except Exception:
        return False
    # Wait up to 5 seconds for it to come online
    import time
    for _ in range(10):
        time.sleep(0.5)
        if ollama_is_running(base_url):
            return True
    return False


def provider_reachable(provider: str, api_key: str = "") -> bool:
    """Quick check whether a provider's endpoint is reachable.
    For keyless providers (ollama, custom) this just checks the URL.
    For keyed providers it does a lightweight request that won't cost tokens."""
    import urllib.request
    import urllib.error
    info = provider_info(provider)
    url = info.get("base_url", "")
    if not url:
        # Gemini uses a different check
        if provider == "gemini" and api_key:
            try:
                test_url = (f"https://generativelanguage.googleapis.com/"
                            f"v1beta/models?key={api_key}")
                req = urllib.request.Request(test_url, method="GET")
                with urllib.request.urlopen(req, timeout=4) as resp:
                    return resp.status == 200
            except Exception:
                return False
        return False
    if provider == "ollama":
        return ollama_is_running()
    # OpenAI-compatible providers: hit /models with the key
    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(url.rstrip("/") + "/models",
                                     headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=4) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        # 401/403 = server is reachable, just bad key
        return e.code in (401, 403)
    except Exception:
        return False
