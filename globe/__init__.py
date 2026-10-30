"""God's Eye View integration for Keys.AI.

The globe is a real third-party application (MIT), vendored under
``integrations/gods_eye_view`` and run as a local service; Keys.AI hosts it in
its own Chromium workspace and drives it through the application's own action
runner. There is no globe launcher button anywhere: text and voice commands are
the way in.

    from globe import get_service
    service = get_service()
    service.open()
    service.navigate("Kanpur, Uttar Pradesh, India")
"""

from __future__ import annotations

__version__ = "0.1.0"
__upstream__ = "https://github.com/bilawalsidhu/gods-eye-view"

__all__ = ["get_service", "__version__", "__upstream__"]


def get_service():
    from globe.service import get_service as _get
    return _get()
