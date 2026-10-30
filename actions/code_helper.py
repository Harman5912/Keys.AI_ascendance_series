import subprocess
import sys
import json
import re
import time
from pathlib import Path


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR           = get_base_dir()
API_CONFIG_PATH    = BASE_DIR / "config" / "api_keys.json"
DESKTOP            = Path.home() / "Desktop"
KEYS_CREATIONS     = DESKTOP / "keys_Creations"
CODE_DIR           = KEYS_CREATIONS / "code"
MAX_BUILD_ATTEMPTS = 3
GEMINI_MODEL       = "gemini-2.5-flash"


def _get_task_config() -> dict:
    """Read per-task model config for code_helper, falling back to global."""
    try:
        sys.path.insert(0, str(BASE_DIR))
        from core.api_config import get_task_model
        return get_task_model("code_helper")
    except Exception:
        return {"provider": "gemini", "model": GEMINI_MODEL, "url": ""}


def _get_api_key() -> str:
    cfg = _get_task_config()
    provider = cfg.get("provider", "gemini")
    key_field_map = {
        "gemini": "gemini_api_key", "nvidia": "nvidia_api_key",
        "anthropic": "anthropic_api_key", "openrouter": "openrouter_api_key",
        "openai": "openai_api_key",
    }
    key_field = key_field_map.get(provider)
    if not key_field:
        return ""
    try:
        # Through config_store so an encrypted credential is decrypted for us
        # instead of reading the placeholder-free JSON and finding nothing.
        from core.config_store import load as _load_cfg
        return _load_cfg().get(key_field, "")
    except Exception:
        try:
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get(key_field, "")
        except Exception:
            return ""


def _get_model_name() -> str:
    """Return the model name configured for code_helper."""
    return _get_task_config().get("model", GEMINI_MODEL)


_gemini_cache: dict[str, object] = {}  # model -> cached wrapper

def _get_gemini(model: str = GEMINI_MODEL):
    """Return a provider that supports .generate_content(contents).
    Uses the shared LLM client which routes to the correct provider."""
    cache_key = model or _get_model_name()
    if cache_key in _gemini_cache:
        return _gemini_cache[cache_key]

    try:
        from core.llm_client import get_llm
        llm = get_llm("code_helper")

        class _W:
            def generate_content(self, contents):
                # contents can be a string or a list of parts
                if isinstance(contents, str):
                    prompt = contents
                elif isinstance(contents, list):
                    # Extract text parts, skip images for non-vision providers
                    parts = []
                    for p in contents:
                        if isinstance(p, str):
                            parts.append(p)
                        elif hasattr(p, 'text'):
                            parts.append(p.text)
                        else:
                            parts.append(str(p))
                    prompt = "\n".join(parts)
                else:
                    prompt = str(contents)
                result = llm.generate(prompt)
                # Return an object with .text attribute for compatibility
                class _R:
                    pass
                r = _R()
                r.text = result
                return r

        w = _W()
    except Exception as e:
        print(f"[CodeHelper] LLM client failed: {e}, using genai fallback")
        from google import genai
        _c = genai.Client(api_key=_get_api_key())

        class _W:
            def generate_content(self, contents):
                return _c.models.generate_content(model=cache_key, contents=contents)

        w = _W()

    _gemini_cache[cache_key] = w
    return w


