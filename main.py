from __future__ import annotations
import platform as _platform
import subprocess as _subprocess

# ── Nuclear: force CREATE_NO_WINDOW on EVERY subprocess call on Windows ───────

# This patches Popen itself, so no per-file flag is needed anywhere.
if _platform.system() == "Windows":
    _OrigPopen = _subprocess.Popen
    class _Popen(_OrigPopen):
        def __init__(self, args, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | _subprocess.CREATE_NO_WINDOW
            kw.pop("startupinfo", None)   # drop any stale/shared STARTUPINFO
            super().__init__(args, **kw)
    _subprocess.Popen = _Popen

# ─────────────────────────────────────────────────────────────────────────────

# ── Force UTF-8 console output so emoji/Unicode log lines never crash on ─────

# legacy Windows (cp1252) consoles.
import sys as _sys
for _stream in (_sys.stdout, _sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────

# ── Silence the harmless sounddevice (0.5.5) NumPy 2.5 deprecation spam ─────
import warnings as _warnings
_warnings.filterwarnings(
    "ignore", message="Setting the shape on a NumPy array has been deprecated"
)

# ─────────────────────────────────────────────────────────────────────────────
import asyncio
import re
import threading
import time
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from ui import KeysAIUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    search_memory, set_trim_notifier,
    save_session_summary, pop_last_session,
)
from memory.config_manager import (
    get_voice, get_input_device, get_output_device,
)
from actions.background_monitor import (
    add_monitor, remove_monitor, list_monitors, check_all as monitor_check_all,
)
from core.tool_declarations import TOOL_DECLARATIONS
from core.tool_registry import TOOL_HANDLERS, PluginDispatch
from core.plugin_loader import discover_plugins
from core import undo as undo_stack
from core import confirm as confirm_gate
from core import audio_devices
from core import confirm_ui

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent
BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

def _get_api_key() -> str:
    """Gemini key for the Live voice session. Empty when unset — the app then
    keeps running in text/brain mode via the configured LLM provider.

    Read through core.config_store: the key may live in encrypted storage
    (config/secrets.enc), and a direct read of api_keys.json then returns
    nothing — which paused voice and every typed command for the whole app.
    """
    try:
        from core.config_store import load as _load_config
        return str(_load_config().get("gemini_api_key", "") or "")
    except Exception:
        try:
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("gemini_api_key", "") or ""
        except Exception:
            return ""

def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are Keys.ai, a premium AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )
_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:    
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()

# --- Plugin system ---

class _ReconnectSignal(Exception):
    """Raised inside the session TaskGroup to force a clean, voluntary
    reconnect (e.g. the user changed a setting that is fixed at connect
    time). Carries `keep_context`: True replays the stored resumption handle
    so the conversation continues; False starts genuinely clean."""

    def __init__(self, keep_context: bool = True):
        super().__init__()
        self.keep_context = keep_context

def _is_reconnect_signal(exc: BaseException) -> bool:
    if isinstance(exc, _ReconnectSignal):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_is_reconnect_signal(sub) for sub in exc.exceptions)
    return False

def _keep_context_of(exc: BaseException) -> bool:
    if isinstance(exc, _ReconnectSignal):
        return getattr(exc, "keep_context", True)
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            if _is_reconnect_signal(sub):
                return _keep_context_of(sub)
    return True

