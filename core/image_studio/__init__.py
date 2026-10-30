"""AI Image Studio — local, offline image generation for Keys.AI.

Everything here is independent of the coding agent and of the Live voice
session: the UI talks to :class:`ImageGenerationService`, which submits
workflows to a local ComfyUI server. No cloud image API is used, and nothing in
this package modifies the configured chat/coding model.

Public entry points:

    get_service()          the process-wide ImageGenerationService
    registry.MODELS        the model catalogue (generator vs. vision)
    installer.detect()     is ComfyUI installed / running?
"""

from __future__ import annotations

_service = None


def get_service():
    """The shared ImageGenerationService (created on first use)."""
    global _service
    if _service is None:
        from core.image_studio.service import ImageGenerationService
        _service = ImageGenerationService()
    return _service


__all__ = ["get_service"]
