import pathlib, sys, textwrap
from pathlib import Path
script = r'''
import pathlib, sys, textwrap
from pathlib import Path

path = Path("main.py")
orig = path.read_text(encoding="utf-8")
anchor = "result = (\n    f\"[VISION_ACTIVE] {_stall.capitalize()} captured. \""
anchor_idx = orig.find(anchor)
if anchor_idx < 0:
    print("ANCHOR NOT FOUND", file=sys.stderr)
    raise SystemExit(1)

start = orig.rfind("\n", 0, anchor_idx)
line_start = start + 1

end_marker = "elif name == \"system_status\":"
end_idx = orig.find(end_marker, anchor_idx)
if end_idx < 0:
    print("END ANCHOR NOT FOUND", file=sys.stderr)
    raise SystemExit(1)

before = orig[:line_start - 1]
after = orig[end_idx:]

rebuilt = textwrap.dedent(r"""
    result = (
        f"[VISION_ACTIVE] {_stall.capitalize()} captured. "
        f"Immediately say ONE natural sentence in English "
        f"(e.g. 'Looking at your {_stall} now, sir'). "
        f"Do NOT describe or guess content - the actual image arrives in the NEXT message."
    )

            elif name == "close_camera":
                self.ui.stop_camera_stream()
                result = "Camera closed."

            elif name == "web_search":
""").lstrip("\n")

new = before + "\n" + rebuilt + after
path.write_text(new, encoding="utf-8")
print("REWROTE start", line_start, "end", end_idx)
'''
path = Path("tmp_repair_final.py")
path.write_text(script, encoding="utf-8")
print("WROTE SCRIPT")
