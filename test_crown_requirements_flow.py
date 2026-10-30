"""
Test the new requirements questioning flow in crown_code.py

Verifies that:
1. When a task has unanswered questions, crown_code returns refusal_text
2. When a player with ask_decision is provided, it would trigger interactive questions
3. After answers are collected, the build can proceed

Run: python test_crown_requirements_flow.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


class MockPlayer:
    """Simulates a UI player that can ask questions and record calls."""
    
    def __init__(self):
        self.calls: list[dict] = []
        self.answers: dict[str, str] = {}
        
    def ask_decision(self, question: str, options: list[str], 
                     show_why: bool = False, why_text: str = "") -> str:
        """Simulate user answering a question."""
        self.calls.append({
            "type": "ask_decision",
            "question": question,
            "options": options,
            "show_why": show_why,
            "why_text": why_text,
        })
        # Simulate user picking the first (recommended) option
        if options:
            return options[0]
        return ""
    
    def ask_permission(self, action: str, reason: str = "", location: str = "") -> str:
        """Simulate permission request."""
        self.calls.append({
            "type": "ask_permission",
            "action": action,
            "reason": reason,
            "location": location,
        })
        # Deny by default for requirements_needed
        if action == "requirements_needed":
            return "deny"
        return "allow_once"
    
    def creation_event(self, icon: str, text: str, file=None):
        self.calls.append({"type": "creation_event", "icon": icon, "text": text})
    
    def begin_creation(self, mode: str, name: str, path: str):
        self.calls.append({"type": "begin_creation", "mode": mode, "name": name})
    
    def write_log(self, text: str):
        self.calls.append({"type": "write_log", "text": text})
    
    def creation_error(self, text: str):
        self.calls.append({"type": "creation_error", "text": text})
    
    def creation_complete(self, summary: str = ""):
        self.calls.append({"type": "creation_complete", "summary": summary})
    
    def speak(self, text: str):
        self.calls.append({"type": "speak", "text": text})


def test_refusal_without_player():
    """Test that crown_code returns refusal text when questions are unanswered."""
    from actions.crown_code import crown_code
    
    player = None  # No player - should return refusal text
    result = crown_code({
        "description": "Build a dashboard with charts",
        "action": "build",
    }, player=player)
    
    assert "NEED REQUIREMENTS" in result, f"Expected refusal text, got: {result[:100]}"
    assert "nothing was built" in result.lower(), f"Expected 'nothing was built', got: {result[:100]}"
    print("✓ Test 1 PASS: Returns refusal text when no player and questions unanswered")def test_interactive_questions_with_player():
    """Test that with a player that has ask_decision, interactive questions are asked."""
    from actions.crown_code import crown_code

    player = MockPlayer()
    result = crown_code({
        "description": "Build a dashboard with charts",
        "action": "build",
    }, player=player)

    # Should have called ask_decision for each question
    decision_calls = [c for c in player.calls if c["type"] == "ask_decision"]
    assert len(decision_calls) > 0, "Expected ask_decision to be called"
    print(f"✓ Test 2 PASS: Called ask_decision {len(decision_calls)} times for requirements")

    # Should have started the build after getting answers
    assert "Started" in result, f"Expected build to start after answers, got: {result[:100]}"
    print("✓ Test 2b PASS: Build proceeds after interactive questions answered")


def test_interactive_questions_flow():
    """Test the full interactive question flow."""
    from actions.crown_code import crown_code
    from core.brief_spec import analyse_brief, generate_interactive_questions
    
    # First, analyse the brief to see what questions would be asked
    analysis = analyse_brief("Build a dashboard with charts")
    assert analysis["ready"] is False, "Expected questions to be needed"
    assert len(analysis["questions"]) > 0, "Expected questions to be generated"
    
    # Generate interactive questions
    interactive_qs = generate_interactive_questions(analysis)
    assert len(interactive_qs) == len(analysis["questions"]), \
        f"Expected {len(analysis['questions'])} interactive questions, got {len(interactive_qs)}"
    
    print(f"✓ Test 3a PASS: Generates {len(interactive_qs)} interactive questions")
    
    # Simulate answering all questions
    answers = {}
    for q in interactive_qs:
        slot = q["slot"]
        # In real flow, this would be player.ask_decision()
        answers[slot] = q["options"][0] if q["options"] else "default"
    
    # Build requirements string from answers
    requirements = "\n".join(f"{k.replace('_', ' ')}: {v}" for k, v in answers.items() if v)
    
    # Re-analyse with answers
    new_analysis = analyse_brief("Build a dashboard with charts", "", requirements)
    assert new_analysis["ready"] is True, f"Expected ready after answers, got questions: {new_analysis['questions']}"
    assert len(new_analysis["questions"]) == 0, "Expected no questions after answers"
    
    print("✓ Test 3b PASS: Answers resolve all questions, build can proceed")


def test_portfolio_task_no_questions():
    """Test that a portfolio build task doesn't need requirements."""
    from actions.crown_code import crown_code
    
    player = MockPlayer()
    result = crown_code({
        "description": "Build a portfolio website for Harman Sadhwani",
        "action": "build",
    }, player=player)
    
    # Portfolio builds should proceed without questions
    # (they may go to the autonomous pipeline)
    assert "Started" in result or "building" in result.lower(), \
        f"Expected build to start for portfolio, got: {result[:100]}"
    print("✓ Test 4 PASS: Portfolio builds can proceed without requirement questions")


def test_simple_task_no_questions():
    """Test that a simple task with no requirements doesn't block."""
    from actions.crown_code import crown_code
    
    player = MockPlayer()
    result = crown_code({
        "description": "Create a simple hello world HTML page",
        "action": "build",
    }, player=player)
    
    # Simple page tasks should proceed
    assert "Started" in result or "building" in result.lower() or "page" in result.lower(), \
        f"Expected build to start for simple page, got: {result[:100]}"
    print("✓ Test 5 PASS: Simple page builds can proceed")


if __name__ == "__main__":
    print("=" * 60)
    print("Testing Crown Code Requirements Flow")
    print("=" * 60)
    print()
    
    try:
        test_refusal_without_player()
    except Exception as e:
        print(f"✗ Test 1 FAIL: {e}")
    
    try:
        test_refusal_with_player_deny()
    except Exception as e:
        print(f"✗ Test 2 FAIL: {e}")
    
    try:
        test_interactive_questions_flow()
    except Exception as e:
        print(f"✗ Test 3 FAIL: {e}")
    
    try:
        test_portfolio_task_no_questions()
    except Exception as e:
        print(f"✗ Test 4 FAIL: {e}")
    
    try:
        test_simple_task_no_questions()
    except Exception as e:
        print(f"✗ Test 5 FAIL: {e}")
    
    print()
    print("=" * 60)
    print("All tests completed")
    print("=" * 60)
