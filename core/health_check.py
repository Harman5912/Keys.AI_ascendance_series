"""
Health Check System - Iron-bound startup verification.
Every subsystem is tested before the app starts.
"""

import json
import platform
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Status(Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class CheckResult:
    name: str
    status: Status
    message: str = ""
    elapsed_ms: float = 0


@dataclass
class HealthReport:
    checks: list = field(default_factory=list)
    total_ms: float = 0

    @property
    def all_ok(self):
        return all(c.status in (Status.OK, Status.SKIP) for c in self.checks)

    @property
    def failures(self):
        return [c for c in self.checks if c.status == Status.FAIL]

    def summary(self):
        lines = []
        lines.append("=" * 60)
        lines.append("  KEYS.AI - SYSTEM HEALTH CHECK")
        lines.append("=" * 60)
        for c in self.checks:
            icon = {"OK": "OK", "WARN": "!!", "FAIL": "XX", "SKIP": "--"}[c.status.value]
            msg = f" -- {c.message}" if c.message else ""
            lines.append(f"  [{icon}] {c.name:30s} {c.elapsed_ms:6.0f}ms{msg}")
        lines.append("=" * 60)
        ok = sum(1 for c in self.checks if c.status == Status.OK)
        fail = sum(1 for c in self.checks if c.status == Status.FAIL)
        warn = sum(1 for c in self.checks if c.status == Status.WARN)
        skip = sum(1 for c in self.checks if c.status == Status.SKIP)
        lines.append(f"  Total: {self.total_ms:.0f}ms | OK: {ok} | Warn: {warn} | Fail: {fail} | Skip: {skip}")
        lines.append("=" * 60)
        return "\n".join(lines)


def _timed(fn):
    t0 = time.perf_counter()
    result = fn()
    elapsed = (time.perf_counter() - t0) * 1000
    return elapsed, result


def _check_python():
    ver = sys.version_info
    if ver < (3, 10):
        return CheckResult("Python Version", Status.FAIL,
                          "Python {}.{} < 3.10 required".format(ver.major, ver.minor))
    return CheckResult("Python Version", Status.OK,
                      "{}.{}.{}".format(ver.major, ver.minor, ver.micro))


def _check_platform():
    os_name = platform.system()
    if os_name not in ("Windows", "Darwin", "Linux"):
        return CheckResult("Platform", Status.FAIL, "Unsupported OS: " + os_name)
    return CheckResult("Platform", Status.OK, os_name)


def _check_config():
    try:
        config_path = Path(__file__).parent.parent / "config" / "api_keys.json"
        if not config_path.exists():
            return CheckResult("API Config", Status.WARN, "config/api_keys.json not found")
        with open(config_path, "r") as f:
            config = json.load(f)
        providers = []
        if config.get("gemini_api_key"):
            providers.append("gemini")
        llm = config.get("llm_provider", "")
        if llm:
            providers.append(llm)
        if not providers:
            return CheckResult("API Config", Status.WARN, "No API keys configured")
        return CheckResult("API Config", Status.OK,
                          "Providers: " + ", ".join(set(providers)))
    except Exception as e:
        return CheckResult("API Config", Status.FAIL, "Config error: " + str(e))


def _check_camera():
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                h, w = frame.shape[:2]
                return CheckResult("Camera", Status.OK, "Working ({}x{})".format(w, h))
            return CheckResult("Camera", Status.WARN, "Opened but no frame")
        return CheckResult("Camera", Status.WARN, "Not available")
    except ImportError:
        return CheckResult("Camera", Status.SKIP, "opencv not installed")
    except Exception as e:
        return CheckResult("Camera", Status.WARN, "Check failed: " + str(e))


def _check_microphone():
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        input_devices = [d for d in devices if d.get("max_input_channels", 0) > 0]
        if not input_devices:
            return CheckResult("Microphone", Status.WARN, "No input devices found")
        default = sd.query_devices(kind="input")
        return CheckResult("Microphone", Status.OK, "Default: " + str(default["name"])[:30])
    except ImportError:
        return CheckResult("Microphone", Status.SKIP, "sounddevice not installed")
    except Exception as e:
        return CheckResult("Microphone", Status.WARN, "Check failed: " + str(e))


def _check_network():
    import urllib.request
    try:
        req = urllib.request.Request("https://www.google.com/generate_204", method="HEAD")
        resp = urllib.request.urlopen(req, timeout=5)
        code = resp.getcode()
        if code in (200, 204):
            return CheckResult("Network", Status.OK, "Internet connected")
        return CheckResult("Network", Status.WARN, "Unexpected response: " + str(code))
    except Exception as e:
        return CheckResult("Network", Status.WARN,
                          "Offline or blocked: " + type(e).__name__)


def _check_dependency(name, import_name=None):
    import_name = import_name or name
    def check():
        try:
            mod = __import__(import_name)
            ver = getattr(mod, "__version__", getattr(mod, "VERSION", "?"))
            return CheckResult("Dependency: " + name, Status.OK, "v" + str(ver))
        except ImportError as e:
            return CheckResult("Dependency: " + name, Status.FAIL,
                              "Not installed: " + str(e))
        except Exception as e:
            return CheckResult("Dependency: " + name, Status.WARN,
                              "Import issue: " + str(e))
    return check


def _check_filesystem():
    try:
        base = Path(__file__).parent.parent
        dirs = [base / "config", base / "memory", base / "core", base / "actions"]
        missing = [d for d in dirs if not d.exists()]
        if missing:
            return CheckResult("Filesystem", Status.WARN,
                              "Missing: " + ", ".join(d.name for d in missing))
        return CheckResult("Filesystem", Status.OK, "All directories present")
    except Exception as e:
        return CheckResult("Filesystem", Status.FAIL, "Check failed: " + str(e))


def _check_permissions():
    if platform.system() != "Windows":
        return CheckResult("Permissions", Status.SKIP, "Windows-only check")
    try:
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
        return CheckResult("Permissions", Status.OK,
                          "Admin" if is_admin else "Normal user (OK)")
    except Exception:
        return CheckResult("Permissions", Status.SKIP, "Could not check")


def run_health_check(verbose=False):
    """Run all health checks and return a comprehensive report."""
    report = HealthReport()
    start_time = time.perf_counter()

    checks = [
        ("Python Version", _check_python),
        ("Platform", _check_platform),
        ("Filesystem", _check_filesystem),
        ("API Config", _check_config),
        ("Network", _check_network),
        ("Camera", _check_camera),
        ("Microphone", _check_microphone),
        ("Permissions", _check_permissions),
        ("PyQt6", _check_dependency("PyQt6")),
        ("Google GenAI", _check_dependency("google.genai")),
        ("SoundDevice", _check_dependency("sounddevice")),
        ("Pillow", _check_dependency("Pillow", "PIL")),
        ("OpenCV", _check_dependency("OpenCV", "cv2")),
        ("PSUtil", _check_dependency("PSUtil", "psutil")),
    ]

    for name, check_fn in checks:
        elapsed, result = _timed(check_fn)
        result.elapsed_ms = elapsed
        report.checks.append(result)
        if verbose:
            icon = {"OK": "OK", "WARN": "!!", "FAIL": "XX", "SKIP": "--"}[result.status.value]
            print("  [{}] {:30s} {:6.0f}ms  {}".format(icon, name, elapsed, result.message))

    report.total_ms = (time.perf_counter() - start_time) * 1000
    return report


if __name__ == "__main__":
    report = run_health_check(verbose=True)
    print(report.summary())