def _clean_code(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _resolve_save_path(output_path: str, language: str) -> Path:
    ext_map = {
        "python": ".py", "py": ".py",
        "javascript": ".js", "js": ".js",
        "typescript": ".ts", "ts": ".ts",
        "html": ".html", "css": ".css",
        "java": ".java", "cpp": ".cpp", "c": ".c",
        "bash": ".sh", "shell": ".sh", "powershell": ".ps1",
        "sql": ".sql", "json": ".json", "rust": ".rs", "go": ".go",
    }
    if output_path:
        p = Path(output_path)
        return p if p.is_absolute() else DESKTOP / p
    ext = ext_map.get((language or "python").lower(), ".py")
    # Route to keys_Creations instead of bare Desktop
    return CODE_DIR / f"keysai_code{ext}"


def _read_file(file_path: str) -> tuple[str, str]:
    if not file_path:
        return "", "No file path provided."
    p = Path(file_path)
    if not p.exists():
        return "", f"File not found: {file_path}"
    try:
        return p.read_text(encoding="utf-8"), ""
    except Exception as e:
        return "", f"Could not read file: {e}"


def _save_file(path: Path, content: str) -> str:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Saved to: {path}"
    except Exception as e:
        return f"Could not save: {e}"


def _preview(code: str, lines: int = 10) -> str:
    all_lines = code.splitlines()
    preview   = "\n".join(all_lines[:lines])
    suffix    = f"\n... ({len(all_lines) - lines} more lines)" if len(all_lines) > lines else ""
    return preview + suffix


def _has_error(output: str) -> bool:
    error_signals = ["error", "exception", "traceback", "syntaxerror",
                     "nameerror", "typeerror", "stderr", "failed", "crash"]
    return any(s in output.lower() for s in error_signals)


def _take_screenshot() -> Path | None:
    try:
        import pyautogui
        screenshot_path = Path.home() / "Desktop" / f"keysai_debug_{int(time.time())}.png"
        screenshot = pyautogui.screenshot()
        screenshot.save(str(screenshot_path))
        print(f"[Code] 📸 Screenshot: {screenshot_path}")
        return screenshot_path
    except Exception as e:
        print(f"[Code] ⚠️ Screenshot failed: {e}")
        return None


def _image_to_base64(path: Path) -> str:
    import base64
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def _detect_intent(description: str, file_path: str, code: str) -> str:
    desc = (description or "").lower()

    screen_kw = ["ekrandaki", "screen", "ekranda", "bu hatayı", "why am i getting",
                 "neden hata", "what's wrong", "ne yanlış", "screenshot", "görüntü"]
    if any(k in desc for k in screen_kw):
        return "screen_debug"

    optimize_kw = ["optimize", "refactor", "clean up", "improve", "temizle",
                   "iyileştir", "daha iyi", "make it better", "hızlandır"]
    if any(k in desc for k in optimize_kw) and (code or file_path):
        return "optimize"

    if file_path:
        p = Path(file_path)
        edit_kw  = ["edit", "update", "modify", "change", "add", "remove",
                    "refactor", "fix", "rename", "replace", "düzenle", "değiştir"]
        run_kw   = ["run", "execute", "launch", "start", "çalıştır"]
        build_kw = ["build", "make it work", "try", "attempt"]

        if p.exists() and any(k in desc for k in edit_kw):
            return "edit"
        if p.exists() and any(k in desc for k in run_kw):
            return "run"
        if any(k in desc for k in build_kw):
            return "build"
        if p.exists():
            return "explain"

    explain_kw = ["explain", "what does", "describe", "analyze", "açıkla", "ne yapıyor"]
    if any(k in desc for k in explain_kw) and (code or file_path):
        return "explain"

    build_kw = ["build", "make it work", "try and", "attempt"]
    if any(k in desc for k in build_kw):
        return "build"

    return "write"

def _write(description: str, language: str, output_path: str, player=None) -> tuple[str, Path]:
    lang  = language or "python"
    path  = _resolve_save_path(output_path, lang)
    model = _get_gemini()

    prompt = f"""You are an expert {lang} developer. Write COMPLETE code.

Description: {description}

ABSOLUTE RULES:
- The FIRST character of your response MUST be a {lang} code character.
- Output ONLY raw {lang} code. ZERO explanation. ZERO markdown. ZERO backticks.
- No "here is", no "step 1", no instructions — ONLY code.
- Complete, working code — no placeholders, no TODO.
- Add inline comments for clarity.

Code:"""

    if player and hasattr(player, 'creation_file_set_active'):
        player.creation_file_set_active(str(path))
        player.creation_event("→", f"Writing {path.name}", str(path))

    response = model.generate_content(prompt)
    code     = _clean_code(response.text)
    _save_file(path, code)

    if player and hasattr(player, 'creation_file_add'):
        player.creation_file_add(str(path), lines=len(code.splitlines()), status="done")
        player.creation_event("✓", f"Written {path.name} ({len(code.splitlines())} lines)", str(path))
        if hasattr(player, 'creation_code_set'):
            player.creation_code_set(code)

    return code, path


def _fix_code(code: str, error_output: str, description: str) -> str:
    model  = _get_gemini()
    prompt = f"""You are an expert debugger.
The code below failed with the following error. Fix it.
Return ONLY the corrected code — no explanation, no markdown, no backticks.

Original goal: {description}

Error:
{error_output[:2000]}

Broken code:
{code}

Fixed code:"""

    response = model.generate_content(prompt)
    return _clean_code(response.text)


def _run_file(path: Path, args: list, timeout: int) -> str:
    interpreters = {
        ".py":  [sys.executable],
        ".js":  ["node"],
        ".ts":  ["ts-node"],
        ".sh":  ["bash"],
        ".ps1": ["powershell", "-File"],
        ".rb":  ["ruby"],
        ".php": ["php"],
    }
    interp = interpreters.get(path.suffix.lower())
    if not interp:
        return f"No interpreter for {path.suffix}."

    try:
        result = subprocess.run(
            interp + [str(path)] + (args or []),
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout, cwd=str(path.parent)
        )
        output = result.stdout.strip()
        error  = result.stderr.strip()
        parts  = []
        if output: parts.append(f"Output:\n{output}")
        if error:  parts.append(f"Stderr:\n{error}")
        return "\n\n".join(parts) if parts else "Executed with no output."

    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except FileNotFoundError:
        return f"Interpreter not found: {interp[0]}."
    except Exception as e:
        return f"Execution error: {e}"


def _build(description, language, output_path, args, timeout, speak=None, player=None) -> str:
    if not description:
        return "Please describe what you want me to build, sir."

    if player:
        player.write_log("[Code] Build started...")

    lang = language or "python"
    path = _resolve_save_path(output_path, lang)

    if player and hasattr(player, 'begin_creation'):
        player.begin_creation("code", path.stem, str(path.parent))
        player.creation_event("✓", "Project initialized")
        player.creation_progress(0.05)

    try:
        code, path = _write(description, lang, output_path, player)
        print(f"[Code] ✅ Written: {path}")
        if player and hasattr(player, 'creation_progress'):
            player.creation_progress(0.25)
    except Exception as e:
        msg = f"Could not write initial code: {e}"
        if speak: speak(msg)
        if player and hasattr(player, 'creation_error'):
            player.creation_error(msg)
        return msg

    last_output = ""
    for attempt in range(1, MAX_BUILD_ATTEMPTS + 1):
        print(f"[Code] 🔄 Attempt {attempt}/{MAX_BUILD_ATTEMPTS}")
        if player:
            player.write_log(f"[Code] Attempt {attempt}...")
        if player and hasattr(player, 'creation_event'):
            player.creation_event("→", f"Running test (attempt {attempt}/{MAX_BUILD_ATTEMPTS})...")
        if player and hasattr(player, 'creation_progress'):
            player.creation_progress(0.25 + 0.2 * attempt)

        last_output = _run_file(path, args, timeout)

        if not _has_error(last_output):
            if player and hasattr(player, 'creation_event'):
                player.creation_event("✓", f"Tests passed (attempt {attempt})")
            if player and hasattr(player, 'creation_code_set'):
                player.creation_code_set(code)
            if player and hasattr(player, 'creation_complete'):
                player.creation_complete(f"Build complete — {path.name} working after {attempt} attempt{'s' if attempt > 1 else ''}")
            msg = (
                f"Build complete, sir. "
                f"The code is working after {attempt} attempt{'s' if attempt > 1 else ''}. "
                f"Saved to {path}."
            )
            if speak: speak(msg)
            return f"{msg}\n\nOutput:\n{last_output}"

        print(f"[Code] ⚠️ Error on attempt {attempt}, fixing...")
        if player:
            player.write_log(f"[Code] Fixing (attempt {attempt})...")
        if player and hasattr(player, 'creation_event'):
            error_preview = last_output[:120].replace("\n", " ")
            player.creation_event("!", f"Error detected — {error_preview}")
            player.creation_event("→", f"Fixing code (attempt {attempt})...")

        try:
            code = _fix_code(code, last_output, description)
            _save_file(path, code)
            if player and hasattr(player, 'creation_event'):
                player.creation_event("✓", f"Fix applied (attempt {attempt})")
            if player and hasattr(player, 'creation_code_set'):
                player.creation_code_set(code)
        except Exception as e:
            msg = f"Could not fix code on attempt {attempt}: {e}"
            if speak: speak(msg)
            if player and hasattr(player, 'creation_error'):
                player.creation_error(msg)
            return msg

    if player and hasattr(player, 'creation_error'):
        player.creation_error(f"Failed after {MAX_BUILD_ATTEMPTS} attempts")
    msg = (
        f"I was unable to build a working version after {MAX_BUILD_ATTEMPTS} attempts, sir. "
        f"The last error was: {last_output[:200]}"
    )
    if speak: speak(msg)
    return f"{msg}\n\nLast code saved to: {path}"

def _write_action(description, language, output_path, player) -> str:
    if not description:
        return "Please describe what you want me to write, sir."
    if player:
        player.write_log("[Code] Writing code...")
    if player and hasattr(player, 'begin_creation'):
        lang = language or "python"
        path = _resolve_save_path(output_path, lang)
        player.begin_creation("code", path.stem, str(path.parent))
        player.creation_event("→", "Initializing creation...")
    try:
        code, path = _write(description, language, output_path, player)
        print(f"[Code] ✅ Written: {path}")
        if player and hasattr(player, 'creation_complete'):
            player.creation_complete(f"File written: {path.name}")
        return f"Code written. Saved to: {path}\n\nPreview:\n{_preview(code)}"
    except Exception as e:
        if player and hasattr(player, 'creation_error'):
            player.creation_error(str(e))
        return f"Could not generate code: {e}"


def _edit_action(file_path, instruction, player) -> str:
    if not file_path:
        return "Please provide a file path to edit, sir."
    if not instruction:
        return "Please describe what change to make, sir."

    content, err = _read_file(file_path)
    if err:
        return err

    if player:
        player.write_log("[Code] Editing file...")

    model  = _get_gemini()
    prompt = f"""You are an expert code editor.
Apply the following change to the code below.
Return ONLY the complete updated code — no explanation, no markdown, no backticks.

Change: {instruction}

Original code:
{content}

Updated code:"""

    try:
        response = model.generate_content(prompt)
        edited   = _clean_code(response.text)
    except Exception as e:
        return f"Could not edit code: {e}"

    # Copilot-style visual edit: open the file in its real editor (VS Code)
    # and drive the change through the app. Falls back to a direct save if the
    # app cannot be driven.
    try:
        from actions.editor_control import editor_control
        return editor_control(
            {"action": "edit", "file_path": file_path, "content": edited},
            player=player,
        )
    except Exception as e:
        print(f"[Code] ⚠️ Visual edit failed, falling back: {e}")
        status = _save_file(Path(file_path), edited)
        print(f"[Code] ✅ Edited: {file_path}")
        return f"File edited. {status}\n\nPreview:\n{_preview(edited)}"


def _explain_action(file_path, code, player) -> str:
    if file_path and not code:
        code, err = _read_file(file_path)
        if err:
            return err
    if not code:
        return "Please provide code or a file path to explain, sir."

    if player:
        player.write_log("[Code] Analyzing code...")

    model  = _get_gemini()
    prompt = f"""Explain what this code does in simple, clear language.
Focus on: what it does, how it works, and any important details.
Be concise — 3 to 6 sentences maximum.

Code:
{code[:4000]}

Explanation:"""

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Could not explain code: {e}"


def _run_action(file_path, args, timeout, player) -> str:
    if not file_path:
        return "Please provide a file path to run, sir."
    p = Path(file_path)
    if not p.exists():
        return f"File not found: {file_path}"
    if player:
        player.write_log(f"[Code] Running {p.name}...")
    return _run_file(p, args, timeout)


def _optimize_action(file_path, code, language, output_path, player) -> str:

    if file_path and not code:
        code, err = _read_file(file_path)
        if err:
            return err
    if not code:
        return "Please provide code or a file path to optimize, sir."

    if player:
        player.write_log("[Code] Optimizing code...")

    lang  = language or "python"
    model = _get_gemini()

    prompt = f"""You are an expert {lang} developer and code reviewer.
Optimize the following code for:
1. Performance — eliminate unnecessary operations, use efficient data structures
2. Readability — clear variable names, proper formatting, logical structure
3. Best practices — modern {lang} patterns, error handling, type hints if applicable
4. Remove dead code, redundant comments, and unnecessary complexity

Return ONLY the optimized code — no explanation, no markdown, no backticks.

Original code:
{code[:6000]}

Optimized code:"""

    try:
        response  = model.generate_content(prompt)
        optimized = _clean_code(response.text)
    except Exception as e:
        return f"Could not optimize code: {e}"

    # Kaydet
    if file_path:
        save_path = Path(file_path)
    else:
        save_path = _resolve_save_path(output_path, lang)

    status = _save_file(save_path, optimized)
    print(f"[Code] ✅ Optimized: {save_path}")

    original_lines  = len(code.splitlines())
    optimized_lines = len(optimized.splitlines())
    diff = original_lines - optimized_lines

    return (
        f"Code optimized. {status}\n"
        f"Lines: {original_lines} → {optimized_lines} "
        f"({'−' if diff > 0 else '+'}{abs(diff)} lines)\n\n"
        f"Preview:\n{_preview(optimized)}"
    )


def _screen_debug_action(description, file_path, player, speak=None) -> str:

    if player:
        player.write_log("[Code] Taking screenshot for analysis...")

    print("[Code] 📸 Capturing screen for debug...")


    screenshot_path = _take_screenshot()
    if not screenshot_path:
        return "Could not take screenshot, sir. Please make sure PyAutoGUI is installed."


    file_content = ""
    if file_path:
        file_content, err = _read_file(file_path)
        if err:
            print(f"[Code] ⚠️ Could not read file: {err}")

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=_get_api_key())

        image_bytes  = screenshot_path.read_bytes()
        image_base64 = _image_to_base64(screenshot_path)

        user_question = description or "What error or problem do you see on the screen? How can it be fixed?"

        context = ""
        if file_content:
            context = f"\n\nAdditionally, here is the related file content:\n```\n{file_content[:4000]}\n```"

        analysis_prompt = f"""You are an expert programmer and debugger analyzing a screenshot.

User's question: {user_question}{context}

Please:
1. Identify any errors, exceptions, or problems visible on the screen
2. Explain what is causing the problem in simple terms
3. Provide a concrete fix or solution
4. If there's code visible, show the corrected version

Be specific and actionable. If you see an error message, quote it exactly."""

        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            analysis_prompt,
        ]

        response = client.models.generate_content(
            model=_get_model_name(),
            contents=contents,
        )

        analysis = response.text.strip()
        print(f"[Code] ✅ Screen analysis complete")

        try:
            screenshot_path.unlink()
        except Exception:
            pass

        if file_path and file_content:

            code_match = re.search(r"```[a-zA-Z]*\n(.*?)```", analysis, re.DOTALL)
            if code_match:
                fixed_code = code_match.group(1).strip()
                save_path  = Path(file_path)
                _save_file(save_path, fixed_code)
                analysis += f"\n\n✅ Fixed code has been saved to: {file_path}"
                print(f"[Code] ✅ Fixed code saved: {file_path}")

        return analysis

    except Exception as e:

        try:
            screenshot_path.unlink()
        except Exception:
            pass
        return f"Screen analysis failed: {e}"


