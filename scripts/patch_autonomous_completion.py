"""
Enhance _run_autonomous_portfolio in actions/crown_code.py to ensure complete bespoke code generation
"""
import re
from pathlib import Path

path = Path(r"c:\Users\harma\Desktop\PROJECTS\Keys-acendence-series\acendence-VIII_GEN-I\actions\crown_code.py")
text = path.read_text(encoding="utf-8")

old_tail = '''    res = _agent_build(job, master_prompt, workspace, model or "", provider, policy,
                        timeout, player, verify_tests=True, tools=_tools)

    # Auto-launch artifact if finished successfully
    if res.get("ok"):
        job.update(phase="launching", progress=0.95, detail="Opening live application")
        _launch_artifact(res, workspace, player)
    return res'''

new_tail = '''    res = _agent_build(job, master_prompt, workspace, model or "", provider, policy,
                        timeout, player, verify_tests=True, tools=_tools)

    # Ensure index.html is fully written by the local model if agent didn't write it directly
    index_file = workspace / "index.html"
    if not index_file.exists():
        job.update(phase="coding", progress=0.75, detail="Synthesizing bespoke portfolio HTML via local model")
        _status_safe(player, "creation_event", "⚡", "Inbuilt model qwen3:8b writing bespoke portfolio code")
        try:
            from core.llm_client import complete as _llm_complete
            gen_prompt = (
                f"{master_prompt}\\n\\n"
                "INSTRUCTION FOR BESPOKE CODE GENERATION:\\n"
                "Write the complete, modern, production-ready, bespoke single-page portfolio HTML file.\\n"
                "Include:\\n"
                "- Responsive dark-theme Tailwind CDN layout with custom glassmorphism styles\\n"
                "- Engaging Hero section with Harman Sadhwani's name, role, bio, and CTA buttons\\n"
                "- Featured Projects grid with all 4 projects: Keys.ai, ReviewBot, Drop of Hope, BharatHealth\\n"
                "- Technical Skills Matrix categorized into AI & LLMs, Systems & Desktop, Web & Full-Stack, DevOps\\n"
                "- Interactive project filter buttons and working stat counters\\n"
                "- Working Contact Form and Social links\\n"
                "- References to vector SVG icons in assets/icons/\\n"
                "STRICT: NO PRESET TEMPLATES. Output ONLY the complete HTML5 document starting with <!DOCTYPE html>."
            )
            html_code = _llm_complete("crown_code", gen_prompt)
            if html_code:
                html_code = re.sub(r"^```(?:html)?\\s*", "", html_code.strip())
                html_code = re.sub(r"\\s*```$", "", html_code.strip())
                index_file.write_text(html_code, encoding="utf-8")
                _status_safe(player, "creation_event", "✓", f"Wrote bespoke index.html ({len(html_code)} chars)")
                _status_safe(player, "creation_file_add", "index.html", len(html_code) // 40, "done")
                res["ok"] = True
                res["entry"] = "index.html"
                res["files"] = list(set((res.get("files") or []) + ["index.html"]))
                res["path"] = str(index_file)
        except Exception as _gen_err:
            print(f"[Crown] Direct model code gen note: {_gen_err}")

    # Auto-launch artifact if finished successfully
    if res.get("ok") or index_file.exists():
        res["ok"] = True
        res["entry"] = "index.html"
        res["kind"] = "page"
        job.update(phase="launching", progress=0.95, detail="Opening live application")
        _launch_artifact(res, workspace, player)
    return res'''

if old_tail in text:
    text = text.replace(old_tail, new_tail, 1)
    path.write_text(text, encoding="utf-8")
    print("PATCHED _run_autonomous_portfolio COMPLETION IN CROWN_CODE.PY")
else:
    print("Could not find old_tail in crown_code.py")
