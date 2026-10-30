"""
dashboard/server.py — Keys.ai Local HTTP Dashboard with AI Processing

Provides WebSocket and REST API for the local React frontend.
Processes text commands AND audio mic input through:
  - Text → LLM (Ollama / OpenAI-compatible via core/llm_client.py)
  - Audio → VAD → accumulate → Gemini transcription → LLM → response

Install deps:  pip install fastapi "uvicorn[standard]" google-genai numpy
"""

import asyncio
import io
import json
import os
import secrets
import struct
import traceback
from datetime import datetime
from pathlib import Path

_DEPS_OK = False
try:
    from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import JSONResponse
    import uvicorn
    _DEPS_OK = True
except ImportError:
    pass

BASE_DIR    = Path(__file__).resolve().parent.parent
STATIC_DIR  = Path(__file__).parent / "static"
PORT        = 8000
# Bind to loopback by default: /local-ws accepts unauthenticated commands that
# are executed by the assistant, so exposing it on 0.0.0.0 let anyone on the
# local network drive the desktop. Override deliberately with
# KEYSAI_DASHBOARD_HOST (e.g. 0.0.0.0) only on a trusted network.
HOST        = os.environ.get("KEYSAI_DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1"

# Mutating endpoints (/api/command, /api/settings*, /api/google/*) and the
# WebSocket control messages (command / wake / interrupt) require this token.
# Loopback binding alone is not enough: any page the user visits can POST to
# http://127.0.0.1:8000 from the browser, and a local process can do it
# directly. A client other than the desktop app must be given the token out of
# band via KEYSAI_DASHBOARD_TOKEN; without that variable the token is random
# per process and known only to the embedder.
DASHBOARD_TOKEN_ENV = "KEYSAI_DASHBOARD_TOKEN"

# ── VAD & Audio Constants ─────────────────────────────────────────────────────
SAMPLE_RATE      = 24000          # matches micCapture.js SAMPLE_RATE
CHUNK_DURATION_MS = 170           # ~CHUNK_SIZE / SAMPLE_RATE * 1000
VAD_THRESHOLD    = 0.020          # energy threshold for speech
VAD_SILENCE_MS   = 800            # ms of silence to end utterance (shorter than frontend's 1200ms cooldown)
VAD_MIN_SPEECH_MS = 300           # minimum speech to trigger
MAX_UTTERANCE_MS = 15000          # max recording length

# ── LLM integration ──────────────────────────────────────────────────────────

def _get_llm_response(text: str) -> str:
    """Answer a dashboard command through the configured provider.

    This used to construct its own Gemini client pinned to
    ``models/gemini-2.0-flash-lite``, so the dashboard kept answering on Gemini
    after the user switched providers (and stopped answering at all when the
    Gemini key was removed). It now shares the app's per-task routing.
    """
    try:
        from core import llm_client
        # No max_tokens: a reasoning model (deepseek-r1, qwq) spends the whole
        # budget on its scratchpad and returns empty content, so a 200-token
        # cap produced "no answer" after ~45s instead of a reply.
        out = llm_client.complete(
            "brain", text, system=_load_system_prompt(),
        )
        return (out or "").strip()
    except Exception as e:
        print(f"[AI] Dashboard completion failed: {e}")
        return ("I could not reach the configured AI provider. "
                "Check Settings → AI Provider.")


def _transcribe_audio_pcm(pcm_bytes: bytes) -> str:
    """Transcribe raw PCM int16 mono audio using Google Gemini."""
    try:
        import google.genai as genai
        from google.genai import types

        # Wrap PCM as WAV in memory (Gemini expects WAV/MP3, not raw)
        wav_buffer = _pcm_to_wav(pcm_bytes, SAMPLE_RATE)

        api_key = _get_api_key()
        client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})

        response = client.models.generate_content(
            model="models/gemini-2.0-flash-lite",
            contents=[
                types.Part.from_bytes(data=wav_buffer.getvalue(), mime_type="audio/wav"),
                types.Part.from_text("Transcribe this audio. Only respond with the exact words spoken, no commentary."),
            ],
        )
        return response.text.strip() if response.text else ""
    except Exception as e:
        print(f"[AI] Transcription failed: {e}")
        return ""


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int) -> io.BytesIO:
    """Convert raw PCM int16 mono bytes to WAV in-memory."""
    import numpy as np
    buf = io.BytesIO()
    num_samples = len(pcm_bytes) // 2
    # Write WAV header
    data_size = len(pcm_bytes)
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))          # chunk size
    buf.write(struct.pack("<H", 1))            # PCM format
    buf.write(struct.pack("<H", 1))            # mono
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", sample_rate * 2))  # byte rate
    buf.write(struct.pack("<H", 2))            # block align
    buf.write(struct.pack("<H", 16))           # bits per sample
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(pcm_bytes)
    buf.seek(0)
    return buf