def _is_website_request(description: str, language: str) -> bool:
    """Detect if the user is asking to create a website/web app."""
    desc = (description or "").lower()
    lang = (language or "").lower()
    website_kw = [
        "website", "web app", "webapp", "webpage", "web page",
        "landing page", "portfolio", "blog site", "ecommerce",
        "e-commerce", "online store", "dashboard", "frontend",
        "html css", "html/css", "react app", "next app",
        "vue app", "angular app", "svelte app",
    ]
    return lang in ("html", "html/css", "web") or any(k in desc for k in website_kw)


WEBSITES_DIR = DESKTOP / "keys_Creations" / "code" / "Web"


def _validate_code(code: str, file_path: str) -> bool:
    """Check if generated output is actual code, not instructions."""
    ext = Path(file_path).suffix.lower()
    code_stripped = code.strip()
    if len(code_stripped) < 20:
        return False
    # Check for instruction patterns (first 500 chars)
    instruction_patterns = [
        r'(?i)^here\'s how', r'(?i)^step \d', r'(?i)^first,?\s',
        r'(?i)^you need to', r'(?i)^create a file', r'(?i)^save this as',
        r'(?i)^instructions:', r'(?i)^to create this', r'(?i)^make sure you',
        r'(?i)^the following', r'(?i)^below is', r'(?i)^copy and paste',
        r'(?i)^run this command', r'(?i)^open your',
    ]
    for pat in instruction_patterns:
        if re.search(pat, code_stripped[:500]):
            return False
    # File-type-specific checks
    if ext in ('.html', '.htm'):
        return any(t in code_stripped.lower() for t in ['<html', '<!doctype', '<head', '<body', '<div'])
    elif ext == '.css':
        return '{' in code_stripped and len(code_stripped) > 50
    elif ext in ('.js', '.jsx', '.ts', '.tsx'):
        return any(kw in code_stripped for kw in ['function', 'const ', 'let ', 'var ', '=>', '.addEventListener', 'export ', 'import '])
    elif ext == '.py':
        return any(kw in code_stripped for kw in ['def ', 'import ', 'class ', 'print(', 'from '])
    elif ext in ('.java', '.go', '.rs'):
        return any(kw in code_stripped for kw in ['class ', 'func ', 'fn ', 'public ', 'package '])
    # Generic: check if lines look like code
    code_lines = [l.strip() for l in code_stripped.split('\n') if l.strip()]
    if not code_lines:
        return False
    code_like = sum(1 for l in code_lines if any(c in l for c in ['=', '(', '{', ':', ';', '<', '>']))
    return code_like > len(code_lines) * 0.25


