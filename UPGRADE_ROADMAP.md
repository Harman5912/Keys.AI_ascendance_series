# Keys.ai × Mark-LV — Feature Upgrade Roadmap

> Sources reviewed: this repo (Keys.ai / Keys-acendence) and
> `Mark-LV-main.zip` (the "MARK LV" JARVIS assistant it descends from).
> Purpose: list everything worth porting or building to make Keys.ai
> demonstrably better, with the exact integration point, effort and risk for
> each item.

---

## Delivered in this pass (verified)

| Item | Files | Verification |
|---|---|---|
| **Model ladder** — measured order, per-call deadline, quota/outage/404 cooldowns, backup-key rotation | `core/gemini_ladder.py` (new), `core/llm_client.py`, `brain/providers/gemini.py` | `test_gemini_ladder.py` — **6/6 pass** (network-free) |
| **Self-echo guard** + **local wake word** (opt-in, zero-cost when off) | `core/echo.py`, `core/wake_word.py` (new), `main.py`, `memory/config_manager.py` | headless: echo rejects its own output; wake imports without openwakeword |
| **Terminal UX** — ANSI colour, ↑/↓ history, cwd prompt, coloured exit-code chips | `ui.py` (`CreationWorkspace`) | offscreen: history + colour/exit-chip insertion pass |
| **Holographic avatar** — reuses real geometry, drives the HUD face | `core/avatar.py`, `avatar_mesh.py`, `viseme.py`, `face_model.obj`, `core/avatar_bridge.py`, `ui.py` | offscreen: `HudCanvas` renders the avatar (14,400 lit px) |
| **F1 shortcut / feature overlay** | `ui.py` (`ShortcutsOverlay`) | offscreen: overlay renders, recentres, starts hidden |
| **Memory panel (F2)** — view and forget every stored fact | `ui.py` (`MemoryPanel`), `memory/memory_manager.py` | offscreen: loads the real store (8 entries), forget removes one |
| **Command palette (Ctrl+K)** — fuzzy action launcher | `ui.py` (`CommandPalette`) | offscreen: filter + run a command pass |
| **Forget-archive safeguard** — deleted facts are kept in `memory/forgotten.json` | `memory/memory_manager.py` | verified archiving + no-mutation-on-miss, without touching the live store |
| **Always-on status HUD** — one dim line showing the running/finished tool | `ui.py` (`HudCanvas.status_line`), `main.py` | offscreen: pixel-diff confirms the line is drawn; clamped so it never clips |
| **Presentation mode (F3)** — full-window feature-card showcase | `ui.py` (`PresentationOverlay`) | offscreen: 8 cards, ←/→/space/Esc navigation, renders |
| **Live theming (F9)** — retint HUD + avatar across 5 themes, persisted | `ui.py` (`_THEMES`, `apply_theme`), `memory/config_manager.py` | offscreen: theme change repaints 62k pixels; config round-trip |
| **In-session coding-model picker** — switch Ollama model from the terminal header | `ui.py` (`CreationWorkspace`), `core/crown_bridge.py` | verified: writes/clears `config/crown_code.json` (restored after test) |

### Still to do (next focused passes)

* Part B/3: **video on the HUD** (yt-dlp) — needs QMediaPlayer/QGraphicsVideoItem and a real
  media run to verify, so it was deliberately left for its own pass rather than shipped unverified.
* Part C remaining: Python fallback agent, hunk-level diff review, multi-session terminal tabs.
* Part E remaining: dashboard-as-second-screen.
* Own idea remaining: **agent activity timeline**.

> Themes retint the painted HUD + avatar; panels built earlier keep their
> construction-time styles, so first-paint widgets stay gold until re-created.
> Deliberately scoped this way: it is coherent on the demo surface and cannot
> half-reskin every widget.

> The GUI end-to-end run (UAC launch) was not executed headlessly; each new
> module and the HUD render were verified directly under an offscreen Qt
> platform, and every changed file passes `py_compile`.

---

## Part A — What Keys.ai already has (so we don't rebuild it)

Keys.ai is already a **superset** of Mark LV in almost every tool category. Do
**not** re-add these:

