"""
core/crown_bridge.py — Keys.AI ⇄ Dev Agent (Crown Code Terminal Agent) headless bridge.

Keys.AI is a Python/PyQt6 app; the Dev Agent is the Crown Code Terminal Agent
panel in the creation workspace. This module runs the Dev Agent's real agent loop
(its agent loop, tool registry, provider registry, CrownRouter and Ollama provider)
as a managed subprocess and exchanges newline-delimited JSON events with it.

It also provides local-model setup helpers (detect Ollama, pick/pull a model,
verify it) used by actions/crown_code.py. The preferred local model is
gemma4:12b on this machine — it emits native tool calls and finished a real file
build through the bridge. The qwen models remain as fallbacks for installs that
do not have Gemma 4 yet.

Crown Code source lives outside this project and is only READ from (a single
additive entry file, src/headless.ts, is compiled to dist-headless/headless.js).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "crown_code.json"

# Default Crown Code checkout. Override with the CROWN_CODE_DIR env var or
# config/crown_code.json {"crown_dir": "..."}.
_DEFAULT_CROWN_DIR = r"C:\Users\harma\Desktop\PROJECTS\Crown CODE"
_DEFAULT_OLLAMA_URL = "http://localhost:11434"
# Preference order for local coding models. Ordered for models that are
# actually usable: they must emit NATIVE tool calls (verified against Ollama's
# chat API — qwen2.5-coder:3b and qwen3.5:4b only write the call as prose and
# therefore do nothing) and they must be fast enough to run a real task. The
# large models stay in the list but last: on a machine without GPU offload a 30B
# decodes at a few tokens/second, which makes multi-file work impractical.
# gemma4:12b is first: it emits native tool calls and finished a real file
# build through the bridge (verified on this machine). The qwen models stay as
# fallbacks for installs that do not have Gemma 4 yet.
_PREFERRED_MODELS = (
    "gemma4:12b",
    "gemma4:e4b",
    "gemma4",
    "qwen3:8b",
    "qwen3:4b",
    "qwen2.5-coder:7b",
    "qwen2.5-coder:14b",
    "qwen3-coder:30b",
    "qwen2.5-coder:32b",
    "qwen3-coder",
    "qwen2.5-coder",
    "qwen3.5:4b",
    "deepseek-coder-v2",
    "codellama",
)


# ── Config ────────────────────────────────────────────────────────────────

def load_config() -> dict:
    """Read config/crown_code.json, merged over defaults. Never raises."""
    cfg = {
        "crown_dir": os.environ.get("CROWN_CODE_DIR", _DEFAULT_CROWN_DIR),
        "provider": "ollama",
        "model": "",
        "ollama_url": os.environ.get("OLLAMA_HOST", _DEFAULT_OLLAMA_URL),
        "policy": "safe",
        "max_iterations": 30,
        "workspace": "",
    }
    try:
        if CONFIG_PATH.exists():
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update({k: v for k, v in raw.items() if v not in (None, "")})
    except Exception:
        pass
    return cfg


def save_config(updates: dict) -> None:
    """Persist selected options so they are reused on the next launch."""
    try:
        current = {}
        if CONFIG_PATH.exists():
            current = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(current, dict):
                current = {}
        current.update(updates)
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[CrownBridge] Could not save config: {e}")


# ── Locating the Crown Code checkout / runtime ────────────────────────────

def crown_dir() -> Path:
    return Path(load_config()["crown_dir"])


def headless_entry() -> Path:
    return crown_dir() / "dist-headless" / "headless.js"


def node_exe() -> str:
    for name in ("node", "node.exe"):
        p = shutil.which(name)
        if p:
            return p
    return ""


def npx_exe() -> str:
    for name in ("npx", "npx.cmd", "npx.exe"):
        p = shutil.which(name)
        if p:
            return p
    return ""


def ensure_built(log=None) -> tuple[bool, str]:
    """Ensure dist-headless/headless.js exists AND is newer than the Crown Code
    sources; rebuild it with tsup when missing or stale.

    Returns (ok, message). Only ever ADDS/REFRESHES an artifact — the original
    Crown Code checkout is not modified beyond its own dist-headless output.
    """
    entry = headless_entry()
    src = crown_dir() / "src" / "headless.ts"
    if not src.exists():
        return False, (f"Crown Code headless source not found at {src}. "
                       f"Expected a Crown Code checkout (set crown_dir in config/crown_code.json).")

    def _src_mtime() -> float:
        """Newest mtime across the entry file and its real dependencies."""
        newest = src.stat().st_mtime
        # Providers / tools / agent the entry imports — a change there must
        # also trigger a rebuild, otherwise Keys.AI runs a stale bundle.
        for sub in ("providers", "agent", "tools", "app"):
            d = crown_dir() / "src" / sub
            if not d.exists():
                continue
            for p in d.rglob("*"):
                if p.is_file() and p.suffix in (".ts", ".tsx"):
                    try:
                        newest = max(newest, p.stat().st_mtime)
                    except OSError:
                        pass
        return newest

    if entry.exists() and entry.stat().st_mtime >= _src_mtime():
        return True, f"headless build present: {entry}"

    node = node_exe()
    if not node:
        return False, "Node.js is not installed or not on PATH — Crown Code requires Node >= 18."

    npx = npx_exe()
    if not npx:
        return False, "npx not found on PATH — cannot build the Crown Code headless entry."

    cmd = [npx, "--no-install", "tsup", str(src), "--format", "esm",
           "--target", "node20", "--out-dir", "dist-headless", "--no-splitting"]
    if log:
        log("Building Crown Code headless bridge...")
    try:
        res = subprocess.run(cmd, cwd=str(crown_dir()), capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=300)
        if res.returncode != 0 or not entry.exists():
            return False, f"headless build failed: {(res.stderr or res.stdout or '')[:400]}"
        return True, f"built {entry}"
    except Exception as e:
        return False, f"headless build error: {e}"


# ── Ollama / local model setup ────────────────────────────────────────────

def _fast_url(url: str) -> str:
    """Point 'localhost' at 127.0.0.1.

    On Windows, resolving localhost tries ::1 first and stalls for ~2s before
    falling back to IPv4 — paid on every model check, so a resident model took
    longer to confirm than to use.
    """
    return (url or "").replace("//localhost", "//127.0.0.1")


def _http_get_json(url: str, timeout: float = 4.0):
    import urllib.request
    url = _fast_url(url)
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 (localhost)
        return json.loads(r.read().decode("utf-8"))


def ollama_installed() -> bool:
    return bool(shutil.which("ollama"))


def ollama_running(url: str = "") -> bool:
    url = (url or load_config()["ollama_url"]).rstrip("/")
    try:
        _http_get_json(f"{url}/api/version")
        return True
    except Exception:
        return False


def start_ollama(log=None) -> bool:
    """Best-effort start of the Ollama server. Never raises."""
    exe = shutil.which("ollama")
    if not exe:
        return False
    if ollama_running():
        return True
    try:
        if log:
            log("Starting Ollama server...")
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen([exe, "serve"], **kwargs)  # noqa: S603
    except Exception as e:
        if log:
            log(f"Could not start Ollama: {e}")
        return False
    for _ in range(20):
        if ollama_running():
            return True
        time.sleep(0.5)
    return ollama_running()


def list_models(url: str = "") -> list[str]:
    url = (url or load_config()["ollama_url"]).rstrip("/")
    try:
        data = _http_get_json(f"{url}/api/tags", timeout=6)
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def pick_model(available: list[str], preferred: str = "") -> str:
    """Choose a coding model: explicit preference → known coder models → any.

    Order of :data:`_PREFERRED_MODELS` wins, so a fast tool-calling model is
    chosen over a huge slow one when both are installed.
    """
    if preferred:
        for m in available:
            if m == preferred or m.split(":")[0] == preferred:
                return m
    for want in _PREFERRED_MODELS:
        for m in available:
            if m == want or m.startswith(want):
                return m
    for m in available:
        if any(k in m.lower() for k in ("coder", "code", "qwen", "deepseek")):
            return m
    return available[0] if available else ""


def model_size_gb(name: str) -> float:
    """Approximate on-disk size in GB for a model tag (for the RAM check)."""
    n = name.lower()
    if "30b" in n or "32b" in n or "34b" in n:
        return 19.0
    if "14b" in n:
        return 9.0
    if "12b" in n:
        return 8.0
    if "8b" in n:
        return 5.2
    if "7b" in n:
        return 4.7
    if "4b" in n:
        return 3.3
    if "3b" in n:
        return 2.0
    if "1b" in n or "tinyllama" in n:
        return 0.7
    return 8.0


def total_ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        return 0.0


def _is_coder(name: str) -> bool:
    return any(k in name.lower() for k in ("coder", "code", "qwen", "deepseek",
                                          "gemma4"))


def recommend_model(available: list[str], preferred: str = "") -> tuple[str, str]:
    """Pick a compatible coding model for this machine's resources.

    An explicit ``preferred`` model is always honoured. Otherwise the best
    available coder model that fits in RAM is chosen; when none fit, the
    smallest coder model is used and a warning is returned. Never assumes a
    30B model will run everywhere.
    """
    ram = total_ram_gb()

    if preferred:
        if not any(m == preferred or m.split(":")[0] == preferred for m in available):
            return preferred, f"{preferred} is not installed yet — it will be pulled."
        model = pick_model(available, preferred)
        return model, _ram_note(model, ram)

    candidates = available or []
    coders = [m for m in candidates if _is_coder(m)] or candidates
    if not coders:
        return "", "No local models installed."

    if ram:
        fits = [m for m in coders if model_size_gb(m) <= ram * 0.75]
        pool = fits or sorted(coders, key=model_size_gb)
    else:
        pool = coders

    model = pick_model(pool)
    return model, _ram_note(model, ram)


def _ram_note(model: str, ram: float) -> str:
    if not ram or not model:
        return ""
    need = model_size_gb(model)
    if need > ram * 0.75:
        return (f"Warning: {model} is ~{need:.0f} GB and this machine has ~{ram:.0f} GB RAM — "
                f"it may run slowly or fail to load. Install a smaller tool-capable "
                f"model, e.g. `ollama pull gemma4:12b`, and set it in "
                f"config/crown_code.json.")
    return ""


def pull_model(model: str, url: str = "", on_progress=None, log=None) -> bool:
    """Pull a model via the Ollama HTTP API, reporting progress. Never raises."""
    import urllib.request
    url = (url or load_config()["ollama_url"]).rstrip("/")
    payload = json.dumps({"name": model}).encode("utf-8")
    req = urllib.request.Request(f"{url}/api/pull", data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3600) as resp:  # noqa: S310
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if on_progress:
                    on_progress(d)
                if log and d.get("status"):
                    log(f"Ollama: {d['status']}")
        return True
    except Exception as e:
        if log:
            log(f"Model pull failed: {e}")
        return False


def verify_model(model: str, url: str = "", timeout: float = 120.0) -> tuple[bool, str]:
    """Run a tiny real inference to confirm the model responds.

    Hybrid/reasoning models (qwen3, gemma4, ...) emit inside their hidden
    reasoning block by default, so thinking is disabled for the probe and the
    token budget is raised. A working model that still only puts content in
    ``thinking`` is reported as not yet verified so the caller can retry or
    fall back instead of claiming a broken model is healthy.
    """
    import urllib.request
    url = (url or load_config()["ollama_url"]).rstrip("/")
    prompt = "Reply with exactly: OK"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"num_predict": 80},
    }
    if any(k in model.lower() for k in ("qwen3", "gemma4", "deepseek")):
        body["think"] = False
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(_fast_url(f"{url}/api/chat"), data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        msg = data.get("message") or {}
        text = (msg.get("content") or "").strip()
        if not text:
            reason = str(data.get("done_reason") or "")
            if (msg.get("thinking") or "").strip():
                return False, ("model answered only inside its reasoning block "
                               f"(done_reason={reason or 'unknown'})")
            return False, f"model returned an empty response (done_reason={reason or 'unknown'})"
        return True, text[:80]
    except Exception as e:
        return False, str(e)[:200]


def resident_models(url: str = "") -> list[str]:
    """Models Ollama currently holds in memory (``/api/ps``)."""
    url = (url or load_config()["ollama_url"]).rstrip("/")
    try:
        data = _http_get_json(f"{url}/api/ps", timeout=4)
        return [str(m.get("name") or m.get("model") or "")
                for m in data.get("models", []) if (m.get("name") or m.get("model"))]
    except Exception:
        return []


def _pin_model(model: str) -> None:
    """Remember the model in crown_code.json — only when it actually changed.

    A write re-encrypts the credential store, so an unchanged value must not
    cost a save on every build.
    """
    try:
        cfg = load_config()
        if cfg.get("model") == model and cfg.get("provider") == "ollama":
            return
        save_config({"model": model, "provider": "ollama"})
    except Exception:
        pass


def model_is_resident(model: str, url: str = "") -> bool:
    """True when ``model`` is already loaded (a probe would measure nothing)."""
    if not model:
        return False
    want = model.strip().lower()
    base = want.split(":")[0]
    for name in resident_models(url):
        n = name.strip().lower()
        if n == want or n.split(":")[0] == base:
            return True
    return False


def preload_model(model: str, url: str = "", timeout: float = 300.0) -> bool:
    """Ask Ollama to load ``model`` now. Never raises.

    ``prompt: ""`` is Ollama's documented load-only call: it does no
    generation, so it costs the model load and nothing else. Doing it here,
    with the console already open and showing "loading", is the difference
    between an honest wait and a build that looks hung on its first token.
    """
    import urllib.request
    url = (url or load_config()["ollama_url"]).rstrip("/")
    payload = json.dumps({"model": model, "prompt": "",
                          "keep_alive": "60m"}).encode("utf-8")
    req = urllib.request.Request(_fast_url(f"{url}/api/generate"), data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            resp.read()
        return True
    except Exception:
        return False


def ensure_local_model(log=None, on_progress=None, preferred: str = "") -> tuple[bool, str]:
    """Full local-model readiness check:
       1. Ollama installed?  2. running?  3. model installed?
       4. pull if missing    5. verify with a real inference.
    Returns (ok, message_or_model).
    """
    cfg = load_config()
    url = cfg["ollama_url"]

    if not ollama_installed():
        return False, ("Ollama is not installed. Install it from "
                       "https://ollama.com/download and restart Keys.AI.")
    if not ollama_running(url):
        if not start_ollama(log):
            return False, (f"Ollama is installed but not reachable at {url}. "
                           f"Start it with 'ollama serve' and retry.")

    available = list_models(url)
    model, note = recommend_model(available, preferred or cfg.get("model", ""))
    if note and log:
        log(note)

    if not model:
        target = preferred or "qwen2.5-coder:7b"
        if log:
            log(f"No local models found — pulling {target} (this may take a while)...")
        if on_progress:
            on_progress({"status": f"pulling {target}"})
        if not pull_model(target, url, on_progress=on_progress, log=log):
            return False, (f"Could not download {target}. Check your internet "
                           f"connection, or run 'ollama pull {target}' manually.")
        model = target

    # Fast path: a model already loaded needs no probe. Probing a resident
    # model cost a round trip on every single build for no information.
    if model_is_resident(model, url):
        if log:
            log(f"Local model ready: {model} (already loaded)")
        _pin_model(model)
        return True, model

    # Cold model: load it first (no generation), so the wait is spent loading
    # rather than timing out an inference that is really just a cold start.
    if on_progress:
        on_progress({"status": f"loading {model}"})
    loaded = preload_model(model, url)
    ok, detail = verify_model(model, url, timeout=60.0 if loaded else 120.0)
    if not ok and loaded and "timed out" in detail.lower():
        # It is installed and loading. Refusing to start here is what made a
        # build look like it never began; a genuinely broken model fails
        # visibly in the run instead.
        if log:
            log(f"Model '{model}' is still loading — starting anyway")
        _pin_model(model)
        return True, model
    if not ok:
        return False, f"Model '{model}' failed a test inference: {detail}"

    if log:
        log(f"Local model ready: {model} (replied {detail!r})")
    _pin_model(model)
    return True, model


def sync_local_models(log=None) -> dict:
    """Startup reconciliation between the AI provider settings and the dev
    engine — runs once at app launch, before model warm-up, so that EVERY time
    Keys.AI opens:

      * Ollama is running (started here when installed but idle),
      * config/crown_code.json pins a model that is actually INSTALLED — an
        "auto"/empty or stale entry resolves to the preferred light model,
      * config/api_keys.json `task_models` (what the AI Provider settings UI
        shows) agrees with it: local tasks pointing at a missing model are
        remapped to an installed one, and `dev_agent` always mirrors Crown
        Code's model.

    Returns {provider, model, installed, changed}; never raises.
    """
    out: dict = {"provider": "", "model": "", "installed": [], "changed": False}
    try:
        cfg = load_config()
        provider = str(cfg.get("provider") or "ollama").lower()
        out["provider"] = provider
        if provider not in ("ollama", "auto", "local"):
            return out          # a hosted dev provider — nothing local to check
        if not ollama_installed():
            return out
        url = cfg["ollama_url"]
        if not ollama_running(url) and not start_ollama(log):
            return out          # offline: ensure_local_model retries on first run
        installed = list_models(url)
        if not installed:
            return out          # nothing installed yet: ensure_local_model pulls
        out["installed"] = installed

        configured = str(cfg.get("model") or "").strip()
        hit = [m for m in installed
               if m == configured or m.split(":")[0] == configured]
        resolved = hit[0] if hit else pick_model(installed)
        if not resolved:
            return out
        if resolved != configured:
            save_config({"model": resolved, "provider": "ollama"})
            out["changed"] = True
            if log:
                log(f"Dev model '{configured or 'auto'}' is not installed — "
                    f"using {resolved} instead.")
        out["model"] = resolved

        # Keep the AI Provider settings (api_keys.json task_models) honest.
        try:
            from core.api_config import get_all_task_models, set_task_model
            tasks = get_all_task_models()
            entries = list(tasks.items())
            if "dev_agent" not in tasks:
                entries.append(("dev_agent", {}))   # crown runs locally: say so
            for task, raw in entries:
                entry = raw or {}
                cur_prov = str(entry.get("provider") or "").lower()
                if task != "dev_agent" and cur_prov not in ("ollama", "local", "auto"):
                    continue                        # hosted task — untouched
                if task == "dev_agent":
                    want = resolved                 # Crown Code IS the dev engine
                else:
                    cur = str(entry.get("model") or "")
                    on_disk = any(m == cur or m.split(":")[0] == cur
                                  for m in installed)
                    want = cur if on_disk else pick_model(installed)
                if want and want != str(entry.get("model") or ""):
                    set_task_model(task, "ollama", want)
                    out["changed"] = True
                    if log:
                        log(f"Settings sync: {task} -> ollama/{want}")
        except Exception as e:                      # never block startup
            if log:
                log(f"task_models sync skipped: {e}")
    except Exception as e:
        if log:
            log(f"Local model sync skipped: {e}")
    return out


# ── The bridge process ────────────────────────────────────────────────────

class CrownBridge:
    """Runs the Crown Code headless bridge and funnels its events."""

    def __init__(self, workspace: str, on_event=None, permission_handler=None,
                 log=None, model: str = "", provider: str = "", ollama_url: str = "",
                 policy: str = "", max_iterations: int = 0, tools=None):
        cfg = load_config()
        self.workspace = str(Path(workspace).resolve()) if workspace else str(BASE_DIR)
        self.on_event = on_event or (lambda ev: None)
        self.permission_handler = permission_handler
        self.log = log or (lambda m: None)
        self.model = model or cfg.get("model", "")
        self.provider = provider or cfg.get("provider", "ollama")
        self.ollama_url = ollama_url or cfg.get("ollama_url", _DEFAULT_OLLAMA_URL)
        self.policy = policy or cfg.get("policy", "safe")
        self.max_iterations = max_iterations or int(cfg.get("max_iterations", 30))
        # Optional allowlist of tool names for this run. Local models do far
        # better with two tool schemas than with twelve (the schemas eat the
        # context window and the model wanders), so a caller that knows a step
        # needs only write_file can say so.
        self.tools = [str(t) for t in (tools or [])]

        self.proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._stderr: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self.result: dict | None = None
        self.ready: dict | None = None
        self._done = threading.Event()
        # Decisions already granted for this run ("allow_task"), and the most
        # recent decision for the action log / UI.
        self._session_allows: set[str] = set()
        self.last_permission = None

    # -- lifecycle ---------------------------------------------------------

    def start(self, task: str) -> tuple[bool, str]:
        ok, msg = ensure_built(self.log)
        if not ok:
            return False, msg
        node = node_exe()
        if not node:
            return False, "Node.js is not installed or not on PATH — Crown Code requires Node >= 18."

        entry = headless_entry()
        env = dict(os.environ)
        env["OLLAMA_HOST"] = self.ollama_url
        env.setdefault("NO_COLOR", "1")
        # When the AI Provider settings point Crown Code at a HOSTED provider
        # (gemini/anthropic/openai/...), its Node side reads the key from the
        # environment — export it here so the setting actually works instead
        # of failing with an empty credential.
        try:
            from core.api_config import get_api_key
            _ENV_KEY = {"gemini": "GOOGLE_API_KEY", "google": "GOOGLE_API_KEY",
                        "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                        "openrouter": "OPENROUTER_API_KEY", "nvidia": "NVIDIA_API_KEY"}
            _ek = _ENV_KEY.get(self.provider)
            if _ek:
                _k = get_api_key(self.provider)
                if _k:
                    env[_ek] = _k
        except Exception:
            pass
        try:
            self.proc = subprocess.Popen(
                [node, str(entry)],
                cwd=self.workspace,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                env=env,
            )
        except Exception as e:
            return False, f"Could not start Crown Code bridge: {e}"

        self._reader = threading.Thread(target=self._read_loop, name="crown-stdout", daemon=True)
        self._stderr = None
        self._reader.start()

        msg = {
            "type": "start",
            "task": task,
            "cwd": self.workspace,
            "model": self.model,
            "provider": self.provider,
            "ollamaUrl": self.ollama_url,
            "maxIterations": self.max_iterations,
            "policy": self.policy,
        }
        if self.tools:
            msg["tools"] = self.tools
        self._send(msg)
        return True, "started"

    def wait(self, timeout: float | None = None) -> dict | None:
        self._done.wait(timeout=timeout)
        return self.result

    def stop(self) -> None:
        try:
            self._send({"type": "abort"})
        except Exception:
            pass
        self._kill()

    def _kill(self) -> None:
        p = self.proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
            try:
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        if p:
            try:
                if p.stdin:
                    p.stdin.close()
            except Exception:
                pass

    # -- I/O ---------------------------------------------------------------

    def _send(self, obj: dict) -> None:
        p = self.proc
        if not p or not p.stdin or p.poll() is not None:
            return
        with self._write_lock:
            try:
                p.stdin.write(json.dumps(obj) + "\n")
                p.stdin.flush()
            except (OSError, ValueError):
                # Process exited between the poll() and the write (e.g. an
                # abort right after a result). Nothing to do — not an error.
                pass
            except Exception as e:
                self.log(f"bridge write failed: {e}")

    def _default_permission(self, ev: dict) -> bool:
        """No handler configured: apply the app's own risk policy.

        Read-only and workspace-local work still runs unattended; anything that
        installs, deletes, reaches outside the workspace or touches credentials
        is refused, because there is no one to ask.
        """
        from core import agent_permissions

        decision = agent_permissions.evaluate(
            ev, workspace=self.workspace, policy=self.policy, approve=None,
            session_allows=self._session_allows,
        )
        self.last_permission = decision
        if not decision.allow:
            self.log(f"permission denied: {decision.describe()}")
        return decision.allow

    def send_permission(self, req_id: str, allow: bool) -> None:
        self._send({"type": "permission_response", "id": req_id, "allow": bool(allow)})

    def run_command(self, command: str, cwd: str = "", timeout: int = 120) -> None:
        self._send({"type": "run_command", "command": command,
                    "cwd": cwd or self.workspace, "timeout": timeout})

    def abort(self) -> None:
        self._send({"type": "abort"})

    def _stderr_loop(self) -> None:
        # stderr merged into stdout (see start()). Nothing to read here.
        return

    def _read_loop(self) -> None:
        p = self.proc
        if not p or not p.stdout:
            self._done.set()
            return
        try:
            for line in p.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    self.log(f"[crown] {line[:300]}")
                    continue
                self._dispatch(ev)
        except Exception as e:
            self.log(f"bridge read error: {e}")
        finally:
            # Process ended — ensure the caller unblocks even without a result.
            if self.result is None:
                self.result = {"type": "result", "ok": False, "state": "error",
                               "summary": "Crown Code bridge ended without a result."}
            self._done.set()

    def _dispatch(self, ev: dict) -> None:
        etype = ev.get("type", "")
        if etype == "ready":
            self.ready = ev
        elif etype == "result":
            self.result = ev
        elif etype == "permission_request":
            # The model proposes; this process decides. A handler that raises,
            # returns None or is missing must never turn into an approval.
            allow = False
            try:
                if self.permission_handler:
                    from core.agent_permissions import Decision
                    res = self.permission_handler(ev)
                    if isinstance(res, Decision):
                        self.last_permission = res
                        allow = bool(res.allow)
                    else:
                        allow = res is True
                else:
                    allow = self._default_permission(ev)
            except Exception as e:
                self.log(f"permission handler error: {e}")
                allow = False
            self.send_permission(str(ev.get("id", "")), allow)
        try:
            self.on_event(ev)
        except Exception as e:
            self.log(f"event handler error: {e}")