def _stream_code_to_ui(code: str, player=None, chunk_size: int = 3):
    """Stream code line-by-line to the creation workspace."""
    if not player or not hasattr(player, 'creation_code_append'):
        return
    if not code:
        return
    lines = code.split("\n")
    buf = []
    for i, line in enumerate(lines):
        buf.append(line)
        if len(buf) >= chunk_size or i == len(lines) - 1:
            chunk = "\n".join(buf)
            if i < len(lines) - 1:
                chunk += "\n"
            player.creation_code_append(chunk)
            buf = []
            time.sleep(0.01)


def _start_http_server(directory: Path, port: int = 8080):
    """Start a simple HTTP server, returns Popen or None."""
    import socket
    for p in range(port, port + 10):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.1)
            result = s.connect_ex(('127.0.0.1', p))
            s.close()
            if result != 0:
                port = p
                break
        except Exception:
            continue
    else:
        print(f"[Code] All ports {port}-{port+9} in use")
        return None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port)],
            cwd=str(directory), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"[Code] HTTP server started on port {port} (pid={proc.pid})")
        return proc
    except Exception as e:
        print(f"[Code] Failed to start HTTP server: {e}")
        return None


def _open_in_browser(url: str):
    """Open URL in the default browser."""
    import webbrowser
    try:
        webbrowser.open(url)
        print(f"[Code] Opened in browser: {url}")
    except Exception as e:
        print(f"[Code] Failed to open browser: {e}")


