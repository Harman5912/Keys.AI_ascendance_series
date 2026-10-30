"""
Implement _run_autonomous_portfolio in actions/crown_code.py and wire the routing.
"""
from pathlib import Path

path = Path(r"c:\Users\harma\Desktop\PROJECTS\Keys-acendence-series\acendence-VIII_GEN-I\actions\crown_code.py")
text = path.read_text(encoding="utf-8")

autonomous_portfolio_fn = '''
# ── Autonomous Portfolio Pipeline (No Presets) ──────────────────────────────

def _run_autonomous_portfolio(job, workspace: Path, task: str, requirements: str,
                              stacks: list[str], player=None, model: str = "",
                              provider: str = "", policy: str = "safe",
                              timeout: int = 900, p: dict | None = None) -> dict:
    """Execute the full autonomous portfolio creation pipeline:
    1. Detail Intake & Memory Persistence (long-term memory + entities)
    2. Live Inbuilt Browser Research & Asset Harvesting (Google search, images, SVG icons)
    3. Architecture Blueprint & Master Prompt Synthesis & Display to User
    4. Crown Code Autonomous Builder with Inbuilt Local Model (NO PRESET DESIGN)
    5. Verification & Live Browser Launch
    """
    p = p or {}
    brief = task

    # ── Step 1: Detailing & Memory Persistence ──────────────────────────────
    task_lower = task.lower()
    is_harman = "harman" in task_lower or "harman" in str(requirements or "").lower()

    job.update(phase="detailing", progress=0.1, detail="Saving entity profile to long-term memory")
    if is_harman:
        _status_safe(player, "creation_event", "💾", "Saving Harman Sadhwani profile and projects to memory")
        try:
            from memory.memory_manager import update_memory
            update_memory({
                "identity": {
                    "creator": {"value": "Harman Sadhwani", "updated": time.strftime("%Y-%m-%d")},
                    "role": {"value": "Lead AI Architect & Systems Engineer, Creator of Keys.ai", "updated": time.strftime("%Y-%m-%d")}
                },
                "projects": {
                    "keys_ai": {"value": "Keys.ai autonomous desktop assistant and screen understanding system", "updated": time.strftime("%Y-%m-%d")},
                    "reviewbot": {"value": "AI-powered automated GitHub code review assistant", "updated": time.strftime("%Y-%m-%d")},
                    "drop_of_hope": {"value": "Real-time community blood donation matching platform", "updated": time.strftime("%Y-%m-%d")},
                    "bharathealth": {"value": "AI-assisted healthcare platform", "updated": time.strftime("%Y-%m-%d")}
                }
            })
            print("[Crown] 💾 Saved Harman Sadhwani profile and projects to Keys.ai long-term memory")
        except Exception as _mem_e:
            print(f"[Crown] Memory update note: {_mem_e}")

    # ── Step 2: Inbuilt Browser Research & Asset Harvesting ─────────────────
    job.update(phase="researching", progress=0.25, detail="Inbuilt browser research & asset harvesting")
    _status_safe(player, "creation_event", "🔍", "Inbuilt Browser: researching Google & harvesting assets")
    try:
        harvester = ResearchHarvester(workspace, player)
        research_data = harvester.run(task, stack=", ".join(stacks) if stacks else "HTML5 + Tailwind CSS + Vanilla JS")
    except Exception as e:
        print(f"[Crown] Research harvest note: {e}")
        research_data = {}

    # ── Step 3: Architecture Blueprint & Master Prompt Generation ──────────
    job.update(phase="planning", progress=0.45, detail="Synthesizing Blueprint & Master Prompt")
    _status_safe(player, "creation_event", "📐", "Synthesizing Blueprint & Master Instruction Prompt")
    try:
        blueprint_eng = BlueprintEngine(workspace, player)
        bp_res = blueprint_eng.synthesize(task, str(requirements or ""), research_data)
        master_prompt = bp_res["master_prompt"]
        explanation = bp_res.get("explanation", "")
        if explanation:
            print(f"\\n{explanation}\\n")
            _status_safe(player, "terminal_output", explanation, "stdout", "agent")
            _status_safe(player, "creation_event", "📜", "Master Prompt Synthesized & Displayed")
            _status_safe(player, "speak", "I have synthesized the architectural blueprint and master prompt for your portfolio.")
    except Exception as e:
        print(f"[Crown] Blueprint note: {e}")
        master_prompt = brief

    # ── Step 4: Crown Code Terminal Builder (Inbuilt Local Model, NO PRESET) ─
    job.update(phase="coding", progress=0.6, detail="Crown Code Terminal Builder (Inbuilt Model, No Presets)")
    _status_safe(player, "creation_event", "⚡", "Starting Crown Code autonomous builder with local model")

    _browser_tools = [
        "navigate_to_url", "get_page_text", "get_page_title",
        "capture_screenshot", "capture_full_page", "list_page_images",
        "download_resource", "save_source",
    ]
    _tools = [t for t in (p.get("tools") or []) if t]
    if str(p.get("research_mode") or "").strip().lower() == "browser":
        for _bt in _browser_tools:
            if _bt not in _tools:
                _tools.append(_bt)

    res = _agent_build(job, master_prompt, workspace, model or "", provider, policy,
                        timeout, player, verify_tests=True, tools=_tools)

    # Auto-launch artifact if finished successfully
    if res.get("ok"):
        job.update(phase="launching", progress=0.95, detail="Opening live application")
        _launch_artifact(res, workspace, player)
    return res
'''

# Insert _run_autonomous_portfolio before def _agent_build
if "_run_autonomous_portfolio" not in text:
    target_pos = text.find("def _agent_build(")
    if target_pos != -1:
        text = text[:target_pos] + autonomous_portfolio_fn + "\n\n" + text[target_pos:]
        print("INSERTED _run_autonomous_portfolio")

# Now update the routing in def crown_code
old_routing = '''    if path_kind == "app":
        def target(job):
            return _run_app(job, workspace, app_kind, player)
    elif path_kind == "site" and speed == "preset":
        def target(job):
            return _run_site(job, workspace, kind, model, player, speed=speed)
    else:'''

new_routing = '''    if path_kind == "app":
        def target(job):
            return _run_app(job, workspace, app_kind, player)
    elif path_kind == "site":
        def target(job):
            # If the user requested an autonomous portfolio / Harman Sadhwani / bespoke build without preset design:
            task_l = task.lower()
            if "harman" in task_l or "no preset" in task_l or str(p.get("no_preset", "")).lower() == "true":
                return _run_autonomous_portfolio(job, workspace, task, requirements, stacks, player, model, provider, policy, timeout, p)
            return _run_site(job, workspace, kind, model, player, speed=speed)
    else:'''

if old_routing in text:
    text = text.replace(old_routing, new_routing, 1)
    print("ROUTING UPDATED TO HANDLE AUTONOMOUS PORTFOLIO")
else:
    print("Could not find exact old_routing, trying alternative match")

path.write_text(text, encoding="utf-8")
print("DONE PATCHING ACTIONS/CROWN_CODE.PY")
