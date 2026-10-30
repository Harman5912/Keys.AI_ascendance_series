"""
Patch actions/crown_code.py to wire the full pipeline:
Memory detailing -> Inbuilt Browser research -> Blueprint & Prompt Display -> Crown Code Local Model (No presets)
"""
from pathlib import Path

path = Path(r"c:\Users\harma\Desktop\PROJECTS\Keys-acendence-series\acendence-VIII_GEN-I\actions\crown_code.py")
text = path.read_text(encoding="utf-8")

old_target_block = '''    # Execution target: app recipes build offline; site builds use site_builder; all other builds use the autonomous pipeline
    if path_kind == "app":
        def target(job):
            return _run_app(job, workspace, app_kind, player)
    elif path_kind == "site":
        def target(job):
            return _run_site(job, workspace, kind, model, player, speed=speed)
    else:
        def target(job):
            # Phase 2: Autonomous Research Mode & Asset Harvesting
            job.update(phase="researching", progress=0.2, detail="Harvesting documentation, icons & assets")
            _status_safe(player, "creation_event", "🔍", "Autonomous Research Mode: scraping assets & design tokens")
            try:
                harvester = ResearchHarvester(workspace, player)
                research_data = harvester.run(task, stack=", ".join(stacks))
            except Exception as e:
                print(f"[Crown] Research harvest note: {e}")
                research_data = {}

            # Phase 3: Architecture Blueprint & Master Prompt Generation
            job.update(phase="planning", progress=0.35, detail="Synthesizing Architecture Blueprint")
            _status_safe(player, "creation_event", "📐", "Synthesizing Blueprint & Master Instruction Prompt")
            try:
                blueprint_eng = BlueprintEngine(workspace, player)
                bp_res = blueprint_eng.synthesize(task, str(requirements or ""), research_data)
                master_prompt = bp_res["master_prompt"]
            except Exception as e:
                print(f"[Crown] Blueprint note: {e}")
                master_prompt = brief

            # Phase 4: Crown Code Terminal Builder
            job.update(phase="coding", progress=0.5, detail="Crown Code Terminal Builder")
            _status_safe(player, "creation_event", "⚡", "Starting Crown Code autonomous builder")

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
            return res'''

new_target_block = '''    # Execution target:
    # app recipes build offline
    # site builds: if speed == "preset", use _run_site (retained for backward compatibility / tests)
    # ALL OTHER builds (including portfolios & websites by default) use the full Autonomous Pipeline:
    # 1. Detail Intake & Memory Persistence ->
    # 2. Inbuilt Browser Research & Asset Harvesting ->
    # 3. Blueprint & Master Prompt Synthesis & Display to User ->
    # 4. Crown Code Inbuilt Local Model (Bespoke Generation, NO PRESET DESIGN)
    if path_kind == "app":
        def target(job):
            return _run_app(job, workspace, app_kind, player)
    elif path_kind == "site" and speed == "preset":
        def target(job):
            return _run_site(job, workspace, kind, model, player, speed=speed)
    else:
        def target(job):
            # Phase 1: Detailing & Memory Persistence
            task_lower = task.lower()
            if "harman" in task_lower or "harman" in str(requirements or "").lower():
                job.update(phase="detailing", progress=0.1, detail="Saving entity profile to memory")
                _status_safe(player, "creation_event", "💾", "Saving Harman Sadhwani profile and projects to long-term memory")
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

            # Phase 2: Autonomous Inbuilt Browser Research & Asset Harvesting
            job.update(phase="researching", progress=0.25, detail="Inbuilt browser research & asset harvesting")
            _status_safe(player, "creation_event", "🔍", "Inbuilt Browser: researching Google & harvesting assets")
            try:
                harvester = ResearchHarvester(workspace, player)
                research_data = harvester.run(task, stack=", ".join(stacks))
            except Exception as e:
                print(f"[Crown] Research harvest note: {e}")
                research_data = {}

            # Phase 3: Architecture Blueprint & Master Prompt Generation & Display
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

            # Phase 4: Crown Code Terminal Builder (Inbuilt Local Model, NO PRESET DESIGN)
            job.update(phase="coding", progress=0.6, detail="Crown Code Terminal Builder (Local Model, No Presets)")
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
            return res'''

if old_target_block in text:
    text = text.replace(old_target_block, new_target_block, 1)
    path.write_text(text, encoding="utf-8")
    print("CROWN_CODE TARGET PATCHED OK")
else:
    print("Could not find exact old_target_block in actions/crown_code.py")