def _fallback_template(file_path: str, description: str) -> str:
    """Minimal working fallback when LLM fails to produce valid code."""
    ext = Path(file_path).suffix.lower()
    if ext == ".html":
        return f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n<title>{description[:60]}</title>\n<link rel="stylesheet" href="css/style.css">\n</head>\n<body>\n<header><h1>{description[:60]}</h1><nav><a href="#home">Home</a><a href="#about">About</a><a href="#contact">Contact</a></nav></header>\n<main>\n<section id="home"><h2>Welcome</h2><p>{description}</p></section>\n<section id="about"><h2>About</h2><p>Created by Keys.ai</p></section>\n<section id="contact"><h2>Contact</h2><p>Get in touch!</p></section>\n</main>\n<footer><p>&copy; 2026 Keys.ai</p></footer>\n<script src="js/main.js"></script>\n</body>\n</html>'
    elif ext == ".css":
        return '*{margin:0;padding:0;box-sizing:border-box}:root{--pri:#D9B650;--bg:#0a0a0f;--text:#f0f0f0;--card:#141420}body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.6}header{background:var(--card);padding:1.5rem 2rem;border-bottom:2px solid var(--pri);display:flex;justify-content:space-between;align-items:center}header h1{color:var(--pri)}nav a{color:var(--text);text-decoration:none;margin-left:1.5rem;transition:color .3s}nav a:hover{color:var(--pri)}main{max-width:900px;margin:2rem auto;padding:0 1.5rem}section{background:var(--card);border-radius:8px;padding:2rem;margin-bottom:1.5rem;border:1px solid rgba(217,182,80,.15)}section h2{color:var(--pri);margin-bottom:1rem}footer{text-align:center;padding:2rem;color:#666;border-top:1px solid #222}@media(max-width:768px){header{flex-direction:column;gap:1rem}nav a{margin:0 .75rem}}'
    elif ext == ".js":
        return "document.addEventListener('DOMContentLoaded',()=>{document.querySelectorAll('nav a').forEach(a=>{a.addEventListener('click',e=>{e.preventDefault();const t=document.querySelector(a.getAttribute('href'));if(t)t.scrollIntoView({behavior:'smooth'})})});const o=new IntersectionObserver(e=>{e.forEach(e=>{if(e.isIntersecting){e.target.style.opacity='1';e.target.style.transform='translateY(0)'}})},{threshold:.1});document.querySelectorAll('section').forEach(s=>{s.style.opacity='0';s.style.transform='translateY(20px)';s.style.transition='opacity .6s,transform .6s';o.observe(s)})});"
    return f"// {file_path}\n// Generated by Keys.ai"


