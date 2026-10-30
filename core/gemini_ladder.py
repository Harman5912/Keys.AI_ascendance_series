"""
core/gemini_ladder.py — one ladder of Gemini models for every one-shot call.

Why this exists
---------------
Before this module, one-shot Gemini calls were made in several places, each
naming its own model and (mostly) with **no timeout at all**. When a single
model alias went unwell the call did not fail — it *hung*, and it paid the same
12–15 s penalty on every subsequent call because nothing remembered the failure.

This module gives every one-shot call the same behaviour:

* **One ladder, ordered by measured latency** — fastest first, so a quota or a
  timeout steps to the next rung instead of failing.
* **A deadline on every attempt** — a call can never hang forever.
* **Cooldowns that remember** — a failing model is rested for a length of time
  that matches *why* it failed (quota refills fast; an outage outlasts a retry;
  a 404 will not fix itself in a minute).
* **Key rotation** — the primary key is tried across the ladder, then each backup
  key, so a rate-limited key does not take the assistant down.

The ladder is deliberately *not* used for the Live voice model: Live models are
not drop-in replacements and must be managed separately by the caller.

Config (optional), in config/api_keys.json:
    "gemini_ladder": ["gemini-2.5-flash", ...]   # override the default order
"""

from __future__ import annotations

import re
import socket
import threading
import time
from typing import Callable, Optional

# ── the ladder (fastest → slowest, from measured response times) ────────────
DEFAULT_LADDER: list[str] = [
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-3-flash-preview",
    "gemini-3.6-flash",
    "gemini-2.5-pro",
]

DEFAULT_TIMEOUT = 12.0  # seconds — every attempt carries at least this deadline

# ── cooldowns: how long a failure is believed (seconds) ────────────────────
COOLDOWN_QUOTA     = 5 * 60        # 429 — quotas refill
COOLDOWN_OUTAGE    = 30 * 60       # 503 / 504 — an outage outlasts a retry
COOLDOWN_NOTFOUND  = 6 * 60 * 60   # 404 — the key will not gain access soon
COOLDOWN_AUTH      = 30 * 60       # 401 / 403
COOLDOWN_TIMEOUT   = 2 * 60        # our own deadline tripped (may just be slow)
COOLDOWN_BADREQ    = 60            # 400 — usually a transient request problem
COOLDOWN_UNKNOWN   = 60            # anything else

_lock = threading.RLock()
_cooldowns: dict[str, float] = {}          # model -> unix ts it becomes usable
_stats: dict[str, dict] = {}               # model -> {ok,fail,last_ms,last_err}


# ── error classification ───────────────────────────────────────────────────

def _status_code(exc: BaseException) -> int | None:
    """Best-effort HTTP status extraction from a google-genai exception."""
    for attr in ("code", "status_code", "status"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    # Fall back to parsing the message: "429", "503 UNAVAILABLE", ...
    m = re.search(r"\b(4\d\d|5\d\d)\b", str(exc))
    return int(m.group(1)) if m else None


def classify(exc: BaseException) -> tuple[str, int]:
    """Return (kind, cooldown_seconds) for a failed attempt."""
    msg = str(exc).upper()
    if isinstance(exc, (socket.timeout, TimeoutError)) or "TIMED OUT" in msg \
            or "TIMEOUT" in msg and "DEADLINE_EXCEEDED" not in msg:
        return "timeout", COOLDOWN_TIMEOUT
    if "DEADLINE_EXCEEDED" in msg:
        return "outage", COOLDOWN_OUTAGE
    code = _status_code(exc)
    if code == 429 or "RESOURCE_EXHAUSTED" in msg or "QUOTA" in msg or "RATE LIMIT" in msg:
        return "quota", COOLDOWN_QUOTA
    if code in (503, 504) or "UNAVAILABLE" in msg or "OVERLOADED" in msg:
        return "outage", COOLDOWN_OUTAGE
    if code == 404 or "NOT_FOUND" in msg or "NOT FOUND" in msg:
        return "notfound", COOLDOWN_NOTFOUND
    if code in (401, 403) or "PERMISSION_DENIED" in msg or "UNAUTHENTICATED" in msg \
            or "API KEY" in msg or "API_KEY" in msg:
        return "auth", COOLDOWN_AUTH
    if code == 400 or "INVALID_ARGUMENT" in msg:
        return "badrequest", COOLDOWN_BADREQ
    return "unknown", COOLDOWN_UNKNOWN


# ── ladder / cooldown bookkeeping ──────────────────────────────────────────

def _config_ladder() -> list[str]:
    """The configured ladder (api_keys.json → gemini_ladder) or the default."""
    try:
        from core.api_config import load_config
        cfg = load_config()
        override = cfg.get("gemini_ladder")
        if isinstance(override, list) and override:
            return [str(m) for m in override if str(m).strip()]
    except Exception:
        pass
    return list(DEFAULT_LADDER)


def _cooling(model: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return _cooldowns.get(model, 0.0) > now


def _rest(model: str, seconds: int) -> None:
    with _lock:
        _cooldowns[model] = time.time() + seconds


def reset_cooldowns(model: str | None = None) -> None:
    """Clear cooldowns (all, or one model). Used by tests and the AI settings UI."""
    with _lock:
        if model:
            _cooldowns.pop(model, None)
        else:
            _cooldowns.clear()


def models_to_try(preferred: str | None = None) -> list[str]:
    """Ordered candidate list: `preferred` first, then the ladder, skipping any
    model currently in cooldown."""
    out: list[str] = []
    for m in ([preferred] if preferred else []) + _config_ladder():
        if m and m not in out and not _cooling(m):
            out.append(m)
    return out


def _keys() -> list[str]:
    """Primary Gemini key followed by any backup keys (rotation order)."""
    try:
        from core.api_config import get_api_key, get_backup_api_keys
        keys = [get_api_key("gemini")] + list(get_backup_api_keys("gemini"))
        return [k for k in keys if k and k.strip()]
    except Exception:
        return []


# ── the actual call ────────────────────────────────────────────────────────

def _raw_generate(model: str, prompt: str, system: str | None,
                  temperature: float, max_tokens: int | None,
                  timeout: float, api_key: str) -> str:
    """One attempt against one model with one key. Raises on failure."""
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=int(timeout * 1000)),
    )
    contents = []
    if system:
        contents.append({"text": system})
    contents.append({"text": prompt})
    cfg: dict = {"temperature": temperature}
    if max_tokens:
        cfg["max_output_tokens"] = max_tokens
    resp = client.models.generate_content(model=model, contents=contents, config=cfg)
    text = getattr(resp, "text", "") or ""
    return text.strip()