def _get_api_key() -> str:
    # Through config_store, so a credential held in encrypted storage is
    # decrypted here instead of looking missing.
    try:
        from core.config_store import load as _load_config
        return str(_load_config().get("gemini_api_key", "") or "")
    except Exception:
        cfg_path = BASE_DIR / "config" / "api_keys.json"
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)["gemini_api_key"]


def _load_system_prompt() -> str:
    prompt_path = BASE_DIR / "core" / "prompt.txt"
    try:
        return prompt_path.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are Keys.ai, a premium AI assistant. "
            "Be concise, direct, and helpful. Answer questions clearly."
        )


# ── Simple Energy-Based VAD ──────────────────────────────────────────────────

class _VAD:
    """Simple energy-based Voice Activity Detector for PCM int16 data."""

    def __init__(self, threshold=VAD_THRESHOLD, silence_ms=VAD_SILENCE_MS,
                 min_speech_ms=VAD_MIN_SPEECH_MS, max_utterance_ms=MAX_UTTERANCE_MS):
        self.threshold = threshold
        self.silence_samples = int(silence_ms * SAMPLE_RATE / 1000)
        self.min_speech_samples = int(min_speech_ms * SAMPLE_RATE / 1000)
        self.max_utterance_samples = int(max_utterance_ms * SAMPLE_RATE / 1000)
        self.buffer = bytearray()
        self.silent_count = 0
        self.speech_active = False
        self.speech_samples = 0

    def _rms(self, chunk: bytes) -> float:
        if len(chunk) < 2:
            return 0.0
        samples = len(chunk) // 2
        import numpy as np
        arr = np.frombuffer(chunk[:samples * 2], dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(arr ** 2) + 1e-12)) / 32768.0

    def add_chunk(self, chunk: bytes) -> dict | None:
        """Process a PCM chunk. Returns {'utterance': bytes} when speech ends, else None."""
        if len(chunk) < 2:
            return None

        energy = self._rms(chunk)
        is_speech = energy > self.threshold

        if is_speech:
            self.silent_count = 0
            if not self.speech_active:
                self.speech_active = True
                self.speech_samples = 0
                self.buffer = bytearray()
            self.buffer.extend(chunk)
            self.speech_samples += len(chunk) // 2

            # Max utterance length guard
            if self.speech_samples >= self.max_utterance_samples:
                utterance = bytes(self.buffer)
                self._reset()
                return {"utterance": utterance, "reason": "max_length"}
        else:
            if self.speech_active:
                self.buffer.extend(chunk)
                self.silent_count += len(chunk) // 2
                if self.silent_count >= self.silence_samples:
                    # Check minimum speech length
                    if self.speech_samples >= self.min_speech_samples:
                        utterance = bytes(self.buffer)
                        self._reset()
                        return {"utterance": utterance, "reason": "silence"}
                    else:
                        # Too short — discard
                        self._reset()
                        return None
            else:
                # Silence while not speaking — ignore
                pass

        return None

    def flush(self) -> bytes | None:
        """Return any buffered speech without waiting for silence timeout.
        Used when the audio connection drops mid-utterance."""
        if self.speech_active and self.speech_samples >= self.min_speech_samples:
            utterance = bytes(self.buffer)
            self._reset()
            return utterance
        self._reset()
        return None

    def _reset(self):
        self.buffer = bytearray()
        self.silent_count = 0
        self.speech_active = False
        self.speech_samples = 0
        self.utterance_result = None


