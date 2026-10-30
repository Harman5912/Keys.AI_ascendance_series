import json
import sys
from pathlib import Path

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"


# All reads and writes go through core.config_store: one lock across the
# read-modify-write cycle, atomic replacement, and no way for this module to
# drop the provider keys or OAuth tokens that core/api_config.py and
# core/firebase_client.py keep in the same file.
def _store():
    sys.path.insert(0, str(BASE_DIR))
    from core import config_store
    return config_store

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def config_exists() -> bool:
    return CONFIG_FILE.exists()

def save_api_keys(gemini_api_key: str) -> None:
    _store().update({"gemini_api_key": (gemini_api_key or "").strip()})

def load_api_keys() -> dict:
    return _store().load()

def get_gemini_key() -> str | None:
    return load_api_keys().get("gemini_api_key")

def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)


def get_assistant_name() -> str:
    """Return the configured assistant name, or 'JARVIS' if not set."""
    return load_api_keys().get("assistant_name", "JARVIS") or "JARVIS"


def get_user_name() -> str:
    """Return the configured user name for addressing."""
    return load_api_keys().get("user_name", "")


def save_assistant_config(assistant_name: str, user_name: str) -> None:
    """Persist assistant name and user name to config."""
    _store().update({
        "assistant_name": (assistant_name or "").strip() or "JARVIS",
        "user_name": (user_name or "").strip(),
    })


# ── Assistant voice ──────────────────────────────────────────────────────────
# Gemini Live prebuilt voices. Names are proper nouns — identical in every
# language, so this list is safe to show verbatim in any locale.
AVAILABLE_VOICES = ["Charon", "Puck", "Kore", "Fenrir", "Aoede"]
DEFAULT_VOICE    = "Charon"


def get_voice() -> str:
    """Return the configured Live voice, falling back to the default if unset
    or if the stored value is not a voice we recognise."""
    v = load_api_keys().get("voice_name", DEFAULT_VOICE) or DEFAULT_VOICE
    return v if v in AVAILABLE_VOICES else DEFAULT_VOICE


def save_voice(voice_name: str) -> None:
    """Persist the chosen Live voice. Unknown names collapse to the default so a
    bad value can never reach the API and break the session."""
    v = (voice_name or "").strip()
    _store().update({"voice_name": v if v in AVAILABLE_VOICES else DEFAULT_VOICE})


def get_brief_enabled() -> bool:
    return load_api_keys().get("morning_brief_enabled", True)


def save_brief_enabled(enabled: bool) -> None:
    _store().update({"morning_brief_enabled": bool(enabled)})


# ── Wake word (optional, local) ─────────────────────────────────────────────
# Opt-in: absent from the config means OFF. The default model is the
# pretrained "hey_jarvis"; a custom phrase (e.g. "Hey Keys") needs its own
# openwakeword model, whose id or .onnx path goes in `wake_model`.

def get_wake_enabled() -> bool:
    return bool(load_api_keys().get("wake_enabled", False))


def save_wake_enabled(enabled: bool) -> None:
    _patch_config(wake_enabled=bool(enabled))


def get_wake_model() -> str:
    return (load_api_keys().get("wake_model", "") or "").strip() or "hey_jarvis"


def save_wake_model(model_name: str) -> None:
    _patch_config(wake_model=(model_name or "").strip())


def get_wake_threshold() -> float:
    try:
        return float(load_api_keys().get("wake_threshold", 0.5))
    except Exception:
        return 0.5


def save_wake_threshold(value: float) -> None:
    try:
        _patch_config(wake_threshold=float(value))
    except Exception:
        pass


def get_barge_in_enabled() -> bool:
    """Let the user interrupt Keys.ai by voice (uses the self-echo guard)."""
    return bool(load_api_keys().get("barge_in_enabled", False))


def save_barge_in_enabled(enabled: bool) -> None:
    _patch_config(barge_in_enabled=bool(enabled))


# ── HUD theme ───────────────────────────────────────────────────────────────

def get_theme() -> str:
    return (load_api_keys().get("theme", "") or "gold").strip()


def save_theme(name: str) -> None:
    _patch_config(theme=(name or "gold").strip())


# ── Audio devices ────────────────────────────────────────────────────────────
# Stored as device NAMES, not sounddevice indices. Indices shift every time a
# USB device is plugged in or removed, so a saved index silently starts pointing
# at a different microphone. The empty string means "system default", which is
# both the factory setting and what an unresolvable saved device falls back to —
# so unplugging a headset degrades to the built-in speakers instead of crashing.

def _patch_config(**fields) -> None:
    """Read-modify-write one or more keys in api_keys.json.

    Every setter in this file open-coded this. Collapsing it here means a new
    setting is one line, there is one place where a corrupt config file is
    handled instead of nine, and the write is serialised with the other two
    modules that touch the same file.
    """
    _store().update(fields)


def get_input_device() -> str:
    """Microphone device name, or '' for the system default."""
    return (load_api_keys().get("input_device", "") or "").strip()


def save_input_device(name: str) -> None:
    _patch_config(input_device=(name or "").strip())


def get_output_device() -> str:
    """Speaker device name, or '' for the system default."""
    return (load_api_keys().get("output_device", "") or "").strip()


def save_output_device(name: str) -> None:
    _patch_config(output_device=(name or "").strip())


def get_plugin_enabled(plugin_name: str) -> bool:
    """Plugins are enabled by default the moment they're discovered (opt-out model)."""
    return load_api_keys().get("plugins_enabled", {}).get(plugin_name, True)


def save_plugin_enabled(plugin_name: str, enabled: bool) -> None:
    def _mutate(data: dict) -> None:
        plugins_cfg = data.get("plugins_enabled")
        if not isinstance(plugins_cfg, dict):
            plugins_cfg = {}
        plugins_cfg[plugin_name] = bool(enabled)
        data["plugins_enabled"] = plugins_cfg

    _store().update(mutate=_mutate)