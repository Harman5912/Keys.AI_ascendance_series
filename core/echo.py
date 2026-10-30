"""
core/echo.py — telling the user's voice apart from Keys.ai's own echo.

For a moment after a reply ends, sound is still leaving the speakers: writing
to an audio device returns when the buffer accepts the audio, not when the room
has finished with it. Streaming the microphone during that gap is how an
assistant hears its own last sentence and answers itself. This module lets the
echo tail drop our own voice while still passing a user who replies instantly,
instead of blanket-muting the microphone.

Why not a level test
--------------------
Deciding "the microphone is louder than the echo" needs to know how loud the
echo *is*, and that is not a constant — it depends on volume, mic placement,
the room, headphones, and whether a hand is over the mic. A single tuned number
is wrong for almost everyone.

What this does instead
----------------------
Two independent signals, neither needing per-machine tuning:

1. **Content.** Echo is not merely loud — it is *the same sound we just played*.
   Both streams are reduced to a handful of band energies, and as much of the
   recent output as fits is *subtracted* from the microphone block. Pure echo
   cancels to almost nothing; a second voice survives the subtraction because
   its formants sit in bands where ours were weak.

2. **A learned echo gain.** Whenever the content check says "that is definitely
   just echo", the observed mic-to-output ratio is folded into a running
   estimate, so the system calibrates itself to the room within a few seconds.

Band energies (not raw spectra) keep the comparison sample-rate agnostic, which
matters here: the microphone runs at 16 kHz and playback at 24 kHz.

Ported from the Mark LV assistant; kept behaviour-identical.
"""

from __future__ import annotations

import time

import numpy as np

# Log-spaced edges across the range that carries speech. Coarse on purpose:
# fine bins would track pitch, and pitch is what differs between two people
# saying the same word — we want the *timbre* that echo preserves.
_BAND_EDGES = (200, 400, 700, 1100, 1700, 2600, 3800, 5200, 7000)

_HISTORY_S = 1.5      # how far back an echo could plausibly have been played
_MIN_LEVEL = 0.06     # below this the mic is room noise; nothing to decide

_MIN_USER = 0.15      # never call anything below this a voice
_HEAD_Q = 97          # percentile of observed echo the threshold must clear
_HEAD_MULT = 1.15     # ...with this much headroom above it

_UNRELIABLE_FLOOR = 0.22
_BLOCKS_NORMAL = 5    # ~320 ms of sustained evidence
_BLOCKS_NOISY = 12    # ~770 ms when the room is this hard

_FLOOR_WINDOW = 60    # blocks kept to characterise the room's echo
_FLOOR_Q = 35         # percentile taken as "typical echo here"
_WARMUP = 16          # blocks (~1 s) of listening before judging anyone
_RELEARN_RUN = 28     # a 'voice' lasting this long means the room changed


def band_energies(pcm, sr: int) -> np.ndarray:
    """Raw energy per speech band — the fingerprint we compare."""
    x = np.asarray(pcm, dtype=np.float32)
    if x.size < 64:
        return np.zeros(len(_BAND_EDGES) - 1, dtype=np.float32)
    x = x - x.mean()
    n = 1 << (int(x.size) - 1).bit_length()          # next power of two
    mag = np.abs(np.fft.rfft(x * np.hanning(x.size), n=n))
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    out = np.empty(len(_BAND_EDGES) - 1, dtype=np.float32)
    for i in range(len(_BAND_EDGES) - 1):
        m = (freqs >= _BAND_EDGES[i]) & (freqs < _BAND_EDGES[i + 1])
        out[i] = float(mag[m].sum())
    return out