# ── DashboardServer ───────────────────────────────────────────────────────────

class DashboardServer:

    def __init__(self):
        self._clients: set[WebSocket]     = set()
        self._history: list[dict]         = []
        self._command_queue               = asyncio.Queue()
        self._wake_callback               = None
        self._interrupt_callback          = None
        self._phone_audio_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._processing_enabled          = True  # set False to pause AI
        self._vad                         = _VAD()
        self._mic_active                  = False
        # Bearer token for mutating routes; see DASHBOARD_TOKEN_ENV above.
        self.auth_token = (os.environ.get(DASHBOARD_TOKEN_ENV) or "").strip() \
            or secrets.token_urlsafe(24)
        # Exactly one consumer may drain _command_queue. The desktop app
        # claims it at startup; otherwise this server drains it itself.
        self._command_owner = "dashboard"
        self.app                          = self._build_app()

    # ── callbacks ────────────────────────────────────────────────────────

    def set_wake_callback(self, fn) -> None:
        self._wake_callback = fn

    def set_interrupt_callback(self, fn) -> None:
        self._interrupt_callback = fn

    # ── command-queue ownership ──────────────────────────────────────────

    def claim_command_queue(self, owner: str = "assistant") -> None:
        """Declare that someone else drains ``_command_queue``.

        Two coroutines awaiting the same queue made the answer to a dashboard
        command depend on which one woke first: the Live assistant replied to
        some messages and the flash-lite sidecar to others, silently. Calling
        this from the host app stops the sidecar consumer from starting.
        """
        self._command_owner = (owner or "assistant").strip().lower()

    # ── auth helpers ─────────────────────────────────────────────────────

    def _authorized(self, presented) -> bool:
        """Constant-time check of a presented token."""
        if not self.auth_token:
            return False
        try:
            return secrets.compare_digest(str(presented or ""), self.auth_token)
        except Exception:
            return False

    @staticmethod
    def _presented_token(request) -> str:
        """Token from X-KeysAI-Token, Authorization: Bearer, or ?token=."""
        try:
            tok = request.headers.get("x-keysai-token", "")
            if not tok:
                auth = request.headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    tok = auth[7:]
            if not tok:
                tok = request.query_params.get("token", "")
            return tok or ""
        except Exception:
            return ""

    def _unauthorized(self) -> "JSONResponse":
        return JSONResponse(
            {"ok": False, "error": "unauthorized",
             "detail": "Send the dashboard token in X-KeysAI-Token"},
            status_code=401,
        )

    # ── broadcast ────────────────────────────────────────────────────────

    async def broadcast(self, msg: dict) -> None:
        self._history.append(msg)
        if len(self._history) > 300:
            self._history = self._history[-300:]
        dead: set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    # ── Background Processing Tasks ──────────────────────────────────────

    async def _process_commands(self):
        """Process text commands from the WebSocket queue through the LLM."""
        while True:
            try:
                text = await asyncio.wait_for(
                    self._command_queue.get(), timeout=0.5
                )
            except asyncio.TimeoutError:
                continue
            except Exception:
                await asyncio.sleep(0.5)
                continue

            if not text or not self._processing_enabled:
                continue

            print(f"[AI] Processing command: {text[:60]}...")
            await self.broadcast({
                "type": "status", "state": "thinking"
            })

            try:
                # Run LLM in executor to avoid blocking the event loop
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, _get_llm_response, text)

                if response:
                    await self.broadcast({
                        "type": "log",
                        "speaker": "keysai",
                        "text": response,
                        "ts": datetime.now().isoformat(),
                    })
                    final_state = "listening" if self._mic_active else "idle"
                    await self.broadcast({
                        "type": "status", "state": final_state
                    })
                    print(f"[AI] Response: {response[:80]}...")
                else:
                    await self.broadcast({
                        "type": "log",
                        "speaker": "sys",
                        "text": "AI returned empty response.",
                        "ts": datetime.now().isoformat(),
                    })
            except Exception as e:
                print(f"[AI] Command processing error: {e}")
                traceback.print_exc()
                await self.broadcast({
                    "type": "log",
                    "speaker": "sys",
                    "text": f"ERR: AI processing failed — {str(e)[:100]}",
                    "ts": datetime.now().isoformat(),
                })
                await self.broadcast({
                    "type": "status", "state": "idle"
                })

    async def _process_utterance(self, utterance: bytes, source: str = "vad"):
        """Transcribe audio utterance and get AI response, broadcasting results.
        Used by both VAD and WS disconnect flush to avoid duplicating the pipeline."""
        if len(utterance) < 160:
            return

        print(f"[AI] Processing utterance ({source}, {len(utterance)} bytes)...")
        await self.broadcast({
            "type": "sys",
            "text": "Processing speech...",
            "ts": datetime.now().isoformat(),
        })
        await self.broadcast({"type": "status", "state": "thinking"})

        try:
            loop = asyncio.get_event_loop()
            transcript = await loop.run_in_executor(
                None, _transcribe_audio_pcm, utterance
            )

            if transcript:
                print(f"[AI] Transcript: {transcript[:80]}...")
                await self.broadcast({
                    "type": "log",
                    "speaker": "user",
                    "text": transcript,
                    "ts": datetime.now().isoformat(),
                })

                # Get LLM response
                response = await loop.run_in_executor(
                    None, _get_llm_response, transcript
                )

                if response:
                    await self.broadcast({
                        "type": "log",
                        "speaker": "keysai",
                        "text": response,
                        "ts": datetime.now().isoformat(),
                    })
            else:
                print("[AI] No transcript returned")
                await self.broadcast({
                    "type": "log",
                    "speaker": "sys",
                    "text": "Could not understand audio — please try again or type your message.",
                    "ts": datetime.now().isoformat(),
                })
        except Exception as e:
            print(f"[AI] Audio processing error: {e}")
            traceback.print_exc()
            await self.broadcast({
                "type": "log",
                "speaker": "sys",
                "text": f"ERR: Audio processing failed — {str(e)[:100]}",
                "ts": datetime.now().isoformat(),
            })

        final_state = "listening" if self._mic_active else "idle"
        await self.broadcast({"type": "status", "state": final_state})

    async def _process_audio(self):
        """Accumulate audio, detect speech via VAD, transcribe, and respond."""
        while True:
            try:
                chunk_data = await asyncio.wait_for(
                    self._phone_audio_queue.get(), timeout=0.2
                )
            except asyncio.TimeoutError:
                continue
            except Exception:
                await asyncio.sleep(0.2)
                continue

            if not self._processing_enabled:
                continue

            pcm_bytes = chunk_data.get("data", b"")
            if not pcm_bytes:
                continue

            # Feed into VAD
            result = self._vad.add_chunk(pcm_bytes)

            if result is not None:
                utterance = result.get("utterance", b"")
                await self._process_utterance(utterance, "vad")

    # ── FastAPI app ───────────────────────────────────────────────────────

    def _build_app(self) -> "FastAPI":
        app = FastAPI(docs_url=None, redoc_url=None)

        # CORS — allow the React dev server and local dashboard to connect
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:5173",
                "http://localhost:8000",
                "file://",
                "app://-",
            ],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # ── Local WebSocket ─────────────────────────────────────────────
        @app.websocket("/local-ws")
        async def ws_local(websocket: WebSocket):
            await websocket.accept()
            # Read-only broadcasts are open; control messages are not.
            control_ok = self._authorized(
                websocket.query_params.get("token", "")
                or websocket.headers.get("x-keysai-token", "")
            )
            self._clients.add(websocket)
            # Send recent history
            for entry in self._history[-50:]:
                try:
                    await websocket.send_json(entry)
                except Exception:
                    break
            try:
                while True:
                    data = await websocket.receive_json()
                    msg_type = data.get("type", "")

                    if msg_type == "auth":
                        # Late upgrade: a client that connected without a token
                        # may present one, once.
                        control_ok = self._authorized(data.get("token", ""))
                        await websocket.send_json({
                            "type": "auth", "ok": bool(control_ok),
                        })
                        continue

                    if msg_type in ("command", "wake", "interrupt") and not control_ok:
                        await websocket.send_json({
                            "type": "error", "code": "unauthorized",
                            "error": "This dashboard requires a token to control Keys.ai.",
                        })
                        continue

                    if msg_type == "command":
                        text = (data.get("text") or "").strip()
                        if text:
                            # Log it immediately and queue for processing
                            await self.broadcast({
                                "type": "log",
                                "speaker": "user",
                                "text": text,
                                "ts": datetime.now().isoformat(),
                            })
                            await self._command_queue.put(text)
                            if self._wake_callback:
                                self._wake_callback()

                    elif msg_type == "wake":
                        if self._wake_callback:
                            self._wake_callback()

                    elif msg_type == "interrupt":
                        if self._interrupt_callback:
                            self._interrupt_callback()

                    elif msg_type == "ping":
                        await websocket.send_json({"type": "pong"})

                    elif msg_type == "toggle_mute":
                        # Mute state changed — broadcast it
                        await self.broadcast({
                            "type": "status",
                            "state": "muted" if data.get("muted") else "idle",
                            "ts": datetime.now().isoformat(),
                        })

            except WebSocketDisconnect:
                pass
            finally:
                self._clients.discard(websocket)

        # ── Local audio WebSocket ────────────────────────────────────────
        @app.websocket("/local-ws-audio")
        async def local_audio_ws(websocket: WebSocket):
            await websocket.accept()
            await self.broadcast({
                "type": "sys",
                "text": "Browser microphone connected.",
                "ts": datetime.now().isoformat(),
            })
            self._vad = _VAD()  # fresh VAD per connection
            try:
                while True:
                    data = await websocket.receive_bytes()
                    try:
                        self._phone_audio_queue.put_nowait(
                            {"data": data, "mime_type": "audio/pcm"}
                        )
                    except asyncio.QueueFull:
                        pass  # drop frame rather than block
            except WebSocketDisconnect:
                pass
            finally:
                await self.broadcast({
                    "type": "sys",
                    "text": "Browser microphone stopped.",
                    "ts": datetime.now().isoformat(),
                })
                # Flush and process any pending utterance directly
                pending = self._vad.flush()
                if pending:
                    asyncio.create_task(
                        self._process_utterance(pending, "disconnect")
                    )
                self._vad = _VAD()  # clean slate for next connection
                self._mic_active = False

        # ── Local status endpoint ────────────────────────────────────────
        @app.get("/api/local/status")
        async def local_status():
            try:
                import psutil
                cpu = psutil.cpu_percent(interval=None)
                mem = psutil.virtual_memory().percent
                net_counters = psutil.net_io_counters()
                net = (net_counters.bytes_sent + net_counters.bytes_recv) / (1024 * 1024)
                gpu = -1.0
                try:
                    import pynvml
                    pynvml.nvmlInit()
                    h = pynvml.nvmlDeviceGetHandleByIndex(0)
                    gpu = float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
                except Exception:
                    pass
                return JSONResponse({
                    "ok": True,
                    "metrics": {
                        "cpu": cpu,
                        "mem": mem,
                        "net": net,
                        "gpu": gpu,
                        "tmp": -1.0,
                    }
                })
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        # ── Send command via REST ─────────────────────────────────────────
        @app.post("/api/command")
        async def api_command(request: Request, data: dict):
            if not self._authorized(self._presented_token(request)):
                return self._unauthorized()
            text = (data.get("text") or "").strip()
            if text:
                await self.broadcast({
                    "type": "log",
                    "speaker": "user",
                    "text": text,
                    "ts": datetime.now().isoformat(),
                })
                await self._command_queue.put(text)
                return JSONResponse({"ok": True})
            return JSONResponse({"ok": False, "error": "Empty text"}, status_code=400)

        # ── Health check ──────────────────────────────────────────────────
        @app.get("/health")
        async def health():
            return JSONResponse({
                "ok": True,
                "clients": len(self._clients),
                "mic_active": self._mic_active,
                "queue_sizes": {
                    "commands": self._command_queue.qsize(),
                    "audio": self._phone_audio_queue.qsize(),
                },
            })

        # ── Logs — recent broadcast history (brain events, fallback, etc.) ─
        @app.get("/api/logs")
        async def api_logs(request):
            n = 100
            try:
                n = int(request.query_params.get("n", "100"))
            except (ValueError, TypeError):
                n = 100
            entries = self._history[-n:]
            return JSONResponse({"ok": True, "logs": entries, "total": len(self._history)})

        # ── AI provider / API key settings ────────────────────────────────
        @app.get("/api/settings")
        async def api_settings_get():
            try:
                from core import api_config
                return JSONResponse(api_config.provider_status())
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        @app.post("/api/settings")
        async def api_settings_set(request: Request, data: dict):
            if not self._authorized(self._presented_token(request)):
                return self._unauthorized()
            try:
                from core import api_config
                api_config.set_provider(
                    provider=data.get("provider", ""),
                    model=data.get("model", ""),
                    api_key=data.get("api_key", ""),
                    base_url=data.get("base_url", ""),
                )
                return JSONResponse({"ok": True, **api_config.provider_status()})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        @app.post("/api/settings/reset-key")
        async def api_settings_reset(request: Request, data: dict | None = None):
            if not self._authorized(self._presented_token(request)):
                return self._unauthorized()
            try:
                from core import api_config
                msg = api_config.reset_api_key((data or {}).get("provider") or None)
                return JSONResponse({"ok": True, "message": msg,
                                     **api_config.provider_status()})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        # ── Google accounts (multiple sign-in) ────────────────────────────
        @app.get("/api/google/accounts")
        async def google_accounts():
            try:
                from core import firebase_client as fb
                return JSONResponse({
                    "ok": True,
                    "configured": fb.is_configured(),
                    "accounts": fb.get_accounts(),
                    "active": fb.available_from_accounts(),
                    "status": fb.status(),
                })
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        @app.post("/api/google/sign-in")
        async def google_sign_in(request: Request):
            """Opens the browser for Google sign-in (blocks until approved)."""
            if not self._authorized(self._presented_token(request)):
                return self._unauthorized()
            try:
                from core import firebase_client as fb
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, fb.sign_in)
                return JSONResponse({"ok": True, "message": result,
                                     "accounts": fb.get_accounts()})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        @app.post("/api/google/switch")
        async def google_switch(request: Request, data: dict):
            if not self._authorized(self._presented_token(request)):
                return self._unauthorized()
            try:
                from core import firebase_client as fb
                msg = fb.switch_account(data.get("account", ""))
                return JSONResponse({"ok": True, "message": msg,
                                     "accounts": fb.get_accounts()})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        @app.post("/api/google/remove")
        async def google_remove(request: Request, data: dict):
            if not self._authorized(self._presented_token(request)):
                return self._unauthorized()
            try:
                from core import firebase_client as fb
                msg = fb.remove_account(data.get("account", ""))
                return JSONResponse({"ok": True, "message": msg,
                                     "accounts": fb.get_accounts()})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        return app

    # ── serve ─────────────────────────────────────────────────────────────

    async def serve(self) -> None:
        if not _DEPS_OK:
            print("[Dashboard] fastapi/uvicorn not installed — dashboard disabled.")
            print("[Dashboard] Run:  pip install fastapi 'uvicorn[standard]'")
            return

        # Start background processing tasks. The command consumer only starts
        # when this server owns the queue — otherwise the desktop assistant is
        # already draining it and a second consumer would race for messages.
        if self._command_owner == "dashboard":
            asyncio.create_task(self._process_commands())
        else:
            print(f"[Dashboard] command queue owned by '{self._command_owner}' "
                  "— sidecar consumer not started.")
        asyncio.create_task(self._process_audio())

        cfg = uvicorn.Config(
            self.app, host=HOST, port=PORT, log_level="warning",
        )

        print(f"[Dashboard] http://{HOST}:{PORT}")
        print("[Dashboard] AI processing enabled — listening for commands and audio.")
        await uvicorn.Server(cfg).serve()
