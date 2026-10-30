"""Universal Project Agent — intake, planning, workers, validation, delivery.

The package orchestrates capabilities Keys.AI already has (Crown Code builds,
document builders, web search, the local image studio, Playwright) behind one
resumable task model. It does not replace any of them.

    from universal_agent import get_service
    service = get_service()
    task = service.create("Build a portfolio for a photographer")
    service.answer(task["id"], {"content": "…"})
"""

from __future__ import annotations

_service = None


def get_service():
    """The shared ProjectAgentService (created on first use)."""
    global _service
    if _service is None:
        from universal_agent.service import ProjectAgentService
        _service = ProjectAgentService()
    return _service


__all__ = ["get_service"]
