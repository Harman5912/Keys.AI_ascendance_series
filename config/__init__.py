# config/__init__.py
import json, os, platform
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "api_keys.json"

def _platform_os() -> str:
    """Auto-detect OS when config file is absent."""
    return {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(
        platform.system(), "linux"
    )

def get_config() -> dict:
    """The app config, with encrypted credentials decrypted.

    This used to read the JSON directly, so any credential moved into
    encrypted storage would look absent to every caller of this module.
    """
    try:
        from core.config_store import load as _load  # local: avoid import cycles
        return _load()
    except Exception:
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

def get_os() -> str:
    """Returns: 'windows' | 'mac' | 'linux'"""
    return get_config().get("os_system", _platform_os()).lower()

def is_windows() -> bool: return get_os() == "windows"
def is_mac()     -> bool: return get_os() == "mac"
def is_linux()   -> bool: return get_os() == "linux"