def _validate_project_references(project_dir: Path, created_files: list, player=None):
    """Check that HTML references match actual file locations."""
    html_files = [(fp, code) for fp, code in created_files if fp.endswith('.html')]
    if not html_files:
        return
    html_lower = html_files[0][1].lower()
    if 'style.css' in html_lower and not (project_dir / 'css' / 'style.css').exists():
        if (project_dir / 'style.css').exists() and player and hasattr(player, 'creation_event'):
            player.creation_event("!", "CSS at style.css but HTML links css/style.css")
    if 'main.js' in html_lower and not (project_dir / 'js' / 'main.js').exists():
        if (project_dir / 'main.js').exists() and player and hasattr(player, 'creation_event'):
            player.creation_event("!", "JS at main.js but HTML links js/main.js")


def _create_website(description: str, output_path: str, player=None) -> str:
    """Create a complete multi-file website, serve it, and open in browser."""
    if player and hasattr(player, 'begin_creation'):
        player.begin_creation("code", "Website", str(WEBSITES_DIR))
        player.creation_event("✓", "Planning website structure")
        player.creation_progress(0.05)

    if output_path:
        project_dir = Path(output_path)
        if not project_dir.is_absolute():
            project_dir = WEBSITES_DIR / project_dir
    else:
        name_guess = re.sub(r'[^a-zA-Z0-9]+', '_', description[:40]).strip('_').lower()
        if not name_guess:
            name_guess = "my_website"
        project_dir = WEBSITES_DIR / name_guess

    project_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: plan (with API key fallback)
    plan = {"name": project_dir.name, "files": []}
    model = None
    try:
        model = _get_gemini()
        plan_prompt = f"""Return ONLY valid JSON for a website plan. No markdown.
{{"name":"x","files":[{{"path":"index.html","desc":"main page"}},{{"path":"css/style.css","desc":"styles"}},{{"path":"js/main.js","desc":"js"}}]}}
Description: {description}"""
        response = model.generate_content(plan_prompt)
        plan = json.loads(_clean_code(response.text))
    except Exception as e:
        print(f"[Code] Plan generation unavailable ({e}), using default structure")

    files_to_create = plan.get("files") or [
        {"path": "index.html", "desc": "Main page"},
        {"path": "css/style.css", "desc": "Styles"},
        {"path": "js/main.js", "desc": "JavaScript"},
    ]

    total = len(files_to_create)
    created_files = []
    MAX_RETRIES = 2

    # ── Ask user for design direction (if interactive) ──────────────────
    design_choice = "Modern Minimal"
    if player and hasattr(player, 'ask_decision'):
        try:
            design_choice = player.ask_decision(
                "What design direction do you want?",
                ["Modern Minimal", "Professional", "Bold & Creative",
                 "Dark / Developer", "Premium / Advanced"],
                show_why=True,
                why_text=(
                    "Modern Minimal: Clean, lots of whitespace, simple typography.\n"
                    "Professional: Corporate feel, structured layout, blue tones.\n"
                    "Bold & Creative: Large typography, vivid colors, animations.\n"
                    "Dark / Developer: Dark theme, code-style fonts, tech aesthetic.\n"
                    "Premium / Advanced: Glassmorphism, gradients, luxury feel."
                ),
            )
            if player and hasattr(player, 'creation_event'):
                player.creation_event("\u2713", f"Design direction: {design_choice}")
        except Exception:
            pass

    # Phase 2: generate each file
    for idx, fi in enumerate(files_to_create):
        file_path = fi["path"]
        file_desc = fi.get("desc") or fi.get("description", "")
        full_path = project_dir / file_path
        ext = Path(file_path).suffix.lower()
        lang_name = {".html": "HTML", ".css": "CSS", ".js": "JavaScript"}.get(ext, "code")

        if player and hasattr(player, 'creation_file_set_active'):
            player.creation_file_set_active(file_path)
        if player and hasattr(player, 'creation_event'):
            player.creation_event("\u2192", f"Writing {file_path}", file_path)
        if player and hasattr(player, 'creation_progress'):
            player.creation_progress(0.1 + 0.7 * (idx / max(total, 1)))

        context = ""
        for cfp, cfc in created_files:
            context += f"\n--- {cfp} (done) ---\n{cfc[:1200]}\n"

        context_line = f"Existing files:{context}" if context else "First file."
        design_note = f"Design style: {design_choice}." if design_choice else ""
        file_prompt = (
            f"Write COMPLETE {lang_name} code for: {file_path}\n"
            f"Website: {description}\n"
            f"{design_note}\n"
            f"{context_line}\n"
            f"Purpose: {file_desc}\n\n"
            f"RULES:\n"
            f"- FIRST char must be {lang_name} code (not explanation).\n"
            f"- NO markdown. NO backticks. NO instructions. ONLY raw code.\n"
            f"- COMPLETE code -- no TODO, no placeholders.\n"
            f"- HTML: <!DOCTYPE>, viewport, link css/style.css, script js/main.js.\n"
            f"- CSS: match the '{design_choice}' style. Modern, responsive.\n"
            f"- JS: working interactivity.\n\n"
            f"Code:"
        )

        code = None
        if model is None:
            # No API key — use fallback template directly
            code = _fallback_template(file_path, description)
            if player and hasattr(player, 'creation_event'):
                player.creation_event("!", f"Fallback template for {file_path} (no API key)")
        else:
            for attempt in range(MAX_RETRIES):
                try:
                    response = model.generate_content(file_prompt)
                    code = _clean_code(response.text)
                    if _validate_code(code, file_path):
                        break
                    print(f"[Code] Validation fail for {file_path} (attempt {attempt+1})")
                    if player and hasattr(player, 'creation_event'):
                        player.creation_event("!", f"Regenerating {file_path}...")
                    file_prompt += "\n\n*** YOUR PREVIOUS OUTPUT WAS INSTRUCTIONS, NOT CODE. OUTPUT ONLY RAW CODE. ***"
                except Exception as e:
                    print(f"[Code] Error generating {file_path}: {e}")
                    if player and hasattr(player, 'creation_event'):
                        player.creation_event("\u2715", f"Error: {file_path}: {e}")
                    continue

        if code is None or not _validate_code(code, file_path):
            code = _fallback_template(file_path, description)
            if player and hasattr(player, 'creation_event'):
                player.creation_event("!", f"Fallback template for {file_path}")

        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(code, encoding="utf-8")
        created_files.append((file_path, code))
        lines = len(code.splitlines())

        if player and hasattr(player, 'creation_file_add'):
            player.creation_file_add(file_path, lines=lines, status="done")
        if player and hasattr(player, 'creation_event'):
            player.creation_event("\u2713", f"Written {file_path} ({lines} lines)", file_path)
        _stream_code_to_ui(code, player)
        print(f"[Code] Written: {full_path} ({lines} lines)")

    if not created_files:
        if player and hasattr(player, 'creation_error'):
            player.creation_error("No files created")
        return "Could not create website files."

    # Phase 3: validate references
    _validate_project_references(project_dir, created_files, player)

    # Phase 4: serve + open browser
    # Ask permission to start server
    server_allowed = True
    if player and hasattr(player, 'ask_permission'):
        try:
            perm = player.ask_permission(
                action="Start a local HTTP server and open it in your browser",
                reason=f"Serve the website at http://localhost:8080 so you can preview it.",
                location=str(project_dir),
            )
            server_allowed = perm in ("allow_once", "allow_task")
            if player and hasattr(player, 'creation_event'):
                icon = "\u2713" if server_allowed else "\u2717"
                text = f"Server permission: {perm}"
                player.creation_event(icon, text)
        except Exception:
            pass

    if not server_allowed:
        if player and hasattr(player, 'creation_complete'):
            player.creation_complete(f"Website '{project_dir.name}' created (server not started per your choice)")
        return (
            f"Website created, sir.\n"
            f"Location: {project_dir}\n"
            f"Open index.html in a browser to preview."
        )

    if player and hasattr(player, 'creation_event'):
        player.creation_event("\u2192", "Starting local server...")
    if player and hasattr(player, 'creation_progress'):
        player.creation_progress(0.9)

    server_proc = _start_http_server(project_dir, port=8080)
    url = "http://localhost:8080"

    if server_proc:
        if player and hasattr(player, 'creation_event'):
            player.creation_event("\u2713", f"Server running on {url}")
        time.sleep(0.5)
        _open_in_browser(url)
        if player and hasattr(player, 'creation_event'):
            player.creation_event("\u2713", "Opened in default browser")
    else:
        if player and hasattr(player, 'creation_event'):
            player.creation_event("!", "Server couldn't start — open index.html manually")

    if player and hasattr(player, 'creation_progress'):
        player.creation_progress(1.0)

    file_list = "\n".join(f"  {fp} ({len(fc.splitlines())} lines)" for fp, fc in created_files)
    summary = (
        f"Website created and running.\n"
        f"Location: {project_dir}\n"
        f"Files ({len(created_files)}):\n{file_list}\n\n"
        f"Live at: {url}\n"
        f"Opened in your default browser."
    )
    if player and hasattr(player, 'creation_complete'):
        player.creation_complete(f"Website '{project_dir.name}' — {len(created_files)} files, live at {url}")
    return summary


