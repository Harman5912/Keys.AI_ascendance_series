from pathlib import Path

p = Path("actions/crown_code.py")
text = p.read_text(encoding="utf-8")
target = "    if analysis[\"questions\"] and (confirmed or p.get(\"auto_defaults\")):\n"
replacement = (
    "    assumptions = []\n"
    "    if analysis[\"questions\"] and confirmed:\n"
    "        assumptions = [q[\"slot\"].replace(\"_\", \" \") for q in analysis.get(\"questions\", [])]\n"
    "    if analysis[\"questions\"] and (confirmed or p.get(\"auto_defaults\")):\n"
)
if target in text and "if analysis[\"questions\"] and confirmed:\n        assumptions" not in text:
    text = text.replace(target, replacement, 1)
    p.write_text(text, encoding="utf-8")
    print("Successfully patched crown_code.py assumptions")
else:
    print("Target already patched or not found")
