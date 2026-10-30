"""
Direct test of _run_autonomous_portfolio for Harman Sadhwani
"""
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from actions.crown_code import _run_autonomous_portfolio
from core.crown_jobs import BuildJob

class MockPlayer:
    def creation_event(self, icon, label, url=""):
        print(f"[Creation Event] {icon} {label}")
    def creation_progress(self, pct, phase="", detail=""):
        print(f"[Progress] {pct*100:.0f}% - {phase}: {detail}")
    def terminal_output(self, text, stream="stdout", source="agent"):
        # print safe ASCII
        clean = text.encode("ascii", errors="replace").decode("ascii")
        print(f"[Terminal] {clean[:120]}")
    def speak(self, text):
        print(f"[Voice] {text}")
    def creation_file_add(self, *a, **k):
        pass
    def creation_preview(self, url):
        print(f"[Preview] {url}")

def test_direct():
    print("=== Testing Direct Autonomous Portfolio Creation ===")
    workspace = root / "workspace" / "harman_sadhwani_portfolio"
    workspace.mkdir(parents=True, exist_ok=True)

    job = BuildJob(kind="site", brief="Build portfolio for Harman Sadhwani", workspace=str(workspace))
    player = MockPlayer()

    task = "Build a comprehensive personal portfolio website for Harman Sadhwani, creator of Keys.ai, showcasing Keys.ai, ReviewBot, Drop of Hope, and BharatHealth"
    reqs = "Sleek dark glassmorphism design with Tailwind, interactive project cards, skills matrix, and contact form"

    res = _run_autonomous_portfolio(
        job=job,
        workspace=workspace,
        task=task,
        requirements=reqs,
        stacks=["html5", "tailwind", "javascript"],
        player=player,
        model="qwen3:8b",
        provider="ollama",
        policy="safe",
        timeout=180,
    )

    print("\nResult:", res)
    index_file = workspace / "index.html"
    print("\nIndex file exists:", index_file.exists())
    if index_file.exists():
        content = index_file.read_text(encoding="utf-8")
        print(f"Index file size: {len(content)} bytes")
        print("Contains 'Harman':", "Harman" in content)
        print("Contains 'Keys.ai':", "Keys.ai" in content)

if __name__ == "__main__":
    test_direct()
