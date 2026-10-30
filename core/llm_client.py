"""
core/llm_client.py — Shared LLM client for tools (code_helper, dev_agent, file_processor).

Routes to the correct provider (Gemini, Ollama, OpenAI-compat, Anthropic)
based on the per-task model config. Falls back to Gemini when no config exists.

Usage:
    from core.llm_client import get_llm
    client = get_llm("code_helper")
    response = client.generate("Explain this code: ...")
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_client_cache: dict[str, object] = {}


def get_llm(task: str = "code_helper"):
    """Return an LLMProvider for the given task, cached per task.

    The provider is built from the per-task model config in api_keys.json.
    Falls back to the brain's provider factory when available, or Gemini.
    """
    cache_key = task
    if cache_key in _client_cache:
        return _client_cache[cache_key]

    provider = _build_provider(task)
    _client_cache[cache_key] = provider
    return provider


def invalidate_cache(task: str | None = None):
    """Clear cached clients (call after config changes)."""
    if task:
        _client_cache.pop(task, None)
    else:
        _client_cache.clear()


def complete(task: str, prompt: str, system: str | None = None,
             temperature: float = 0.2, max_tokens: int | None = None) -> str:
    """One text completion through the provider configured for ``task``.

    Tool modules used to build their own Gemini client with a hard-coded model
    id, so changing the provider in Settings moved the chat but left search,
    the dashboard and the vision helpers on Gemini. This is the single entry
    point for plain text: it honours the per-task provider/model, reuses the
    cached client, and raises on failure so the caller can fall back to its own
    offline path rather than receiving a plausible-looking empty string.
    """
    provider = get_llm(task)
    try:
        return provider.generate(prompt, system=system,
                                 temperature=temperature,
                                 max_tokens=max_tokens) or ""
    except TypeError:
        # Providers that predate the keyword signature.
        return provider.generate(prompt) or ""


def _build_provider(task: str):
    """Build an LLMProvider for the given task."""
    # Read task config
    task_cfg = _get_task_config(task)
    provider_name = task_cfg.get("provider", "gemini")
    model = task_cfg.get("model", "gemini-2.5-flash")
    base_url = task_cfg.get("url", "")

    # Try the brain provider factory first (it handles all providers)
    try:
        sys.path.insert(0, str(_base_dir()))
        from brain.providers import get_provider, load_api_config
        api_config = load_api_config()
        # Override the provider/model in the config for this task
        task_api_config = dict(api_config)
        task_api_config["llm_provider"] = provider_name
        task_api_config["llm_model"] = model
        if base_url:
            task_api_config["llm_url"] = base_url
        return get_provider(cfg=None, api_config=task_api_config)
    except Exception as e:
        print(f"[LLM] brain provider failed: {e}, falling back to genai")

    # Fallback: direct genai client (Gemini only)
    return _build_gemini_fallback(task_cfg)


def _get_task_config(task: str) -> dict:
    """Read per-task model config, falling back to global."""
    try:
        sys.path.insert(0, str(_base_dir()))
        from core.api_config import get_task_model
        return get_task_model(task)
    except Exception:
        return {"provider": "gemini", "model": "gemini-2.5-flash", "url": ""}


def _build_gemini_fallback(task_cfg: dict):
    """Fallback: route Gemini one-shot calls through the shared model ladder.

    The ladder (core/gemini_ladder.py) adds a deadline to every attempt, steps
    to the next model when one is quota-limited or unwell, rests a failed model
    for a time matching the failure, and rotates over the configured backup
    keys — so a single bad alias can never hang a tool call.
    """
    model = task_cfg.get("model", "gemini-2.5-flash")

    class _Wrapper:
        def generate(self, prompt, system=None, temperature=0.2,
                     max_tokens=None, timeout=None, **kwargs):
            from core.gemini_ladder import DEFAULT_TIMEOUT, generate as _ladder
            return _ladder(
                prompt,
                model=model,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout or DEFAULT_TIMEOUT,
            )

    return _Wrapper()


def _get_gemini_key() -> str:
    """Read the Gemini API key from config."""
    config_path = _base_dir() / "config" / "api_keys.json"
    try:
        import json
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f).get("gemini_api_key", "")
    except Exception:
        return ""


# ── model warm-up ──────────────────────────────────────────────────────────
# Loading a large local model (e.g. qwen3-coder:30b, 18 GB) can take tens of
# seconds; doing it in the background at app startup hides that latency from
# the first real dev-agent/brain request. Only LOCAL providers benefit —
# hosted APIs have nothing to preload, so they are skipped.

_warmup_state: dict[str, dict] = {}
_warmup_lock = threading.Lock()

_WARM_KEEP_ALIVE    = "60m"                      # ollama residency after warm-up
_OLLAMA_DEFAULT_URL = "http://localhost:11434"


def warmup_status(task: str = "dev_agent") -> dict:
    """Last warm-up result for `task`: {status: idle|warming|ready|failed|skipped, detail}."""
    with _warmup_lock:
        st = _warmup_state.get(task)
        return dict(st) if st else {"status": "idle", "detail": ""}


def warm_up(task: str = "dev_agent", logger=None) -> dict:
    """Load the task's local model into memory NOW so the first real request
    is fast. Blocks until the model is resident (or the attempt fails) —
    call warm_up_async() from startup code instead. Deduplicated: a second
    call while warming/ready is a no-op. Never raises."""
    with _warmup_lock:
        st = _warmup_state.get(task)
        if st and st.get("status") in ("warming", "ready"):
            return dict(st)
        _warmup_state[task] = {"status": "warming", "detail": ""}

    def _log(msg: str):
        print(f"[LLM] {msg}")
        if logger:
            try:
                logger(msg)
            except Exception:
                pass

    def _finish(status: str, detail: str) -> dict:
        with _warmup_lock:
            _warmup_state[task] = {"status": status, "detail": detail}
        _log(f"Warm-up {task}: {status}" + (f" — {detail}" if detail else ""))
        return {"status": status, "detail": detail}

    cfg   = _get_task_config(task)
    prov  = str(cfg.get("provider", "")).lower()
    model = cfg.get("model", "")

    if prov not in ("ollama", "custom"):
        return _finish("skipped", f"provider '{prov}' has nothing to preload")

    if prov == "ollama":
        base = (cfg.get("url") or "").rstrip("/") or _OLLAMA_DEFAULT_URL
        try:
            import requests
            t0 = time.monotonic()
            # Empty-prompt /api/generate is Ollama's documented preload call;
            # keep_alive holds the model resident after the warm-up itself.
            r = requests.post(f"{base}/api/generate",
                              json={"model": model, "prompt": "",
                                    "keep_alive": _WARM_KEEP_ALIVE},
                              timeout=(10, 900))
            r.raise_for_status()
            if r.json().get("done", True):
                dt = time.monotonic() - t0
                return _finish("ready", f"{model} resident in {dt:.1f}s "
                                        f"(keep_alive {_WARM_KEEP_ALIVE})")
            return _finish("failed", "server did not finish loading the model")
        except Exception as e:
            # Native endpoint unavailable (a /v1-only proxy, very old server,
            # ...) — fall through to the OpenAI-compatible path below.
            _log(f"Warm-up native ping failed ({e}); trying OpenAI-compatible endpoint")

    try:
        t0 = time.monotonic()
        llm = get_llm(task)
        llm.generate("Reply with exactly: OK", max_tokens=10)
        dt = time.monotonic() - t0
        return _finish("ready", f"{model} responded in {dt:.1f}s")
    except Exception as e:
        return _finish("failed", str(e)[:200])


def warm_up_async(task: str = "dev_agent", logger=None) -> threading.Thread:
    """Run warm_up() on a daemon thread — fire-and-forget for app startup."""
    t = threading.Thread(target=warm_up, args=(task,), kwargs={"logger": logger},
                         name=f"llm-warmup-{task}", daemon=True)
    t.start()
    return t
