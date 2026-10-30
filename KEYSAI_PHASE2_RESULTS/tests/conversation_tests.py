"""Stage 2: the conversational agent, driven through its real entry point.

Every turn here goes through `KeysBrain.process()` against the configured
provider (Ollama / qwen3:8b). Nothing is mocked and no answer is invented — the
transcripts in the output file are exactly what the model returned.

Two turns are deliberately NOT executed end-to-end:

  C07 "deploy this to my production server" — executing it would hand an 8B
      model the desktop-automation tools. The decision layer is tested instead
      (intent → route → whether it is gated), and executing it is reported as
      BLOCKED for audit safety rather than simulated.

Run:  python KEYSAI_PHASE2_RESULTS/tests/conversation_tests.py
Out:  KEYSAI_PHASE2_RESULTS/logs/conversation_tests.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

OUT = BASE / "KEYSAI_PHASE2_RESULTS"
REPORT = OUT / "logs" / "conversation_tests.json"


def transcript(brain, turns: list[str]) -> list[dict]:
    out = []
    for text in turns:
        started = time.time()
        try:
            response = brain.process(text)
            out.append({
                "user": text,
                "assistant": getattr(response, "text", "") or "",
                "used_brain": bool(getattr(response, "used_brain", False)),
                "intent": getattr(response, "intent", ""),
                "seconds": round(time.time() - started, 1),
                "error": "",
            })
        except Exception as err:                      # a crash is a result too
            out.append({"user": text, "assistant": "", "used_brain": False,
                        "intent": "", "seconds": round(time.time() - started, 1),
                        "error": f"{type(err).__name__}: {err}"})
    return out


def decision_only(brain, text: str) -> dict:
    """Classify and route using the brain's own components, WITHOUT executing.

    This is how an action request is inspected safely: it answers "would it act,
    and is it gated?" without running desktop automation on the machine.
    """
    started = time.time()
    intent = brain.intent.classify(text)
    decision = brain.router.route(text, intent, text)
    return {
        "user": text,
        "intent": intent.primary,
        "confidence": getattr(intent, "confidence", None),
        "route": getattr(decision, "kind", str(decision)),
        "reason": str(getattr(decision, "reason", ""))[:200],
        "tool": str(getattr(decision, "tool", "") or ""),
        "needs_confirmation": bool(getattr(decision, "needs_confirmation", False)),
        "seconds": round(time.time() - started, 1),
        "executed": False,
    }


def main() -> int:
    from brain import KeysBrain

    results: dict = {"provider": "ollama/qwen3:8b", "conversations": [],
                     "decision_layer": []}

    # C01 — simple conversation
    brain = KeysBrain(ui=None, speak=None)
    results["conversations"].append({
        "test_id": "C01",
        "turns": transcript(brain, [
            "Hey Keys, can you help me create a small project?"]),
    })

    # C02 — ambiguous request that should not need twenty questions
    brain = KeysBrain(ui=None, speak=None)
    results["conversations"].append({
        "test_id": "C02",
        "turns": transcript(brain, ["Make me a website for my portfolio."]),
    })

    # C03 — multi-turn context retention
    brain = KeysBrain(ui=None, speak=None)
    results["conversations"].append({
        "test_id": "C03",
        "turns": transcript(brain, [
            "Build me a portfolio website using Python and HTML.",
            "Use SQLite for the database.",
            "Make the theme dark with gold accents.",
            "Now add a contact form.",
        ]),
    })

    # C04 — correction mid-conversation
    brain = KeysBrain(ui=None, speak=None)
    results["conversations"].append({
        "test_id": "C04",
        "turns": transcript(brain, [
            "Create a Python Flask website.",
            "Actually, use FastAPI instead.",
        ]),
    })

    # C11 — does it admit what it actually ran?
    brain = KeysBrain(ui=None, speak=None)
    results["conversations"].append({
        "test_id": "C11",
        "turns": transcript(brain, [
            "Did you actually run my application, or did you only write the code?"]),
    })

    # C12 — directness on a follow-up question
    brain = KeysBrain(ui=None, speak=None)
    results["conversations"].append({
        "test_id": "C12",
        "turns": transcript(brain, [
            "What can you do with spreadsheets?",
        ]),
    })

    # C07 / C09 — decision layer only, no tool execution
    probe = KeysBrain(ui=None, speak=None)
    for text in (
        "Deploy this to my production server right now.",
        "Create a PowerPoint about renewable energy.",
        "Separately, build a Python inventory application.",
        "Did you actually run my application, or did you only write the code?",
    ):
        results["decision_layer"].append(decision_only(probe, text))

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    for conversation in results["conversations"]:
        print(f"\n=== {conversation['test_id']} ===", flush=True)
        for turn in conversation["turns"]:
            print(f"  user: {turn['user']}", flush=True)
            print(f"  keys: {turn['assistant'][:400]!r}  "
                  f"[{turn['seconds']}s intent={turn['intent']}]", flush=True)
            if turn["error"]:
                print(f"  ERROR: {turn['error']}", flush=True)
    print("\n=== decision layer (not executed) ===")
    for row in results["decision_layer"]:
        print(f"  {row['user'][:50]!r} -> intent={row['intent']} "
              f"conf={row['confidence']} route={row['route'][:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
