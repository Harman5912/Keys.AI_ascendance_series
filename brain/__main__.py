"""
CLI demo for the Smart Brain — lets you drive KeysBrain without the UI.

    python -m brain "open chrome"
    python -m brain --list-tools
    python -m brain --plan "create a python file and run it"
    python -m brain --no-tools "what is the weather in Istanbul"   # chat only
    python -m brain --no-brain "hello"                             # disabled

WARNING: without --no-tools this actually executes the tools (opens apps,
searches the web, ...) exactly like Keys.ai would.
"""

from __future__ import annotations

import argparse
import sys


def _console_ui():
    """Minimal stand-in for the PyQt UI."""

    class UI:
        def write_log(self, text):
            print(text)

        def set_state(self, state):
            print(f"[state] {state}")

        def show_content(self, title, text):
            print(f"\n===== {title} =====\n{text[:1500]}\n================")

        def stop_camera_stream(self):
            pass

    return UI()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="brain", description="KEYS.AI SMART BRAIN V2 — CLI demo")
    parser.add_argument("text", nargs="*", help="the request to process")
    parser.add_argument("--list-tools", action="store_true",
                        help="list registered tools and exit")
    parser.add_argument("--plan", action="store_true",
                        help="show the plan, do NOT execute it")
    parser.add_argument("--no-brain", action="store_true",
                        help="disable the brain (fallback path)")
    args = parser.parse_args(argv)

    from brain.brain import KeysBrain

    ui = _console_ui()

    if args.list_tools:
        brain = KeysBrain(ui=ui)
        print("\n".join(brain.tools.names()))
        return 0

    if not args.text:
        parser.print_help()
        return 0

    request = " ".join(args.text)

    # --plan: only generate the plan
    if args.plan:
        brain = KeysBrain(ui=ui)
        intent = brain.intent.classify(request)
        resolved = brain.context.resolve_references(request)
        snapshot = brain.context.snapshot(brain.memory.format_for_prompt())
        plan = brain.planner.create_plan(request, intent, resolved, snapshot)
        if plan is None:
            print("[plan] chat / no tools needed")
            return 0
        print(f"[plan] {plan.get('summary')}")
        for i, s in enumerate(plan["steps"], 1):
            print(f"  {i}. {s['description']}\n     tool={s['tool']} "
                  f"args={s['arguments']}")
        return 0

    brain = KeysBrain(ui=ui, enabled=not args.no_brain)

    def speak(text):
        print(f"\n🗣  {text}\n")

    print(f">>> {request}")
    resp = brain.process(request, ui=ui, speak=speak)
    if resp.used_brain:
        if resp.text:
            speak(resp.text)
    else:
        print("(brain disabled or fell back — normal conversational path)")
    print(f"[brain] status={resp.status} intent={resp.intent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