def generate(prompt: str, *,
             model: str | None = None,
             system: str | None = None,
             temperature: float = 0.2,
             max_tokens: int | None = None,
             timeout: float = DEFAULT_TIMEOUT,
             api_key: str | None = None,
             on_event: Optional[Callable[[dict], None]] = None) -> str:
    """Run `prompt` through the ladder and return the first successful answer.

    Steps to the next rung on failure and rests the failed model for a length
    of time matching the failure. Tries the primary key across the whole ladder,
    then each backup key. Raises the last error only if every combination fails.
    """
    # ── Persona injection ────────────────────────────────────────────────────
    try:
        from core.persona import get_system_prompt_addon, infer_mode
        _mode = infer_mode(prompt[:200])
        _persona = get_system_prompt_addon(mode=_mode, task=prompt[:200])
        if system:
            system = _persona + "\n\n" + system
        else:
            system = _persona
    except Exception:
        pass
    # ────────────────────────────────────────────────────────────────────────

    ladder = models_to_try(model)
    if not ladder:
        # Everything is cooling — clear the stale cooldowns and retry the ladder.
        reset_cooldowns()
        ladder = models_to_try(model)

    keys = [api_key] if api_key else _keys()
    if not keys:
        raise RuntimeError("No Gemini API key configured (config/api_keys.json).")

    last_exc: BaseException | None = None
    for key in keys:
        for m in ladder:
            if _cooling(m):
                continue
            t0 = time.monotonic()
            try:
                text = _raw_generate(m, prompt, system, temperature,
                                     max_tokens, timeout, key)
                dt = time.monotonic() - t0
                with _lock:
                    st = _stats.setdefault(m, {"ok": 0, "fail": 0,
                                               "last_ms": 0.0, "last_err": ""})
                    st["ok"] += 1
                    st["last_ms"] = round(dt * 1000, 1)
                    st["last_err"] = ""
                    _cooldowns.pop(m, None)  # a success clears any lingering rest
                if on_event:
                    try:
                        on_event({"kind": "ok", "model": m, "ms": round(dt * 1000, 1)})
                    except Exception:
                        pass
                return text
            except Exception as e:  # noqa: BLE001 — classify then continue
                last_exc = e
                kind, cooldown = classify(e)
                # An auth/quota error is a *key* problem — do not rest the model,
                # step to the next key immediately.
                if kind in ("auth", "quota"):
                    with _lock:
                        st = _stats.setdefault(m, {"ok": 0, "fail": 0,
                                                   "last_ms": 0.0, "last_err": ""})
                        st["fail"] += 1
                        st["last_err"] = f"{kind}"
                    if on_event:
                        try:
                            on_event({"kind": kind, "model": m,
                                      "error": str(e)[:200]})
                        except Exception:
                            pass
                    break  # next key
                _rest(m, cooldown)
                with _lock:
                    st = _stats.setdefault(m, {"ok": 0, "fail": 0,
                                               "last_ms": 0.0, "last_err": ""})
                    st["fail"] += 1
                    st["last_err"] = kind
                if on_event:
                    try:
                        on_event({"kind": kind, "model": m, "rest_s": cooldown,
                                  "error": str(e)[:200]})
                    except Exception:
                        pass
                continue

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Gemini ladder exhausted with no attempt made.")


def status() -> dict:
    """Snapshot for the UI / demo: cooldowns, per-model stats, current ladder."""
    now = time.time()
    with _lock:
        cooling = {m: round(ts - now, 1) for m, ts in _cooldowns.items() if ts > now}
        stats = {m: dict(v) for m, v in _stats.items()}
    return {"ladder": _config_ladder(), "cooling": cooling, "stats": stats}
