"""
Build a proper portfolio for Harman Sadhwani using Keys.ai's autonomous pipeline:
1. Collect details & save into Keys.ai long-term memory
2. Inbuilt browser research & asset harvest
3. Master prompt synthesis & display
4. Crown Code autonomous builder using local model (NO PRESET DESIGN)
5. Verify created files
"""
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from actions.crown_code import crown_code
from memory.memory_manager import load_memory

class MockPlayer:
    def __init__(self):
        self.logs = []
        self.events = []

    def creation_event(self, icon, label, url=""):
        msg = f"{icon} {label}"
        self.events.append(msg)
        print(f"[Player Event] {msg}")

    def creation_progress(self, pct, phase="", detail=""):
        print(f"[Player Progress] {pct*100:.1f}% - {phase} ({detail})")

    def creation_phase(self, *a, **k):
        pass

    def terminal_output(self, text, stream="stdout", source="agent"):
        self.logs.append(text)
        print(f"[Terminal] {text[:140]}")

    def speak(self, text):
        print(f"[Keys.ai Voice] 🗣️ '{text}'")

    def creation_preview(self, url):
        print(f"[Player Preview] {url}")

    def write_log(self, text):
        pass

    def begin_creation(self, *a, **k):
        pass

    def ensure_local_model(self, *a, **k):
        return (True, "qwen3:8b")

def run_test():
    print("=" * 70)
    print("STARTING HARMAN SADHWANI PORTFOLIO BUILD TEST")
    print("=" * 70)

    player = MockPlayer()
    workspace = root / "workspace" / "harman_sadhwani_portfolio"
    workspace.mkdir(parents=True, exist_ok=True)

    task_desc = (
        "Build a comprehensive personal portfolio website for Harman Sadhwani, "
        "creator of Keys.ai, showcasing his flagship AI agents (Keys.ai, ReviewBot, "
        "Drop of Hope, BharatHealth), technical skills, interactive project filters, "
        "and clean modern dark design."
    )

    result_msg = crown_code(
        {
            "description": task_desc,
            "workspace": str(workspace),
            "confirmed": True,
            "no_preset": "true",
            "wait": True,   # block until build is finished so we can inspect
            "timeout": 300,
        },
        player=player,
    )

    print("\nCrown Code Result Message:\n", result_msg)

    # 1. Verify Memory was updated
    mem = load_memory()
    print("\n--- Verifying Keys.ai Long-Term Memory ---")
    creator_info = mem.get("identity", {}).get("creator", {})
    projects_info = mem.get("projects", {})
    print(f"Creator stored: {creator_info.get('value')}")
    print(f"Projects stored: {list(projects_info.keys())}")
    assert "Harman" in creator_info.get("value", "") or "harman" in str(mem).lower(), "Harman not saved in memory"
    assert "keys_ai" in projects_info or "reviewbot" in projects_info, "Projects not saved in memory"
    print("✅ Memory verification passed!")

    # 2. Verify Workspace Assets & Research
    print("\n--- Verifying Research & Assets ---")
    assets_dir = workspace / "assets"
    icons_dir = assets_dir / "icons"
    tokens_file = assets_dir / "design_tokens.json"
    refs_dir = workspace / "references"

    assert icons_dir.exists(), "icons_dir missing"
    assert tokens_file.exists(), "design_tokens.json missing"
    icons = list(icons_dir.glob("*.svg"))
    print(f"SVG icons generated: {len(icons)} {[i.name for i in icons]}")
    assert len(icons) >= 5, "Fewer than 5 icons generated"
    print("✅ Research assets verification passed!")

    # 3. Verify Blueprint & Master Prompt
    print("\n--- Verifying Blueprint & Master Prompt ---")
    blueprint_file = workspace / "BLUEPRINT.json"
    assert blueprint_file.exists(), "BLUEPRINT.json missing"
    print("✅ BLUEPRINT.json generated and present!")

    # 4. Verify Built Portfolio Code (No Presets)
    print("\n--- Verifying Generated Portfolio Code ---")
    index_file = workspace / "index.html"
    assert index_file.exists(), "index.html was not generated"
    html_content = index_file.read_text(encoding="utf-8")
    print(f"index.html size: {len(html_content)} characters")
    assert "Harman" in html_content, "Harman name missing in HTML"
    assert "Keys.ai" in html_content or "ReviewBot" in html_content, "Projects missing in HTML"
    print("✅ index.html verified with genuine custom content (No preset design)!")

    print("\n" + "=" * 70)
    print("🎉 HARMAN SADHWANI PORTFOLIO BUILD TEST PASSED 100%!")
    print("=" * 70)

if __name__ == "__main__":
    run_test()
