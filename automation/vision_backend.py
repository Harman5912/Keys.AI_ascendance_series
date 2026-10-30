"""Backend #3 — Computer Vision + OCR.

Captures the screen with `mss`, finds elements with OpenCV template matching,
reads text with OCR (EasyOCR preferred, optional), and uses an AI vision model
(Gemini, configured via config/api_keys.json `gemini_api_key`) as the smart
fallback for locating described elements. Every detection is converted to
screen coordinates for the input backend to act on.

All optional dependencies degrade gracefully (OpenCV/mss required for capture).
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path
from typing import Optional

from automation.base import Backend, Element, Rect


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_CONFIG_PATH = _base_dir() / "config" / "api_keys.json"


def _load_config() -> dict:
    try:
        from core.config_store import load as _load_cfg
        return _load_cfg()
    except Exception:
        try:
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}


def _get_api_key() -> str:
    return _load_config().get("gemini_api_key", "")


class VisionBackend(Backend):
    name = "vision"
    priority = 3

    def __init__(self) -> None:
        self._cv2 = None
        self._mss = None
        self._ocr = None
        try:
            import cv2  # noqa: F401
            self._cv2 = True
        except Exception:
            self._cv2 = False
        try:
            import mss  # noqa: F401
            self._mss = True
        except Exception:
            self._mss = False
        # OCR engine: EasyOCR preferred; PaddleOCR optional; else None.
        try:
            import easyocr  # noqa: F401
            self._ocr = "easyocr"
        except Exception:
            self._ocr = None

    def available(self) -> bool:
        return bool(self._mss) and bool(self._cv2)

    # ── capture ─────────────────────────────────────────────────────────
    def capture(self) -> Optional[bytes]:
        if not self._mss:
            return None
        try:
            import mss
            import mss.tools
            with mss.mss() as sct:
                monitors = sct.monitors
                target = monitors[1] if len(monitors) > 1 else monitors[0]
                shot = sct.grab(target)
                return mss.tools.to_png(shot.rgb, shot.size)
        except Exception:
            return None

    def _capture_np(self):
        if not self._mss or not self._cv2:
            return None
        try:
            import mss
            import numpy as np
            with mss.mss() as sct:
                monitors = sct.monitors
                target = monitors[1] if len(monitors) > 1 else monitors[0]
                shot = sct.grab(target)
                return np.array(shot), (target["left"], target["top"])
        except Exception:
            return None

    # ── OCR ─────────────────────────────────────────────────────────────
    def ocr_text(self, region=None) -> str:
        """OCR the whole screen (or a (x,y,w,h) region). Returns raw text."""
        if self._ocr is None:
            return ""
        shot = self._capture_np()
        if shot is None:
            return ""
        frame, (ox, oy) = shot
        try:
            import cv2
            if region:
                x, y, w, h = region
                frame = frame[oy + y: oy + y + h, ox + x: ox + x + w]
            else:
                frame = frame[oy:, ox:]
            if self._ocr == "easyocr":
                import easyocr
                reader = getattr(self, "_easy_reader", None)
                if reader is None:
                    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
                    self._easy_reader = reader
                results = reader.readtext(frame, detail=0, paragraph=True)
                return "\n".join(str(t) for t in results)
        except Exception as e:
            print(f"[Vision] ⚠️  OCR failed: {e}")
        return ""

    # ── template matching ───────────────────────────────────────────────
    def find_template(self, template_path: str, threshold: float = 0.8) -> Optional[Element]:
        if not self._cv2 or not self._mss:
            return None
        shot = self._capture_np()
        if shot is None:
            return None
        frame, (ox, oy) = shot
        try:
            import cv2
            import numpy as np
            tpl = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
            if tpl is None:
                return None
            gray = cv2.cvtColor(np.array(frame), cv2.COLOR_BGRA2BGR)
            res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val < threshold:
                return None
            h, w = tpl.shape[:2]
            return Element(name=Path(template_path).stem, control_type="template",
                           rect=Rect(ox + int(max_loc[0]), oy + int(max_loc[1]), w, h),
                           backend="vision", confidence=float(max_val))
        except Exception:
            return None

    # ── AI vision element location ──────────────────────────────────────
    def find_ai(self, description: str) -> Optional[Element]:
        """Ask the Gemini vision model where the described element is."""
        api_key = _get_api_key()
        if not api_key:
            return None
        try:
            from google import genai
            from google.genai import types as gtypes
            import numpy as np
            shot = self._capture_np()
            if shot is None:
                return None
            frame, (ox, oy) = shot
            import cv2
            img = cv2.cvtColor(np.array(frame), cv2.COLOR_BGRA2BGR)
            ok, buf = cv2.imencode(".png", img)
            if not ok:
                return None
            client = genai.Client(api_key=api_key)
            h, w = img.shape[:2]
            prompt = (
                f"This is a {w}x{h} screenshot. Locate the UI element described as: "
                f"'{description}'. Reply with ONLY the center coordinates as: x,y "
                f"(in image pixels, 0,0 = top-left). If not visible, reply NOT_FOUND."
            )
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    gtypes.Part.from_bytes(data=buf.tobytes(), mime_type="image/png"),
                    prompt,
                ],
            )
            text = (resp.text or "").strip()
            if "NOT_FOUND" in text.upper():
                return None
            m = re.search(r"(\d+)\s*,\s*(\d+)", text)
            if not m:
                return None
            cx, cy = int(m.group(1)), int(m.group(2))
            return Element(name=description, control_type="ai",
                           rect=Rect(ox + cx - 25, oy + cy - 25, 50, 50),
                           backend="vision", confidence=0.7)
        except Exception as e:
            print(f"[Vision] ⚠️  AI find failed: {e}")
            return None

    # ── element search (chained: template → AI → OCR text match) ────────
    def find(self, description: str, control_type: str = "", window_title: str = "") -> Optional[Element]:
        desc = (description or "").strip()
        if not desc:
            return None
        # 1) If the description is a file path → template matching.
        p = Path(desc)
        if p.exists() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp"):
            return self.find_template(str(p))
        # 2) AI vision.
        el = self.find_ai(desc)
        if el:
            return el
        # 3) OCR text match → find the bounding box of the phrase.
        el = self._find_ocr(desc)
        return el

    def _find_ocr(self, text: str) -> Optional[Element]:
        if self._ocr is None:
            return None
        shot = self._capture_np()
        if shot is None:
            return None
        frame, (ox, oy) = shot
        try:
            import easyocr
            import numpy as np
            reader = getattr(self, "_easy_reader", None)
            if reader is None:
                reader = easyocr.Reader(["en"], gpu=False, verbose=False)
                self._easy_reader = reader
            results = reader.readtext(np.array(frame)[oy:, ox:], detail=1, paragraph=False)
            target = text.lower()
            for (bbox, txt, conf) in results:
                if target in str(txt).lower():
                    xs = [pt[0] for pt in bbox]
                    ys = [pt[1] for pt in bbox]
                    x0, x1 = min(xs), max(xs)
                    y0, y1 = min(ys), max(ys)
                    return Element(name=str(txt), control_type="ocr",
                                   rect=Rect(ox + int(x0), oy + int(y0),
                                             int(x1 - x0), int(y1 - y0)),
                                   backend="vision", confidence=float(conf))
        except Exception:
            pass
        return None

    # ── screen description ──────────────────────────────────────────────
    def describe_screen(self) -> str:
        """Return a text summary of what's on screen (AI vision + OCR)."""
        img = self.capture()
        if img is None:
            return "Could not capture the screen (mss unavailable)."
        api_key = _get_api_key()
        if not api_key:
            return self.ocr_text() or "Captured the screen but no API key for AI description."
        try:
            from google import genai
            from google.genai import types as gtypes
            client = genai.Client(api_key=api_key)
            prompt = (
                "Describe what is on this computer screen: the active application, "
                "visible windows, key UI elements (buttons, fields, menus, text), "
                "and any notable content. Be concise but specific."
            )
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    gtypes.Part.from_bytes(data=img, mime_type="image/png"),
                    prompt,
                ],
            )
            ai = (resp.text or "").strip()
            ocr = self.ocr_text()
            if ocr:
                ai += f"\n\n[OCR text detected]\n{ocr[:1500]}"
            return ai
        except Exception as e:
            return f"Could not describe screen: {e}"