class KeysAILive:

    def __init__(self, ui: KeysAIUI):
        self.ui             = ui
        self.session              = None
        self.audio_in_queue       = None
        self.out_queue            = None
        self._loop                = None
        self._is_speaking         = False
        self._speaking_lock       = threading.Lock()
        self._phone_active        = False   # True while phone mic is streaming; pauses PC mic
        self._pending_vision       = None    # (img_bytes, mime_type, question, angle) to inject after tool response
        self._vision_cam_active    = False   # True if camera was opened for vision → auto-close after response
        self._vision_close_pending = False   # True after vision injected; next turn_complete closes camera
        self._vision_last_time     = 0.0     # monotonic time of last screen_process call (cooldown guard)
        self._vision_busy          = False   # True while a vision capture/inject cycle is in flight
        self._interrupted          = False   # True while draining audio after user interrupt
        self.ui.on_text_command   = self._dispatch_text
        self.ui.on_interrupt      = self.interrupt
        self._turn_done_event: asyncio.Event | None = None
        self._dashboard     = None
        self._briefing_sent    = False          # morning briefing fires once per process
        self._sys_monitor      = None   # lazy - created on first monitor tick
        self._proactive        = None   # lazy - created on first proactive check
        self._last_user_speech = time.monotonic()  # updated on every user utterance
        # Set when the model calls the `globe` tool during the current turn, so
        # the deterministic globe-utterance guard never runs the same request
        # a second time.
        self._globe_tool_called = False
        self._brain            = None   # lazy - SMART BRAIN V2 (enabled via config/brain.json)
        # ── Wake word + self-echo guard (optional, local) ───────────────
        # Both are created/started in run(). They are None when disabled, and
        # the audio path checks for None, so a missing optional dependency can
        # never slow or break the microphone.
        self._wake              = None    # WakeWordDetector
        self._wake_listen_until = 0.0     # monotonic; mic open until this time
        self._echo              = None    # EchoGuard
        self._barge_in          = False   # interrupt by voice (opt-in)
        # ── Session resumption ─────────────────────────────────────────
        # The server issues a resumption handle every few seconds and reissues
        # it as the conversation moves on. Before this, session_resumption was
        # switched on in the config and the update was never read, so the
        # handle was thrown away and EVERY reconnect — a dropped packet, a
        # voice change, switching microphone — started an empty session.
        #
        # Deliberately RAM-only: persisting it would make a fresh launch
        # continue yesterday's chat, which breaks the session-summary flow
        # (a conversation that never ends never produces a summary).
        self._resume_handle: str | None = None
        self._reconnect_event: asyncio.Event | None = None
        self._reconnect_keep   = True
        self._reconnect_reason = ""
        self._enhanced_live    = True   # affective dialog + proactive audio; auto-disabled if server rejects
        # ── Session memory: conversation turns for the end-of-session summary ──
        self._session_log: list[str] = []
        # ── Plugin system: drop a .py file into plugins/ → new tool on next launch ──
        _core_names = {t["name"] for t in TOOL_DECLARATIONS}
        self._plugin_registry = discover_plugins(
            plugins_dir=Path(__file__).resolve().parent / "plugins",
            core_tool_names=_core_names,
            logger=lambda msg: (print(f"[Plugins] {msg}"), self.ui.write_log(f"SYS: {msg}")),
        )
        PluginDispatch.set_plugin_fallback(self._plugin_registry)

    def _get_brain(self):
        """Lazy SMART BRAIN V2 instance. None when unavailable; `enabled`
        decides whether text commands route through it. Flags: --brain
        forces ON, --no-brain forces OFF (config/brain.json otherwise)."""
        if self._brain is not None:
            return self._brain
        try:
            from brain.brain import KeysBrain
            if "--no-brain" in sys.argv:
                self._brain = KeysBrain(ui=self.ui, speak=self.speak,
                                        enabled=False)
                print("[Brain] Disabled via --no-brain flag.")
            elif "--brain" in sys.argv:
                self._brain = KeysBrain(ui=self.ui, speak=self.speak,
                                        enabled=True)
                print("[Brain] SMART BRAIN V2 — forced ENABLED (--brain).")
            else:
                self._brain = KeysBrain(ui=self.ui, speak=self.speak)
                print(f"[Brain] SMART BRAIN V2 — "
                      f"{'ENABLED' if self._brain.enabled else 'disabled (config/brain.json)'}.")
        except Exception as e:
            print(f"[Brain] ⚠️ Could not initialise Smart Brain: {e}")
            self._brain = None
        # Wire brain logger → dashboard broadcast so brain events (including
        # FALLBACK) appear in the web UI.
        if self._brain is not None and self._dashboard is not None:
            _dash = self._dashboard  # capture for closure
            _orig_sink = self._brain.logger.sink
            def _dashboard_sink(line: str):
                # Forward to original sink (write_log / print)
                if _orig_sink is not None:
                    try:
                        _orig_sink(line)
                    except Exception:
                        pass
                # Also broadcast to dashboard WebSocket as a system message.
                # Using type='sys' renders as centered muted text in the web UI,
                # which is the right style for brain/fallback status events.
                active_loop = self._loop
                if active_loop is not None:
                    try:
                        from datetime import datetime as _dt
                        asyncio.run_coroutine_threadsafe(
                            _dash.broadcast({
                                "type": "sys",
                                "text": line,
                                "ts": _dt.now().isoformat(),
                            }),
                            active_loop,
                        )
                    except Exception:
                        pass
            self._brain.logger.sink = _dashboard_sink
            print("[Brain] Logger wired to dashboard broadcast.")
        return self._brain

    def request_reconnect(self, keep_context: bool = True, reason: str = ""):
        """Thread-safe: ask the run loop to tear down and rebuild the Live
        session. No-op until the async loop and reconnect event exist."""
        loop = getattr(self, "_loop", None)
        ev   = self._reconnect_event
        self._reconnect_keep   = keep_context
        self._reconnect_reason = reason
        if loop and ev is not None:
            loop.call_soon_threadsafe(ev.set)

    async def _watch_reconnect(self):
        """Session-scoped task: when a voluntary reconnect is requested, raise
        a signal that unwinds the TaskGroup so the run loop rebuilds."""
        assert self._reconnect_event is not None
        await self._reconnect_event.wait()
        self._reconnect_event.clear()
        keep   = self._reconnect_keep
        reason = self._reconnect_reason or "settings"
        self.ui.write_log(f"SYS: Applying {reason} — reconnecting...")
        raise _ReconnectSignal(keep_context=keep)

    def _dispatch_text(self, text: str) -> None:
        """Run a typed command on the asyncio loop.

        The UI calls this from a plain thread (`KeysAIUI._send`). Handing it an
        ``async def`` directly would build a coroutine and drop it, so every
        typed command — including "open the globe" — silently did nothing.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            self.ui.write_log("SYS: The assistant is not connected yet.")
            return
        try:
            asyncio.run_coroutine_threadsafe(self._on_text_command(text), loop)
        except RuntimeError as exc:
            self.ui.write_log(f"ERR: could not run that command — {exc}")

    async def _on_text_command(self, text: str):
        # Typed commands are answered here, before the model sees them: they
        # have to work the moment the window is up.
        if await self._maybe_command(text):
            return
        # An explicit globe request is executed here, not sent to the model: it
        # has to work the moment the window is up, and it must never depend on
        # a live session being available.
        if await self._maybe_globe_text(text):
            return
        if not self._loop or not self.session:
            self.ui.write_log("SYS: The assistant is not connected yet.")
            return
        # ── SMART BRAIN V2: intercept text commands when enabled. Voice
        # keeps the existing Gemini Live path untouched. Any brain failure
        # falls back to the normal path below — never breaks chat. ──
        brain = self._get_brain()
        if brain is not None and brain.enabled:
            try:
                resp = await brain.process(text, ui=self.ui, speak=self.speak)
                if resp.used_brain:
                    # The brain consumed the command — never re-send it to
                    # the session (would double-execute). Speak whatever it
                    # returned, or say so if there is no spoken text.
                    self.ui.write_log(f"You: {text}")
                    if resp.text:
                        self.ui.write_log(f"Keys.ai: {resp.text}")
                        self.speak(resp.text)
                    else:
                        self.ui.write_log("SYS: Task done — no spoken response.")
                    return
            except Exception as e:
                traceback.print_exc()
                self.ui.write_log(f"ERR: Brain failed — falling back to chat. {e}")
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    async def _maybe_command(self, text: str) -> bool:
        """Run a /command typed by the user. True when the text was one."""
        try:
            from skills.commands import handle, is_command
        except Exception:
            return False
        if not is_command(text):
            return False
        self.ui.write_log(f"You: {text}")
        try:
            reply = await asyncio.to_thread(handle, text, None)
        except Exception as exc:
            reply = f"ERR: that command failed — {exc}"
        self.ui.write_log(str(reply or "Done."))
        try:
            self._session_log.append(f"User: {text}")
            self._session_log.append(f"Keys.ai: {reply}")
        except Exception:
            pass
        return True

    async def _maybe_globe_text(self, text: str) -> bool:
        """Run a typed globe request. True when the text was one.

        The same deterministic guard the voice path uses, so "open the globe"
        and "take me to Kanpur" typed into the command bar do the same thing
        spoken — and do it without waiting on the model.
        """
        try:
            from globe.intents import try_parse
            if try_parse(text) is None:
                return False
        except Exception:
            return False

        self.ui.write_log(f"You: {text}")
        try:
            from globe.tools import handle_utterance
            reply = await asyncio.to_thread(
                handle_utterance, text, self.ui, self.speak)
        except Exception as exc:
            self.ui.write_log(f"ERR: globe — {exc}")
            return True
        if reply:
            self.ui.write_log(f"Keys.ai: {reply}")
            try:
                self._session_log.append(f"Keys.ai: {reply}")
            except Exception:
                pass
        return True

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("HOLD K TO TALK")

    async def _on_wake_word(self) -> None:
        """Called from the wake-word thread: open the mic for a short window."""
        self._wake_listen_until = time.monotonic() + 8.0
        try:
            self.ui.write_log("SYS: Wake word heard — listening…")
            self.ui.set_state("LISTENING")
        except Exception:
            pass

    def interrupt(self) -> None:
        """Stop KEYS.AI mid-speech: drain queued audio and open mic immediately."""
        self._interrupted = True
        q = self.audio_in_queue
        if q:
            drained = 0
            while True:
                try:
                    q.get_nowait()
                    drained += 1
                except Exception:
                    break
            if drained:
                print(f"[Keys.ai] ✋ Interrupted — {drained} audio chunks discarded")
        self.set_speaking(False)
        if self._turn_done_event:
            self._turn_done_event.clear()
        self.ui.write_log("SYS: Interrupted — listening...")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _ensure_not_already_shutting_down(self) -> None:
        """Keep a tool call's side effects from starting a second shutdown."""
        if self._shutdown_in_progress:
            raise RuntimeError(
                "Keys.ai is already shutting down — no more tool work until that finishes."
            )

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime
        from google.genai import types
        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()
        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )
        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str)
        # Personality / SOUL / skills block (guarded — never breaks startup)
        try:
            from personality import build_system_block
            _pers_block = build_system_block()
            if _pers_block:
                parts.append(_pers_block)
        except Exception:
            pass
        parts.append(sys_prompt)
        cfg = dict(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations":
                    TOOL_DECLARATIONS + self._plugin_registry.get_tool_declarations()}],
            # Hand back the handle captured from the last session_resumption
            # update. `handle=None` is exactly the old behaviour (ask for
            # handles, start fresh), so the first connect of a run is unchanged.
            session_resumption=types.SessionResumptionConfig(
                handle=self._resume_handle
            ),
            # Sliding-window compression: the session never dies from a full
            # context window — one conversation can last for hours
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=get_voice()
                    )
                )
            ),
        )
        if self._enhanced_live:
            # Affective dialog: hears tone/emotion and adapts its voice.
            # Proactive audio: stays silent when speech isn't addressed to it
            # (background chatter, talking to someone else in the room).
            cfg["enable_affective_dialog"] = True
            cfg["proactivity"] = types.ProactivityConfig(proactive_audio=True)
        return types.LiveConnectConfig(**cfg)

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        from google.genai import types
        name = fc.name
        args = dict(fc.args or {})
        print(f"[Keys.ai] 🔧 {name}  {args}")
        self.ui.set_state("THINKING")
        self.ui.set_status_line(f"\u25b8 {name}")
        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("HOLD K TO TALK")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )
        loop   = asyncio.get_event_loop()
        result = "Done."
        # A tool call must never unilaterally end the session. Tool failures are
        # reported to the user and logged, but they are not treated as shutdown
        # signals. The only tool that may begin a shutdown is shutdown_keysai, and
        # even that is gated by _begin_shutdown() below.
        self._ensure_not_already_shutting_down()
        try:
            if name == "recall_memory":
                # Local file search: no network, no second model. Kept out of
                # the executor deliberately — it is a dictionary scan over a
                # few hundred short strings; a thread hop would cost more
                # than the work itself.
                result = search_memory(args.get("query", ""), limit=8)
            elif name == "undo":
                if str(args.get("action", "")).lower().strip() == "list":
                    items = undo_stack.history()
                    result = (
                        "Things I can undo, most recent first:\n"
                        + "\n".join(f"{i+1}. {t}" for i, t in enumerate(items))
                    ) if items else "I have not changed anything I can undo yet."
                else:
                    result = await loop.run_in_executor(None, undo_stack.undo_last)
            elif name == "manage_monitor":
                action = args.get("action", "").lower().strip()
                topic  = args.get("topic", "").strip()
                if action == "add" and topic:
                    result = await asyncio.to_thread(add_monitor, topic)
                elif action == "remove" and topic:
                    result = await asyncio.to_thread(remove_monitor, topic)
                elif action == "list":
                    topics = await asyncio.to_thread(list_monitors)
                    result = ("Monitoring: " + ", ".join(topics)) if topics else "No topics are being monitored."
                else:
                    result = "Specify action (add/remove/list) and a topic."

            # UAC secure desktop guard: while a UAC prompt owns the screen the
            # automation tools cannot see the desktop, so they pause instead of
            # clicking into the void.
            if name in (
                "computer_use", "hybrid_control", "computer_control",
                "computer_settings", "editor_control", "browser_control",
                "agent_control",
            ):
                try:
                    from automation.elevation import secure_desktop_active
                    if secure_desktop_active():
                        result = (
                            "The UAC secure desktop is active — I am pausing automation until "
                            "you approve the prompt and return to your desktop. Ask me to "
                            "continue afterwards."
                        )
                        return types.FunctionResponse(
                            id=fc.id, name=name, response={"result": result}
                        )
                except Exception:
                    pass

            if name == "screen_process":
                import time as _t_mod
                _now = _t_mod.monotonic()
                # Cooldown: captures that arrive before the model has looked at the
                # previous frame only burn frames, so gate them.
                _cooldown = 1.5
                if self._vision_busy or (_now - self._vision_last_time) < _cooldown:
                    _wait = max(0, _cooldown - (_now - self._vision_last_time))
                    print(f"[Vision] ⏳ Cooldown active ({_wait:.1f}s remaining)")
                    result = (
                        "Vision is briefly cooling down. Wait a moment, then you may capture "
                        "once more to VERIFY the action's result on screen."
                    )
                else:
                    from actions.screen_processor import _capture_camera, _capture_screen
                    self._vision_busy = True
                    self._vision_last_time = _now
                    angle     = args.get("angle", "screen").lower()
                    user_text = args.get("text", "What do you see?")
                    if angle == "camera":
                        img_b, mime_t = await loop.run_in_executor(None, _capture_camera)
                        self.ui.start_camera_stream()
                        self._vision_cam_active = True
                        print(f"[Vision] 📷 Camera: {len(img_b):,} bytes")
                        _stall = "camera"
                    else:
                        img_b, mime_t = await loop.run_in_executor(None, _capture_screen)
                        print(f"[Vision] 🖥️  Screen: {len(img_b):,} bytes")
                        _stall = "screen"
                    self._pending_vision = (img_b, mime_t, user_text, angle)
                    result = (
                        f"[VISION_ACTIVE] {_stall.capitalize()} captured. "
                        f"Immediately say ONE natural sentence in English "
                        f"(e.g. 'Looking at your {_stall} now, sir'). "
                        f"Do NOT describe or guess content - the actual image arrives in the NEXT message."
                    )
            elif name == "close_camera":
                self.ui.stop_camera_stream()
                result = "Camera closed."
            elif name == "web_search":
                from actions.web_search import web_search as web_search_action
                r = await loop.run_in_executor(
                    None,
                    lambda: web_search_action(parameters=args, player=self.ui),
                )
                result = r or "Done."
                _mode = args.get("mode", "search")
                if r and not r.startswith("No results") and not r.startswith("Search failed"):
                    _query = args.get("query") or ", ".join(args.get("items", []))
                    _label = f"{_mode.upper()} - {_query[:38]}" if _query else _mode.upper()
                    self.ui.show_content(_label, r)
            elif name == "system_status":
                from actions.system_monitor import get_system_status
                r = await loop.run_in_executor(None, get_system_status)
                result = str(r)
            elif name == "globe":
                self._globe_tool_called = True
                handler = TOOL_HANDLERS.get("globe")
                r = await loop.run_in_executor(
                    None, lambda: handler(args, self.ui, self.speak))
                result = r or "Done."
            elif name == "shutdown_keysai":
                self.ui.write_log("SYS: Shutdown requested.")
                self.speak("Goodbye, sir.")
                self._begin_shutdown()
            else:
                # Lazy registry dispatch - heavy deps import on first use only
                handler = TOOL_HANDLERS.get(name)
                if handler is None:
                    # Not a core tool — try the plugin registry (drop-in
                    # plugins/*.py discovered at startup).
                    r = await loop.run_in_executor(
                        None,
                        lambda: PluginDispatch.try_plugin(name, args, self.ui, self.speak),
                    )
                    if r is None:
                        result = f"Unknown tool: {name}"
                    else:
                        result = r or "Done."
                else:
                    r = await loop.run_in_executor(None, handler, args, self.ui, self.speak)
                    result = r or "Done."
        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)
        if not self.ui.muted:
            self.ui.set_state("HOLD K TO TALK")
        # Leave the last action on the HUD so the screen always says what just
        # happened, even after the state returns to idle.
        self.ui.set_status_line(f"\u2713 {name}")
        print(f"[Keys.ai] 📤 {name} → {str(result)[:80]}")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )
    # ── shutdown gate ───────────────────────────────────────────────────────────
    _shutdown_in_progress: bool = False
    _speaking_error_in_progress: bool = False

    def _begin_shutdown(self) -> None:
        """Begin a voluntary, one-time shutdown of the assistant.
        Borrowed posture from QwenPaw-style dangerous-action handling: ending the
        session is an explicit transition, not a silent tool call. This gate exists
        so a tool crash, a misread intent, or a plugin failure cannot quietly restart
        or duplicate the shutdown sequence.
        """
        if self._shutdown_in_progress:
            return
        self._shutdown_in_progress = True
        self.ui.write_log("SYS: Shutdown sequence started.")
        def _exit():
            import os, time
            threading.current_thread().name = "keysai-shutdown"
            try:
                self.ui.write_log("SYS: Shutting down Keys.ai now.")
            except Exception:
                pass
            time.sleep(0.8)
            os._exit(0)
        _thread = threading.Thread(
            target=_exit, daemon=True, name="keysai-shutdown"
        )
        _thread.start()

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        import sounddevice as sd
        import numpy as np
        print("[KEYS.AI] 🎤 Mic started")
        loop = asyncio.get_event_loop()
        def _open_mic(dev):
            return sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                device=dev,
                callback=callback,
            )
        def _level(frame) -> float:
            try:
                a = np.asarray(frame, dtype=np.float32)
                return float(np.sqrt((a * a).mean())) / 32768.0
            except Exception:
                return 0.0
        def callback(indata, frames, time_info, status):
            # The wake word hears EVERY frame (cheap, non-blocking) so it can be
            # called even while the microphone is otherwise closed to the model.
            if self._wake is not None:
                self._wake.feed(indata)
            if self.ui.muted or self._phone_active:
                return
            with self._speaking_lock:
                keysai_speaking = self._is_speaking
            if keysai_speaking:
                # Self-echo guard: while we are speaking, only a genuinely
                # different voice may barge in — and only when that is on.
                if not (self._barge_in and self._echo is not None
                        and self._echo.is_user_speech(indata, SEND_SAMPLE_RATE,
                                                      _level(indata))):
                    return
            # The mic is open while K is held (push-to-talk, main window or the
            # mini overlay — one mic path for both) OR for a short window after
            # a wake word. Otherwise it is dropped: closing the window never
            # leaves the assistant hearing.
            if not (self.ui.main_ptt_active
                    or time.monotonic() < self._wake_listen_until):
                return
            try:
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": indata.tobytes(), "mime_type": "audio/pcm"}
                )
            except Exception:
                pass   # queue full/session closing — drop this chunk
        try:
            # Which microphone. resolve() returns None for "system default"
            # and for a saved device that is no longer present — so a headset
            # unplugged since the last run falls back to the built-in mic
            # instead of raising on startup and taking the session with it.
            _mic_name = get_input_device()
            _mic_dev  = audio_devices.resolve(_mic_name, "input")
            if _mic_dev is not None:
                print(f"[Keys.ai] 🎤 Input device: {_mic_name}")
            try:
                _mic_stream = _open_mic(_mic_dev)
            except Exception as _e:
                # A device the picker listed but the driver will not open right
                # now must never mean the assistant cannot hear at all.
                if _mic_dev is None:
                    raise
                print(f"[Keys.ai] ⚠️  Mic '{_mic_name}' failed: {_e} — using default")
                self.ui.write_log(
                    f"SYS: Microphone '{_mic_name}' unavailable — using system default.")
                _mic_stream = _open_mic(None)
            with _mic_stream:
                print("[KEYS.AI] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[KEYS.AI] ❌ Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[KEYS.AI] 👂 Recv started")
        out_buf, in_buf = [], []
        try:
            while True:
                async for response in self.session.receive():
                    # ── Session resumption ───────────────────────────
                    # The server sends this periodically. `resumable` goes
                    # false while a turn is mid-flight — replaying a handle
                    # from that moment is what the flag exists to prevent —
                    # so only resumable handles are kept. This is the entire
                    # fix for "every reconnect forgets everything".
                    _sru = getattr(response, "session_resumption_update", None)
                    if _sru is not None:
                        if getattr(_sru, "resumable", False) and getattr(_sru, "new_handle", None):
                            if self._resume_handle is None:
                                print("[Keys.ai] 🔗 Session resumption armed")
                            self._resume_handle = _sru.new_handle
                    if response.data:
                        if self._interrupted:
                            pass  # discard: interrupted
                        else:
                            if self._turn_done_event and self._turn_done_event.is_set():
                                self._turn_done_event.clear()
                            # Split into ~50 ms chunks so interrupt() stops audio within 50 ms
                            # (24000 Hz × 2 bytes/sample × 0.05 s = 2400 bytes per slice)
                            _audio_data = response.data
                            _SLICE = 2400
                            for _i in range(0, len(_audio_data), _SLICE):
                                self.audio_in_queue.put_nowait(_audio_data[_i : _i + _SLICE])
                    if response.server_content:
                        sc = response.server_content
                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt and txt != (out_buf[-1] if out_buf else ""):
                                out_buf.append(txt)
                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                in_buf.append(txt)
                                self._last_user_speech = time.monotonic()
                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()
                            # If this turn_complete ends an interrupted response, clear the
                            # flag and skip all further processing for that turn.
                            if self._interrupted:
                                self._interrupted = False
                                in_buf  = []
                                out_buf = []
                                continue
                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                                self._route_globe_utterance(full_in)
                                self._session_log.append(f"User: {full_in}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "user",
                                        "text": full_in,
                                        "ts": datetime.now().isoformat(),
                                    }))
                            in_buf = []
                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Keys.ai: {full_out}")
                                self._session_log.append(f"Keys.ai: {full_out}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "keysai",
                                        "text": full_out,
                                        "ts": datetime.now().isoformat(),
                                    }))
                            out_buf = []
                            # Vision injection: model finished tool-response turn → now send the image
                            if self._pending_vision and self.session:
                                import base64 as _b64
                                img_b, mime_t, question, angle = self._pending_vision
                                self._pending_vision = None
                                b64 = _b64.b64encode(img_b).decode("ascii")
                                print(f"[Vision] 📤 {len(img_b):,} bytes (angle={angle}) → main session")
                                await self.session.send_client_content(
                                    turns={"parts": [
                                        {"inline_data": {"mime_type": mime_t, "data": b64}},
                                        {"text": question},
                                    ]},
                                    turn_complete=True,
                                )
                                # Mark next turn_complete behaviour depending on angle
                                if self._vision_cam_active:
                                    # Camera: keep busy until KEYS.AI finishes speaking the answer
                                    self._vision_cam_active    = False
                                    self._vision_close_pending = True
                                else:
                                    # Screen-only: no camera to close; release busy flag now
                                    self._vision_busy = False
                            elif self._vision_close_pending:
                                # This turn_complete IS the vision answer — close camera + release busy flag
                                self._vision_close_pending = False
                                self._vision_busy = False
                                async def _cam_close():
                                    await asyncio.sleep(2.0)
                                    self.ui.stop_camera_stream()
                                asyncio.create_task(_cam_close())
                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[KEYS.AI] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
        except Exception as e:
            print(f"[KEYS.AI] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    def _route_globe_utterance(self, utterance: str) -> None:
        """Send an explicit globe request to the globe even if the model didn't.

        The primary route is the `globe` tool the model calls itself. This is
        the deterministic fallback for the wording the user expects to always
        work — "open the globe", "take me to Kanpur", "open GRO" — so those
        still act when the model happens to answer in words instead.

        A camera flight can take seconds, so the work runs on a worker thread;
        blocking here would stall the receive loop that drains the audio.
        """
        called = getattr(self, "_globe_tool_called", False)
        self._globe_tool_called = False
        if called:
            return
        try:
            from globe.intents import try_parse
            if try_parse(utterance) is None:
                return
        except Exception:
            return

        async def _run_globe():
            try:
                from globe.tools import handle_utterance
                reply = await asyncio.to_thread(
                    handle_utterance, utterance, self.ui, self.speak)
            except Exception as exc:
                print(f"[Keys.ai] globe fallback failed: {exc}")
                return
            if reply:
                self.ui.write_log(f"Keys.ai: {reply}")
                try:
                    self._session_log.append(f"Keys.ai: {reply}")
                except Exception:
                    pass

        asyncio.create_task(_run_globe())

    async def _play_audio(self):
        import sounddevice as sd
        import numpy as np
        print("[KEYS.AI] 🔊 Play started")
        _spk_name = get_output_device()
        _spk_dev  = audio_devices.resolve(_spk_name, "output")
        if _spk_dev is not None:
            print(f"[Keys.ai] 🔊 Output device: {_spk_name}")
        def _open_spk(dev):
            st = sd.RawOutputStream(
                samplerate=RECEIVE_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                device=dev,
            )
            st.start()
            return st
        try:
            stream = _open_spk(_spk_dev)
        except Exception as _e:
            # A chosen output that the host API accepts by name but refuses to
            # open must not cost the user their voice. Fall back, say so.
            if _spk_dev is None:
                raise
            print(f"[Keys.ai] ⚠️  Output device '{_spk_name}' failed: {_e} — using default")
            self.ui.write_log(f"SYS: Speaker '{_spk_name}' unavailable — using system default.")
            stream = _open_spk(None)
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue
                self.set_speaking(True)
                # Feed the HUD avatar and the self-echo guard from the same
                # audio block: the avatar's mouth follows the real level, and
                # the guard hears our own output to tell it from the user.
                try:
                    a = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
                    _lv = float(np.sqrt((a * a).mean())) / 32768.0
                    self.ui.set_hud_level(min(1.0, _lv * 3.0))
                    if self._echo is not None:
                        self._echo.note_output(a, RECEIVE_SAMPLE_RATE, _lv)
                except Exception:
                    pass
                try:
                    await asyncio.to_thread(stream.write, chunk)
                except (RuntimeError, asyncio.CancelledError):
                    break   # executor shutting down — exit cleanly
        except Exception as e:
            print(f"[KEYS.AI] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()
    # ── Morning briefing ────────────────────────────────────────────────────────

    async def _send_startup_briefing(self) -> None:
        """
        Two-phase briefing for instant perceived response:
          Phase 1 — immediate greeting (no tools, no fetch) → Keys.ai speaks in <2s
          Phase 2 — news fetched in background, injected after greeting finishes
        """
        await asyncio.sleep(0.3)
        if not self.session:
            return
        # ── memory ───────────────────────────────────────────────────────────
        memory   = load_memory()
        identity = memory.get("identity", {})
        def _val(k: str) -> str:
            e = identity.get(k, {})
            return (e.get("value", "") if isinstance(e, dict) else str(e)).strip()
        lang = _val("language")
        name = _val("name")
        from datetime import datetime
        time_str = datetime.now().strftime("%H:%M")
        # ── Phase 1: instant greeting — one simple sentence ──────────────────
        lang_clause = f" Respond in {lang}." if lang else ""
        name_clause = f" Address the user as {name}." if name else ""
        # Inject last session context if available — pop removes it so it is
        # never repeated: a briefing that repeats yesterday's line every day
        # trains the user to stop listening to it.
        last = await asyncio.to_thread(pop_last_session)
        session_clause = ""
        if last:
            try:
                _delta = (datetime.now() - datetime.strptime(last["date"], "%Y-%m-%d")).days
                _when  = "earlier today" if _delta == 0 else ("yesterday" if _delta == 1 else f"{_delta} days ago")
            except Exception:
                _when = "last time"
            session_clause = (
                f" Also briefly and naturally mention that {_when}: {last['summary']}"
            )
        p1 = (
            f"Greet the user, mention it is {time_str}, and say you are fetching today's news headlines now."
            f"{session_clause} "
            f"Keep it to 2 short sentences max. Do not call any tools.{lang_clause}{name_clause}"
        )
        await self.session.send_client_content(
            turns={"parts": [{"text": p1}]},
            turn_complete=True,
        )
        self.ui.write_log("SYS: Briefing phase 1 (greeting) sent.")
        # ── Phase 2: fetch news in background, deliver after greeting plays ───
        async def _guarded_news():
            try:
                await self._briefing_news_phase(lang)
            except Exception as e:
                print(f"[Briefing] Phase 2 error: {e}")
                self.ui.write_log(f"SYS: Briefing news phase failed: {e}")
        asyncio.create_task(_guarded_news())

    async def _briefing_news_phase(self, lang: str) -> None:
        """
        Sends phase-2 (news) to Gemini ~1.5 s after phase-1 is dispatched so
        Gemini starts working on it while phase-1 audio is still playing.
        """
        lang_str = f" Respond in {lang}." if lang else ""
        # 1.5 s is enough for Gemini to finish generating phase-1 audio on its
        # side (turn_complete) while the greeting is still being played locally.
        await asyncio.sleep(1.5)
        if not self.session:
            return
        p2 = (
            "[BRIEFING] Call web_search with mode='news' and query='top world news today' "
            "to find actual recent news articles with real event headlines (not just website names). "
            "After the search, say ONE specific news event from the results in one sentence, "
            f"then say the full list is displayed on screen.{lang_str}"
        )
        await self.session.send_client_content(
            turns={"parts": [{"text": p2}]},
            turn_complete=True,
        )
        self.ui.write_log("SYS: Briefing phase 2 (news) sent.")
    # ── System monitor ──────────────────────────────────────────────────────────

    async def _run_system_monitor(self) -> None:
        """Background task: voice alerts when metrics exceed thresholds."""
        if self._sys_monitor is None:
            from actions.system_monitor import SystemMonitor
            self._sys_monitor = SystemMonitor()
        _last_alert = 0.0
        while True:
            await asyncio.sleep(15 if time.monotonic() - _last_alert > 120 else 5)
            alert = await asyncio.to_thread(self._sys_monitor.check)
            if alert:
                _last_alert = time.monotonic()
            if alert and self.session:
                try:
                    await self.session.send_client_content(
                        turns={"parts": [{"text": alert}]},
                        turn_complete=True,
                    )
                except Exception as e:
                    print(f"[Monitor] ⚠️ Could not send alert: {e}")
    # ── Proactive mode ──────────────────────────────────────────────────────────

    async def _run_proactive_mode(self) -> None:
        """
        Background task: periodically checks if the user has been silent long enough,
        then hands time + memory context to Gemini so it can decide what (if anything)
        to say proactively. No hardcoded rules — Gemini makes the call.
        """
        if self._proactive is None:
            from actions.proactive import ProactiveEngine
            self._proactive = ProactiveEngine()
        while True:
            await asyncio.sleep(60)   # evaluate once per minute
            if not self.session:
                continue
            with self._speaking_lock:
                speaking = self._is_speaking
            # Never interrupt active work: speaking, vision capture, or tool busy
            if speaking or self._vision_busy or self._pending_vision is not None:
                continue
            if not self._proactive.should_trigger(self._last_user_speech):
                continue
            self._proactive.mark_triggered()
            try:
                memory = await asyncio.to_thread(load_memory)
                prompt = self._proactive.build_prompt(memory)
                await self.session.send_client_content(
                    turns={"parts": [{"text": prompt}]},
                    turn_complete=True,
                )
                self.ui.write_log("SYS: Proactive check-in.")
            except Exception as e:
                print(f"[Proactive] ⚠️ {e}")
    # ── Background monitor ──────────────────────────────────────────────────

    async def _run_background_monitor(self) -> None:
        """Check user-configured topics once per day; speak alerts when new
        headlines appear."""
        await asyncio.sleep(300)          # wait 5 min after startup before first check
        while True:
            if self.session:
                # Don't interrupt an active conversation
                with self._speaking_lock:
                    speaking = self._is_speaking
                recent_speech = (time.monotonic() - self._last_user_speech) < 30
                if not speaking and not recent_speech:
                    try:
                        alerts = await asyncio.to_thread(monitor_check_all)
                        memory = load_memory()
                        lang_e = memory.get("identity", {}).get("language", {})
                        lang   = (lang_e.get("value", "") if isinstance(lang_e, dict) else str(lang_e)).strip() or "English"
                        for alert in alerts:
                            msg = (
                                f"{alert}\n\n"
                                f"Inform the user about this development naturally in {lang}. "
                                "One brief sentence only."
                            )
                            await self.session.send_client_content(
                                turns={"parts": [{"text": msg}]},
                                turn_complete=True,
                            )
                            self.ui.write_log("SYS: Monitor alert sent.")
                            await asyncio.sleep(6)   # gap between consecutive alerts
                    except Exception as e:
                        print(f"[Monitor] ⚠️ Background check error: {e}")
            await asyncio.sleep(1800)     # check every 30 minutes
    # ── Session memory ──────────────────────────────────────────────────

    async def _save_session_summary(self) -> None:
        """Summarise the current session in 1-2 sentences and save to
        long_term.json — mentioned naturally in the next morning briefing,
        consumed after use so it never repeats."""
        log = self._session_log
        if len(log) < 3:          # need at least one exchange to be worth saving
            return
        self._session_log = []    # reset immediately so the next session starts clean
        memory = load_memory()
        lang_entry = memory.get("identity", {}).get("language", {})
        lang = (lang_entry.get("value", "") if isinstance(lang_entry, dict) else str(lang_entry)).strip()
        lang = lang or "English"
        convo = "\n".join(log[-40:])   # cap at last 40 turns to stay within token budget
        prompt = (
            f"Summarize this conversation in 1-2 sentences in {lang}. "
            "Focus on what the user accomplished or discussed. "
            "Output ONLY the summary text, nothing else:\n\n" + convo
        )
        try:
            from google import genai as _genai
            client = _genai.Client(api_key=_get_api_key())
            resp   = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-flash-latest",
                contents=prompt,
            )
            summary = (resp.text or "").strip()
            if summary:
                save_session_summary(summary, lang)
        except Exception as e:
            print(f"[Memory] ⚠️ Session summary failed: {e}")
    # ── Phone audio relay ────────────────────────────────────────────────────────

    async def _relay_phone_audio(self) -> None:
        """Forward phone mic PCM chunks from dashboard queue into the Gemini Live session."""
        q = self._dashboard._phone_audio_queue
        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # No audio for 1 s → phone mic inactive, give PC mic back
                self._phone_active = False
                continue
            self._phone_active = True   # phone is streaming — silence PC mic
            with self._speaking_lock:
                speaking = self._is_speaking
            if not speaking and not self.ui.muted:
                try:
                    self.out_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass
    # ── WhatsApp incoming-call receptionist mode REMOVED ───────────────────────
    # ── dashboard command relay ─────────────────────────────────────────────

    async def _process_dashboard_commands(self) -> None:
        while True:
            try:
                text = await asyncio.wait_for(
                    self._dashboard._command_queue.get(), timeout=0.5
                )
                if not text:
                    continue
                # Wait up to 8s for session to become ready after a wake
                for _ in range(80):
                    if self.session:
                        break
                    await asyncio.sleep(0.1)
                if self.session:
                    await self.session.send_client_content(
                        turns={"parts": [{"text": text}]},
                        turn_complete=True,
                    )
                    self.ui.write_log(f"[Web]: {text}")
                else:
                    print(f"[Dashboard] Dropped command (no session): {text}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)
    # ── main loop ───────────────────────────────────────────────────────────

    async def run(self):
        self._loop = asyncio.get_event_loop()
        self._reconnect_event = asyncio.Event()
        # ── Wire the shared core services to the interface ───────────────
        # The confirmation gate is useless without a way to ask, and a memory
        # trim is invisible without a way to say so. Both are bound once here
        # rather than passed down through every action signature.
        confirm_ui.install(self.ui._win, log=self.ui.write_log)
        set_trim_notifier(self.ui.write_log)
        # Tell the device picker the exact rates the streams open at, from
        # the constants that actually open them.
        audio_devices.configure(SEND_SAMPLE_RATE, RECEIVE_SAMPLE_RATE)
        # Enumerate audio devices off-thread so the settings drawer never
        # pays for host-API enumeration on the Qt thread.
        audio_devices.prefetch()
        # Start dashboard (optional — needs: pip install fastapi "uvicorn[standard]" cryptography)
        try:
            from dashboard.server import DashboardServer
            self._dashboard = DashboardServer()
            self._dashboard.set_interrupt_callback(self.interrupt)
            # The Live assistant drains this queue below; tell the dashboard so
            # it does not start a second consumer for the same asyncio.Queue.
            self._dashboard.claim_command_queue("assistant")
            asyncio.create_task(self._dashboard.serve())
            # Runs for the whole lifetime, not just inside an active session
            asyncio.create_task(self._process_dashboard_commands())
        except Exception as e:
            print(f"[Dashboard] Disabled: {e}")
            self._dashboard = None
        # WhatsApp incoming-call receptionist — DISABLED for now (calling
        # features removed; messaging only). Re-enable later by calling
        # self.start_call_handler() here when the call feature returns.
        # try:
        #     self.start_call_handler()
        # except Exception as e:
        #     print(f"[CallMode] handler disabled: {e}")
        # ── Self-echo guard (always available; only used when barge-in is on) ─
        try:
            from core.echo import EchoGuard
            self._echo = EchoGuard()
        except Exception as e:
            print(f"[Echo] disabled: {e}")
            self._echo = None
        # ── Wake word (optional, local, opt-in) ────────────────────────────
        # Started once for the whole process. Failure is non-fatal: the mic
        # simply stays push-to-talk.
        try:
            from memory.config_manager import (get_barge_in_enabled,
                                               get_wake_enabled, get_wake_model,
                                               get_wake_threshold)
            self._barge_in = bool(get_barge_in_enabled())
            if get_wake_enabled():
                from core.wake_word import WakeWordDetector
                self._wake = WakeWordDetector(
                    on_detect=self._on_wake_word,
                    threshold=get_wake_threshold(),
                    model_name=get_wake_model(),
                    logger=print,
                    notify=self.ui.write_log,
                )
                if not self._wake.start():
                    self._wake = None
            else:
                print("[Wake] disabled (enable with wake_enabled in config)")
        except Exception as e:
            print(f"[Wake] disabled: {e}")
            self._wake = None
        while True:
            try:
                print("[Keys.ai] Connecting...")
                self.ui.set_state("THINKING")
                _resumed_with = self._resume_handle is not None
                config = self._build_config()
                if not _get_api_key():
                    # The configured LLM provider may not need a Gemini key
                    # (Ollama / OpenRouter / Anthropic brain mode). Keep the
                    # dashboard + text brain alive instead of error-spamming.
                    self.ui.write_log(
                        "SYS: No Gemini API key set — voice is paused. Text "
                        "and the smart brain keep working via the configured "
                        "LLM provider (Settings → AI Provider)."
                    )
                    self.ui.set_state("SLEEPING")
                    await asyncio.sleep(15)
                    continue
                # Fresh client on every reconnect — avoids stale HTTP session state
                from google import genai
                client = genai.Client(
                    api_key=_get_api_key(),
                    http_options={"api_version": "v1beta"}
                )
                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session          = session
                    self.audio_in_queue   = asyncio.Queue()
                    self.out_queue        = asyncio.Queue(maxsize=200)
                    self._turn_done_event = asyncio.Event()
                    # Reset transient state that must not carry over from a previous session
                    self._pending_vision       = None
                    self._vision_cam_active    = False
                    self._vision_close_pending = False
                    self._vision_busy          = False
                    self._vision_last_time     = 0.0
                    self._interrupted          = False
                    print("[Keys.ai] Connected.")
                    if _resumed_with:
                        # Say it plainly: the difference between "it
                        # reconnected" and "it reconnected and still knows
                        # what we were doing" is the whole point.
                        self.ui.write_log("SYS: Reconnected — conversation restored.")
                    self.ui.set_state("HOLD K TO TALK")
                    self.ui.write_log("SYS: Keys.ai online.")
                    if self._dashboard:
                        await self._dashboard.broadcast({"type": "status", "state": "active"})
                    self._reconnect_event.clear()  # ignore requests from before this session
                    tg.create_task(self._watch_reconnect())
                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._run_system_monitor())
                    tg.create_task(self._run_background_monitor())
                    tg.create_task(self._run_proactive_mode())
                    if self._dashboard:
                        tg.create_task(self._relay_phone_audio())
                    # Morning briefing — fires once per process launch
                    if not self._briefing_sent:
                        self._briefing_sent = True
                        tg.create_task(self._send_startup_briefing())
            except KeyboardInterrupt:
                raise
            except SystemExit:
                raise
            except BaseException as e:
                # Catches both Exception and BaseExceptionGroup (Python 3.11+
                # TaskGroup raises BaseExceptionGroup when tasks are cancelled
                # externally, which `except Exception` would miss, letting the
                # exception escape the while-loop and causing asyncio.run() to
                # start shutdown — resulting in "executor after shutdown" errors).
                # Voluntary reconnect — not an error. Rebuild immediately.
                if _is_reconnect_signal(e):
                    print("[Keys.ai] Voluntary reconnect requested.")
                    if not _keep_context_of(e):
                        self._resume_handle = None
                    self._conn_backoff = 0
                    continue
                # A resumption handle the server will not accept — expired, or
                # belonging to a session it has since dropped. Without this,
                # the same dead handle would be replayed on every retry and
                # the feature meant to survive a reconnect would be the thing
                # preventing one. Drop it once and let the next attempt start
                # clean.
                if _resumed_with and (
                    "resum" in str(e).lower()
                    or "handle" in str(e).lower()
                    or "INVALID_ARGUMENT" in str(e)
                    or "NOT_FOUND" in str(e)
                ):
                    print("[Keys.ai] 🔗 Resumption handle rejected — starting a fresh session")
                    self.ui.write_log("SYS: Could not restore the conversation — starting fresh.")
                    self._resume_handle = None
                    self._conn_backoff = 0
                    continue
                err_str = str(e)
                print(f"[Keys.ai] Error ({type(e).__name__}): {e}")
                traceback.print_exc()
                # Enhanced audio features rejected by the server (preview API
                # drift) — drop them and reconnect with the plain config.
                if self._enhanced_live and (
                    "INVALID_ARGUMENT" in err_str
                    or "affective" in err_str.lower()
                    or "proactiv" in err_str.lower()
                    or "Unknown name" in err_str
                    or "unexpected keyword" in err_str
                ):
                    self._enhanced_live = False
                    self.ui.write_log(
                        "SYS: Advanced audio features unavailable — reconnecting without them.")
                    continue
                # Invalid API key — stop hammering the API, prompt re-configuration
                if "API key not valid" in err_str or "1007" in err_str:
                    self.ui.write_log("ERR: API key invalid — please re-enter your key.")
                    self.ui.set_state("SLEEPING")
                    self.ui.prompt_reconfig()
                    while not self.ui._win._ready:
                        await asyncio.sleep(1)
                    print("[KEYS.AI] New API key saved — reconnecting...")
                    _conn_backoff = 3
                    continue
                # Network / timeout errors — log clearly and back off
                is_net_err = any(k in err_str for k in (
                    "TimeoutError", "timed out", "getaddrinfo", "CancelledError",
                    "ConnectionRefusedError", "OSError", "Cannot connect",
                ))
                if is_net_err:
                    _conn_backoff = min(getattr(self, "_conn_backoff", 3) * 2, 60)
                    self._conn_backoff = _conn_backoff
                    self.ui.write_log(
                        f"NET: Could not connect — retrying in {_conn_backoff}s. "
                        "(A VPN may be required.)"
                    )
                else:
                    self._conn_backoff = 3
            finally:
                self.session = None
                # Only save if there was a real conversation (≥3 turns)
                if len(self._session_log) >= 3:
                    asyncio.create_task(self._save_session_summary())
            self.set_speaking(False)
            self.ui.set_state("SLEEPING")
            if self._dashboard:
                await self._dashboard.broadcast({"type": "status", "state": "sleeping"})
            delay = getattr(self, "_conn_backoff", 3)
            print(f"[Keys.ai] Reconnecting in {delay}s...")
            await asyncio.sleep(delay)

def main():
    # ── Health Check: verify all systems before starting ──────────────────────
    # Skip health check in mini/overlay mode for faster startup.
    _mini_only = any(a in ("--mini", "--overlay", "-m") for a in sys.argv)
    _skip_health = "--no-health" in sys.argv or _mini_only
    if not _skip_health:
        try:
            from core.health_check import run_health_check
            print("[Keys.ai] Running system health check...")
            report = run_health_check(verbose=True)
            print(report.summary())
            # Log critical failures
            if report.failures:
                print(f"[Keys.ai] WARNING: {len(report.failures)} critical failure(s) detected!")
                for f in report.failures:
                    print(f"  ✗ {f.name}: {f.message}")
        except Exception as e:
            print(f"[Keys.ai] Health check failed: {e}")
    # Extract a PNG from keys_eye_icon.ico for use as the HUD centre face.
    # The .ico remains the window/taskbar icon (set in ui.py MainWindow).
    _ico_path = BASE_DIR / "keys_eye_icon.ico"
    _face_path = BASE_DIR / "icon.png"
    if _ico_path.exists() and not _face_path.exists():
        try:
            from PIL import Image
            img = Image.open(_ico_path).convert("RGBA")
            img.save(_face_path, "PNG")
        except Exception:
            _face_path = _ico_path  # fallback to .ico if conversion fails
    # --mini / --overlay: launch with ONLY the background popup, no main window.
    if _mini_only:
        print("[Keys.ai] Mini overlay mode — main UI hidden. Hold K to talk (tray to quit).")
    ui = KeysAIUI(str(_face_path), show_main=not _mini_only)
    # ── Administrator mode: detect elevation at startup and surface it in the
    # UI (privilege badge). Legitimate elevation only — never bypasses UAC.
    try:
        from automation.elevation import elevation_status
        ui.set_elevation_status(elevation_status())
        if elevation_status().get("elevated"):
            print("[Keys.ai] 🔓 Running ELEVATED (administrator mode)")
        else:
            print("[Keys.ai] 🔒 Running with normal privileges (admin mode available via 'elevate')")
    except Exception:
        pass
    # ── LLM model warm-up (background) ─────────────────────────────────
    # Reconciles the provider settings with the dev engine, then preloads
    # the local task models (e.g. qwen3.5:4b for the dev agent) so the first
    # coding/chat request doesn't wait for a model load. Hosted providers
    # (gemini/openai/...) are skipped; the call is deduplicated and never
    # raises.

    def _warm_models():
        import time as _time
        _time.sleep(4)   # let startup (UI, dashboard, network) settle first
        try:
            from core import llm_client
            _log = lambda m: ui.write_log(f"SYS: {m}")   # noqa: E731
            # Reconcile the AI provider settings with the dev engine FIRST:
            # start Ollama if idle and pin an installed light model in both
            # config/crown_code.json and api_keys.json task_models, so what
            # the settings show is exactly what runs (no background drift).
            try:
                from core.crown_bridge import sync_local_models
                sync_local_models(log=_log)
            except Exception as e:
                print(f"[Keys.ai] Local model sync skipped: {e}")
            # Dev agent benefits most from a warm model (long generations).
            llm_client.warm_up("dev_agent", logger=_log)
            # The brain model, when it's a different local model on the
            # same server, would also need loading — warm it only if distinct.
            from core.api_config import get_task_model
            da = get_task_model("dev_agent")
            br = get_task_model("brain")
            if (br.get("provider"), br.get("model")) != (da.get("provider"), da.get("model")):
                llm_client.warm_up("brain")
        except Exception as e:
            print(f"[Keys.ai] LLM warm-up skipped: {e}")
    threading.Thread(target=_warm_models, name="llm-warmup", daemon=True).start()

    def runner():
        ui.wait_for_api_key()
        keysai = KeysAILive(ui)
        try:
            asyncio.run(keysai.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")
    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()
if __name__ == "__main__":
    main()