| Area | Keys.ai status |
|---|---|
| Coding agent | **Crown Code terminal agent** (Node headless bridge + Ollama + embedded TERMINAL pane) — Mark LV has no equivalent |
| Multi-provider LLM | `brain/providers/` (Gemini, Anthropic, OpenAI-compat) + `ai_settings` backup-key rotation |
| Desktop automation | `automation/` (UIA → native → vision/OCR → mouse/kb), `agent_control/` visible takeover, `computer_use`, `hybrid_control` |
| Undo / confirmation | `core/undo.py`, `core/confirm.py` + `confirm_ui.py` ✅ already ported |
| Memory | `save_memory` / `recall_memory` tools, `memory/` store, key-index |
| Audio devices | `core/audio_devices.py` ✅ already ported |
| Plugin/skills | `core/plugin_loader.py`, `skills/registry.py`, `plugins/` |
| Proactive / monitoring / reminders | `actions/proactive.py`, `background_monitor.py`, `reminder.py`, `manage_monitor` tool |
| Voice picker, morning briefing, session summaries | present (`main.py`, `memory/memory_manager.py`) |
| Web dashboard | `dashboard/` (FastAPI + login + `static/app.html`) |
| Phone / WhatsApp / Google accounts / email | present (beyond Mark LV entirely) |

**Conclusion:** the value of the zip is **not** its tools — it is its
*experience layer* (the face, the wake word, the reliability ladder, the demo
polish). Those are what Keys.ai is missing.

---

## Part B — Gaps worth closing (from Mark LV)

### P0 — Demo showstoppers

**1. Holographic avatar + lip-sync + facial acting** ⭐ highest impact
- **Today:** `ui.py` → `HudCanvas` (line 387) loads a **static circular PNG**
  (`_load_face`, line 426) — the "face" is just a masked icon.
- **Mark LV has:** `core/avatar.py` (software-rendered lit head), `avatar_mesh.py`
  (loads `face_model.obj`, 468-vertex MediaPipe face, Apache-2.0), `viseme.py`
  (~50 mouth shapes/sec fused from audio formants **and** transcript), plus
  brow/gaze/blink/nod "facial acting" and "face-as-status" (looks away while
  thinking, eyes meet you while listening).
- **Integration:** replace `HudCanvas._load_face` with the mesh renderer; feed
  `main.py`'s audio loop (sounddevice @ ~594 / ~787) and Live transcript into
  `viseme.py`; drive state from the existing think/speak/listen signals.
- **Effort:** L (2–4 days). **Risk:** M (touches HUD paint + audio path).
- **Why:** this is the single thing that makes a demo look like a product.

**2. Local wake word ("Hey Keys")**
- **Today:** absent. Talk is push-to-talk (K / F5).
- **Mark LV:** `core/wake_word.py` — local `openwakeword`, own thread, offline,
  auto-sleeps after 2 min idle, never streams audio while asleep.
- **Integration:** new `core/wake_word.py`; gate the mic in `main.py`; toggle in
  `SetupOverlay`; add optional dep. Lazy-import (see D3).
- **Effort:** M. **Risk:** L.

**3. Video "where the face is" (on the HUD)**
- **Today:** `youtube_video` opens in the browser.
- **Mark LV:** `actions/video_player.py` plays YouTube/local/URL **inside the
  HUD** (two-stream video+audio, language-first track pick, starts muted, mic
  mutes while sound is on).
- **Integration:** a video surface in `HudCanvas`; reuse the existing preview
  browser in `CreationWorkspace` as a fallback; add `yt-dlp`.
- **Effort:** M. **Risk:** M.

### P1 — Reliability & "it never hangs"

**4. Model ladder with measured order, timeouts and cooldowns**
- **Today:** `core/llm_client.py` has **no timeout** on the direct genai
  fallback (`_build_gemini_fallback`, line ~115) and no cooldown for a model
  that 503/504s — a bad alias can stall a call. `ai_settings` rotates *keys*
  but not *models*.
- **Mark LV:** `core/gemini.py` — one ladder of 9 models ordered by **measured**
  latency, a ≥10 s deadline on every call, and cooldowns (429 → 5 min,
  503/504 → 30 min, 404 → 6 h). Measured saving: 11.2 s on every subsequent call.