class EchoGuard:
    """Classifies microphone blocks while the assistant is speaking.

    Usage: `note_output()` from the playback path, `is_user_speech()` from the
    microphone callback. Both are cheap enough to sit in an audio thread — one
    small FFT each.
    """

    def __init__(self) -> None:
        self._hist: list[tuple[float, np.ndarray, float]] = []   # (t, bands, level)
        self._gain = 0.6          # mic level per unit of output level; learned
        self._seen = 0            # how many echo blocks the estimate has seen
        self._last_sim = 0.0
        self._last_expected = 0.0
        self._residuals: list[float] = []   # recent ECHO residuals only
        self._floor = 0.10        # typical echo residual here; learned
        self._run = 0             # consecutive blocks called speech
        self._head = 0.13         # near-worst echo residual here; learned

    # ── diagnostics, for the log and for tests ──────────────────────────────

    @property
    def gain(self) -> float:
        return self._gain

    @property
    def calibrated(self) -> bool:
        return self._seen >= 8

    @property
    def floor(self) -> float:
        return self._floor

    @property
    def reliable(self) -> bool:
        return self._floor < _UNRELIABLE_FLOOR

    @property
    def threshold(self) -> float:
        return max(_MIN_USER, self._head * _HEAD_MULT)

    @property
    def required_blocks(self) -> int:
        return _BLOCKS_NORMAL if self.reliable else _BLOCKS_NOISY

    @property
    def last_similarity(self) -> float:
        return self._last_sim

    def reset(self) -> None:
        """Playback stopped — drop the history, keep what was learned."""
        self._hist.clear()
        self._last_sim = 0.0

    # ── the two entry points ────────────────────────────────────────────────

    def note_output(self, pcm, sr: int, level: float, when: float | None = None) -> None:
        """Record a slice of what is being played, for later comparison."""
        try:
            t = time.monotonic() if when is None else when
            self._hist.append((t, band_energies(pcm, sr), float(level)))
            cutoff = t - _HISTORY_S
            if len(self._hist) > 8:
                self._hist = [h for h in self._hist if h[0] >= cutoff]
        except Exception:
            pass          # never let bookkeeping disturb playback

    def is_user_speech(self, pcm, sr: int, level: float,
                       when: float | None = None) -> bool:
        """True if this microphone block is a different voice, not our echo."""
        try:
            if level < _MIN_LEVEL:
                if self._hist and max(h[2] for h in self._hist) > 0.15:
                    self._residuals.append(0.0)
                    if len(self._residuals) > _FLOOR_WINDOW:
                        del self._residuals[:-_FLOOR_WINDOW]
                    if len(self._residuals) >= _WARMUP:
                        self._floor = float(np.percentile(self._residuals, _FLOOR_Q))
                        self._head = float(np.percentile(self._residuals, _HEAD_Q))
                self._run = 0
                return False
            if not self._hist:
                return True

            t = time.monotonic() if when is None else when
            bands = band_energies(pcm, sr)
            total = float(bands.sum())
            if total <= 1e-9:
                return False

            best_res, best_level = 1.0, 0.0
            for ts, ref, ref_level in self._hist:
                if ts > t or t - ts > _HISTORY_S:
                    continue
                denom = float(np.dot(ref, ref))
                if denom < 1e-12:
                    continue
                alpha = max(0.0, float(np.dot(bands, ref)) / denom)
                residual = np.maximum(bands - alpha * ref, 0.0)
                ratio = float(residual.sum()) / total
                if ratio < best_res:
                    best_res, best_level = ratio, ref_level
            self._last_sim = 1.0 - best_res

            if best_level <= 0.0:
                return True

            warming = len(self._residuals) < _WARMUP
            thr = self.threshold
            speech = (not warming) and best_res >= thr

            if speech:
                self._run += 1
                if self._run > _RELEARN_RUN:
                    self._residuals.clear()
                    self._run = 0
                    return False
                return True

            self._run = 0
            self._residuals.append(best_res)
            if len(self._residuals) > _FLOOR_WINDOW:
                del self._residuals[:-_FLOOR_WINDOW]
            if len(self._residuals) >= _WARMUP:
                self._floor = float(np.percentile(self._residuals, _FLOOR_Q))
                self._head = float(np.percentile(self._residuals, _HEAD_Q))
            if warming:
                return False

            if best_res <= self._floor * 1.15 and best_level > 0.05:
                obs = level / max(best_level, 1e-6)
                self._gain += (min(obs, 3.0) - self._gain) * 0.08
                self._seen = min(self._seen + 1, 999)
            return False
        except Exception:
            return False      # any doubt: do not interrupt
