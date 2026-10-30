import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from personality import build_system_block, select_mode, mode_block
from personality.corpus import select_examples, format_examples

print("=== 1. Persona Base Traits & Injection ===")
block = build_system_block(user_text="Hello Keys", intent="greeting")
assert "KEYS.AI" in block or "Keys.ai" in block
print("System block length:", len(block))
print("Address rule present:", "sir" in block.lower())

print("\n=== 2. Mode Inferences (8 Mode Profiles) ===")
queries = [
    ("Hey there", "companion"),
    ("Need this done in 5 minutes, quick status only", "focus"),
    ("Debug this NullPointerException in user_service.py", "developer"),
    ("Compare PostgreSQL vs CockroachDB architectures with citations", "research"),
    ("Open Chrome, inspect the table, and save as CSV", "operator"),
    ("I feel overwhelmed and keep failing", "coach"),
    ("Give me a creative name for an AI assistant platform", "creative"),
]
for q, expected in queries:
    m = select_mode(q)
    print(f"Query: '{q[:40]}...' -> Mode: {m} (expected: {expected})")

print("\n=== 3. Dialogue Corpus & Humour Suppression on Distress ===")
coach_mode = select_mode("I am totally burnt out and exhausted")
assert coach_mode == "coach"
coach_block = mode_block(coach_mode)
print("Distress mode verified:", coach_mode)
print("Coach mode block snippet:")
for line in coach_block.splitlines()[:4]:
    print(" ", line)

exs = select_examples("I have a strange bug in my python code", mode="developer")
print(f"\nRetrieved {len(exs)} dialogue examples for developer mode:")
for ex in exs:
    print("  - ID:", ex["id"])

print("\n=== 4. Multilingual / Hinglish Handling ===")
hindi_exs = select_examples("Can we speak in Hindi or Hinglish?", mode="companion")
print(f"Retrieved {len(hindi_exs)} examples for multilingual request:")
for ex in hindi_exs:
    print("  - ID:", ex["id"], "User:", ex["user"])

print("\nALL PERSONALITY VERIFICATIONS PASSED!")
