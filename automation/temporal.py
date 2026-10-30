"""Temporal vision & motion engine (spec 12-14, 21, 24).

The screen is not static. Instead of sending every frame to Gemini, this
module does cheap LOCAL observation:

    • capture_gray()        — mss capture -> small grayscale numpy frame
    • motion_regions(a, b)  — frame differencing -> bounding rects of change
    • stability(region)     — is a UI element still moving (animation/loading)
                              or has it settled so we may interact safely?
    • track_element(...)    — follow a moving element across frames and report
                              position / velocity / direction
    • dhash()               — cheap perceptual hash for change detection
    • loading_estimate()    — is the region in a 'still changing' state?

All OpenCV/numpy imports are lazy; every method returns safe defaults when
cv2/mss are unavailable, so nothing here can ever crash the caller.
"""

from __future__ import annotations

import time
from typing import Optional


def _cv_available() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        import mss  # noqa: F401
        return True
    except Exception:
        return False


def capture_gray(region=None, scale: float = 0.5):
    """Grab the screen (or a region) and return a downscaled grayscale array.
    Returns None when capture is unavailable."""
    if not _cv_available():
        return None
    try:
        import mss
        import numpy as np
        import cv2
        with mss.mss() as sct:
            monitors = sct.monitors
            target = monitors[1] if len(monitors) > 1 else monitors[0]
            if region:
                x, y, w, h = region
                target = {"left": target["left"] + x, "top": target["top"] + y,
                          "width": w, "height": h}
            shot = sct.grab(target)
            frame = np.array(shot)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
            if scale and 0 < scale < 1:
                gray = cv2.resize(gray, None, fx=scale, fy=scale,
                                  interpolation=cv2.INTER_AREA)
            return gray
    except Exception:
        return None


def motion_regions(frame_a, frame_b, threshold: int = 25,
                   min_area: int = 40, origin=None) -> list[tuple]:
    """Frame differencing: return [(x, y, w, h), ...] of changed regions in
    SCREEN coordinates (origin = (left, top) offset of the frames)."""
    if frame_a is None or frame_b is None:
        return []
    try:
        import numpy as np
        import cv2
        if frame_a.shape != frame_b.shape:
            return []
        diff = cv2.absdiff(frame_a, frame_b)
        _, mask = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        ox, oy = origin or (0, 0)
        scale = getattr(frame_a, "_scale", 1.0)
        out = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < min_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            out.append((int(ox + x / scale), int(oy + y / scale),
                        int(w / scale), int(h / scale)))
        return out[:12]
    except Exception:
        return []


def dhash(frame, size: int = 9) -> Optional[int]:
    """Cheap perceptual hash (difference hash). Same image -> same int;
    small changes -> small Hamming distance."""
    if frame is None:
        return None
    try:
        import cv2
        import numpy as np
        small = cv2.resize(frame, (size + 1, size))
        bits = 0
        for y in range(size):
            for x in range(size):
                bits = (bits << 1) | (1 if small[y, x] > small[y, x + 1] else 0)
        return bits
    except Exception:
        return None


def hamming(a: Optional[int], b: Optional[int]) -> int:
    if a is None or b is None:
        return 999
    return bin(a ^ b).count("1")


def stability(region, samples: int = 4, interval: float = 0.12,
              max_drift: float = 0.08) -> tuple[bool, float]:
    """Is the element in `region` still? Samples the region repeatedly.

    Returns (stable, drift_ratio): stable=True means the pixels stopped
    changing enough to interact safely (spec 24 — wait for the target to
    settle before clicking). drift_ratio is the max relative change seen.
    """
    frames = []
    for _ in range(max(2, samples)):
        f = capture_gray(region, scale=0.5)
        if f is not None:
            frames.append(f)
        time.sleep(interval)
    if len(frames) < 2:
        return True, 0.0
    worst = 0.0
    for i in range(1, len(frames)):
        d = hamming(dhash(frames[i - 1]), dhash(frames[i]))
        worst = max(worst, d / 81.0)
    return worst <= max_drift, worst


class TemporalVision:
    """High-level temporal helpers used by the engine."""

    def __init__(self) -> None:
        self._prev_frame = None
        self._prev_hash: Optional[int] = None
        self._origin = (0, 0)

    def snapshot(self, region=None):
        """Capture + record; returns (frame, origin)."""
        import mss
        with mss.mss() as sct:
            monitors = sct.monitors
            target = monitors[1] if len(monitors) > 1 else monitors[0]
            origin = (int(target["left"]), int(target["top"]))
        frame = capture_gray(region)
        if frame is not None:
            self._prev_frame = frame
            self._prev_hash = dhash(frame)
            self._origin = origin
        return frame, origin

    def motion_now(self, region=None) -> list[tuple]:
        """Changed regions between the previous snapshot and now."""
        frame = capture_gray(region)
        if frame is None or self._prev_frame is None:
            self._prev_frame = frame
            return []
        regions = motion_regions(self._prev_frame, frame, origin=self._origin)
        self._prev_frame = frame
        self._prev_hash = dhash(frame)
        return regions

    def changed(self, region=None) -> bool:
        """Cheap change gate: True when the visible pixels moved enough that a
        vision/AI re-read would add information."""
        frame = capture_gray(region)
        if frame is None:
            return False
        h = dhash(frame)
        if self._prev_hash is None:
            self._prev_hash = h
            return False
        dist = hamming(self._prev_hash, h)
        self._prev_hash = h
        return dist > 4   # a handful of bits of change => meaningful

    def track_element(self, region, samples: int = 5, interval: float = 0.1):
        """Follow a moving element: returns list of (x, y) centers over time.
        Returns [] when tracking is unavailable; None when region invalid."""
        if not region or len(region) != 4:
            return None
        centers = []
        import numpy as np
        import cv2
        first = capture_gray(region, scale=0.5)
        if first is None:
            return []
        for _ in range(max(2, samples)):
            f = capture_gray(region, scale=0.5)
            if f is None:
                continue
            res = cv2.matchTemplate(f, first, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > 0.5:
                hh, ww = first.shape
                cx = region[0] + int(max_loc[0] / 0.5) + int(ww / 0.5) // 2
                cy = region[1] + int(max_loc[1] / 0.5) + int(hh / 0.5) // 2
                centers.append((cx, cy))
            time.sleep(interval)
        return centers

    def velocity(self, centers) -> Optional[tuple]:
        """Average per-sample velocity (dx, dy) from a track; None if short."""
        if not centers or len(centers) < 2:
            return None
        dx = sum(b[0] - a[0] for a, b in zip(centers, centers[1:])) / (len(centers) - 1)
        dy = sum(b[1] - a[1] for a, b in zip(centers, centers[1:])) / (len(centers) - 1)
        return (round(dx, 1), round(dy, 1))

    def loading(self, region, samples: int = 5, interval: float = 0.15) -> bool:
        """True while a region keeps changing (progress/loading/animation).
        Uses stability(): not stable over the window => still loading."""
        stable, _ = stability(region, samples=samples, interval=interval,
                              max_drift=0.06)
        return not stable