- **Integration:** new `core/gemini_ladder.py`; route `llm_client`, tools that
  make their own one-shot calls, and `brain/providers/gemini.py` through it.
- **Effort:** M. **Risk:** L. **Why:** turns "it sometimes hangs" into "it
  always answers."

**5. Self-echo guard**
- `core/echo.py` — recognises the tail of the assistant's own voice and drops
  it instead of muting the user. Effort S, risk L.

**6. Instant acknowledgment**
- Speak a short, context-aware "on it…" the moment a long task starts (before
  Crown Code / browser runs), so the assistant is never silent. Effort S.

### P2 — Polish

**7. Live theming** — `ui.py` colour palette (`class C`, line 101) + a hue/hex
control in settings; avatar retints to match. Effort S–M.

**8. Memory panel UI** — `recall_memory` exists as a tool but there is no panel;
add an overlay (same pattern as `AgentSettingsOverlay`) to view/delete facts.
Effort S.

**9. Clipboard intelligence** — copy text → floating Translate / Summarise /
Explain / Fix popup. Effort M.

**10. Auto-start on boot** — registry Run key, surfaced in `install.py`/setup.
Effort S.

---

## Part C — Terminal agent (Crown Code) upgrades

Crown Code is already strong (real shell, exit codes, streamed output). Gaps:

1. **No native fallback** — if Node or Ollama is missing, coding is simply
   unavailable. Add a pure-Python agent fallback (`core/engine/`) so the tool
   always works.
2. **Terminal UX** — ANSI colour parsing, ↑/↓ command history, copy/paste,
   a live `cwd` prompt, per-command **exit-code chips**, and "rerun last".
3. **Diff review** — show syntax-highlighted diffs with accept/reject per hunk
   instead of trusting the write.
4. **Model picker in-session** — switch between e.g. `qwen2.5-coder:7b` (fast)
   and `qwen3-coder:30b` (deep) without editing `config/crown_code.json`.
5. **Multi-session tabs** — run more than one coding job without losing the
   previous console.
6. **Approval queue** — non-blocking list of pending risky actions instead of a
   modal dialog (keeps the demo flowing).

---

## Part D — "Basics" hardening (smoothness)

1. **Timeout + cooldown everywhere** (see B4) — the biggest perceived-quality win.
2. **UTF-8 log safety** — ensure emoji/arrow status prints can't raise
   `UnicodeEncodeError` on non-UTF-8 consoles and kill a session.
3. **Lazy imports at startup** — Mark LV cut plugin discovery 211 ms → 39 ms by
   deferring heavy module imports. Measure our boot; defer `openwakeword`,
   `yt-dlp`, Playwright, etc.
4. **Tool-declaration bloat** — the `agent_control` / `computer_use` /
   `browser_control` descriptions are enormous and are sent on **every**
   connection. Consolidate shared verbs to cut tokens per session.
5. **Settings panel instant-open** — mirror Mark LV's fix (do heavy state checks
   off the UI thread).

---

## Part E — UI / demo polish

1. **Presentation mode** — a guided showcase overlay: live feature cards,
   one-key "next demo", on-screen narration of what the agent is doing.
2. **Shortcut overlay (F1)** — list all hotkeys; great for a demo.
3. **Live status HUD** — show active tool/agent, model, and a subtle activity
   indicator at all times.
4. **Consistent glass/neon system** — unify `GlassBackdrop`, panels and the
   avatar's theme.
5. **Web dashboard as a second screen** — drive `dashboard/` alongside the HUD
   during a demo.

---

## Recommended build order

| Order | Item | Effort | Risk |
|---|---|---|---|
| 1 | Model ladder + timeouts/cooldowns (B4) | M | L |
| 2 | Holographic avatar + lip-sync (B1) | L | M |
| 3 | Wake word (B2) | M | L |
| 4 | Terminal agent UX + Python fallback (C1–C3) | M | M |
| 5 | Video on HUD (B3) | M | M |
| 6 | Theming + memory panel + clipboard (B7–B9) | S–M | L |
| 7 | Presentation mode + shortcut overlay (E1–E2) | M | L |

Items 1 and 4 are the safest high-value starts. Item 2 is the demo winner but
is the most invasive, so it deserves its own focused pass with a run-check.
