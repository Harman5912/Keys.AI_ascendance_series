"""
Replace emoji prints with ASCII-safe prints in actions/crown_code.py
"""
from pathlib import Path

path = Path(r"c:\Users\harma\Desktop\PROJECTS\Keys-acendence-series\acendence-VIII_GEN-I\actions\crown_code.py")
text = path.read_text(encoding="utf-8")

old_str = 'print("[Crown] 💾 Saved Harman Sadhwani profile and projects to Keys.ai long-term memory")'
new_str = 'print("[Crown] Saved Harman Sadhwani profile and projects to Keys.ai long-term memory")'

if old_str in text:
    text = text.replace(old_str, new_str, 1)
    path.write_text(text, encoding="utf-8")
    print("PATCHED SAFE PRINT IN CROWN_CODE.PY")
else:
    print("old_str not found")