def code_helper(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None
) -> str:
    """
    Called from main.py.

    parameters:
        action      : write | edit | explain | run | build | screen_debug | optimize | auto
        description : What the code should do / what change to make / what problem to analyze
        language    : Programming language (default: python)
        output_path : Where to save — user specifies full path or filename
        file_path   : Path to existing file (edit / explain / run / build / optimize)
        code        : Raw code string (explain/optimize without a file)
        args        : CLI argument list for run/build
        timeout     : Execution timeout in seconds (default: 30)
    """
    p           = parameters or {}
    action      = p.get("action", "auto").lower().strip()
    description = p.get("description", "").strip()
    language    = p.get("language", "python").strip()
    output_path = p.get("output_path", "").strip()
    file_path   = p.get("file_path", "").strip()
    code        = p.get("code", "").strip()
    args        = p.get("args", [])
    timeout     = int(p.get("timeout", 30))

    if action == "auto":
        action = _detect_intent(description, file_path, code)
        print(f"[Code] 🤖 Auto-detected: {action}")

    # ── Website detection: route to multi-file project creator ──────────
    if action in ("write", "build", "auto") and not file_path:
        if _is_website_request(description, language):
            print(f"[Code] 🌐 Website detected — creating multi-file project")
            return _create_website(description, output_path, player)

    if action == "write":
        return _write_action(description, language, output_path, player)

    elif action == "edit":
        return _edit_action(
            file_path,
            description or p.get("instruction", ""),
            player
        )

    elif action == "explain":
        return _explain_action(file_path, code, player)

    elif action == "run":
        return _run_action(file_path, args, timeout, player)

    elif action == "build":
        return _build(description, language, output_path, args, timeout, speak, player)

    elif action == "optimize":
        return _optimize_action(file_path, code, language, output_path, player)

    elif action == "screen_debug":
        return _screen_debug_action(description, file_path, player, speak)

    else:
        return f"Unknown action: '{action}'. Use write, edit, explain, run, build, optimize, or screen_debug."