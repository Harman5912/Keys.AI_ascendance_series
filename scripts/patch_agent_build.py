"""Patch _agent_build in actions/crown_code.py to add CROWN_ENGINE feature flag."""
from pathlib import Path

path = Path(r"c:\Users\harma\Desktop\PROJECTS\Keys-acendence-series\acendence-VIII_GEN-I\actions\crown_code.py")
text = path.read_text(encoding="utf-8")

# Find the line after the docstring close: the `result = _run_bridge(...)` call
OLD = '''    result = _run_bridge(job, brief, workspace, model, provider, policy, timeout,
                         player, max_iterations=int(timeout / 30),
                         verify_tests=verify_tests, tools=tools)'''

NEW = '''    import os as _os
    _engine_flag = _os.environ.get("CROWN_ENGINE", "legacy").lower().strip()

    if _engine_flag == "v2":
        # ── v2 engine path ────────────────────────────────────────────────────
        try:
            from crown_code.engine.events import reset_bus
            from crown_code.engine.events import ProgressEvent, ErrorEvent
            from crown_code.engine.interface import make_engine
            from crown_code.engine.ui_adapter import UIAdapter

            bus = reset_bus()
            cfg = {
                "model": model or "",
                "provider": provider or "ollama",
                "ollama_url": _os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
                "max_iterations": max(10, int(timeout / 30)),
            }
            engine = make_engine(job_id=job.id, brief=brief,
                                 workspace=str(workspace),
                                 bus=bus, config=cfg, engine_type="v2")

            UIAdapter(bus=bus, player=player, speak_done=True).attach()

            def _on_v2_event(evt):
                if isinstance(evt, ProgressEvent):
                    job.update(phase=evt.phase, progress=evt.percent,
                               detail=evt.message, log=evt.message)
                elif isinstance(evt, ErrorEvent):
                    job.update(log=f"[error] {evt.message}")
            bus.subscribe(_on_v2_event)

            engine.start()
            engine.join(timeout=timeout + 60)
            result = engine.result or {"ok": False, "summary": "No result returned."}
        except Exception as _exc:
            result = {"ok": False, "summary": f"v2 engine error: {_exc}"}
    else:
        # ── legacy path (original CrownBridge subprocess) ─────────────────────
        result = _run_bridge(job, brief, workspace, model, provider, policy, timeout,
                             player, max_iterations=int(timeout / 30),
                             verify_tests=verify_tests, tools=tools)'''

if OLD in text:
    text = text.replace(OLD, NEW, 1)
    path.write_text(text, encoding="utf-8")
    print("PATCHED OK")
else:
    # Try to find it without exact match
    idx = text.find("result = _run_bridge(job, brief, workspace, model, provider, policy, timeout,")
    print(f"OLD not found, _run_bridge at index {idx}")
    # Show what's around it
    if idx > 0:
        print(repr(text[idx-5:idx+200]))
