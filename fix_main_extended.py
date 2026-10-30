import pathlib, sys, re, subprocess, shutil
from pathlib import Path

path = Path("main.py")
backup = Path("main.py.bak")
if not backup.exists():
    shutil.copyfile(path, backup)

matches_fixed = 0
max_iterations = 500
for iteration in range(max_iterations):
    raw = path.read_bytes().decode("utf-8")
    norm = raw.replace("\r\n", "\n")
    crlf_count = raw.count("\r\n")
    lf_count = norm.count("\n") - crlf_count
    use_crlf = crlf_count >= lf_count
    sep = "\r\n" if use_crlf else "\n"

    # Match the broken pattern: blank line(s) followed by 16-space indented "result = (" then CRLF and 20-space f-string
    results = list(re.finditer(r'\r?\n                result = \([\\r\\n]+                    f"\[VISION_ACTIVE\]', norm))
    # Also match the variation where the f-string is one space more indented than expected
    results_extra = list(re.finditer(r'\r?\n                result = \([\\r\\n]+                     f"\[VISION_ACTIVE\]', norm))
    results += results_extra

    if not results:
        print(f"iteration {iteration}: no more broken blocks found", file=sys.stderr)
        break

    m = results[0]
    idx = m.start()
    start_norm = norm.rfind("\n", 0, idx)
    line_start_norm = start_norm + 1
    end_marker_norm = "elif name == \"system_status\":"
    end_norm_idx = norm.find(end_marker_norm, idx)
    if end_norm_idx < 0:
        print(f"iteration {iteration}: END ANCHOR NOT FOUND for idx {idx}", file=sys.stderr)
        break

    before_norm = norm[:line_start_norm - 1]
    after_norm = norm[end_norm_idx:]

    rebuilt_norm = (
        "                result = (\n"
        '                    f"[VISION_ACTIVE] {_stall.capitalize()} captured. "\n'
        '                    f"Immediately say ONE natural sentence in English "\n'
        "                    f'(e.g. \'Looking at your {_stall} now, sir\'). '\n"
        '                    f"Do NOT describe or guess content - the actual image arrives in the NEXT message."\n'
        "                )\n"
        "\n"
        "            elif name == \"close_camera\":\n"
        "                self.ui.stop_camera_stream()\n"
        "                result = \"Camera closed.\"\n"
        "\n"
        "            elif name == \"web_search\":\n"
    )

    new_norm = before_norm + "\n" + rebuilt_norm + after_norm
    new = new_norm.replace("\n", sep)
    path.write_text(new, encoding="utf-8")
    matches_fixed += 1
    print(f"iteration {iteration}: fixed block at {idx} -> {line_start_norm}:{end_norm_idx}", file=sys.stderr)

# Compile check
proc = subprocess.run([sys.executable, "-m", "py_compile", str(path)], capture_output=True, text=True)
compile_ok = proc.returncode == 0
print("COMPILE_OK" if compile_ok else "COMPILE_FAIL", file=sys.stderr)
if not compile_ok:
    print(proc.stderr[:500], file=sys.stderr)

if compile_ok:
    imp = subprocess.run([sys.executable, "-c", "from actions.send_message import send_message; print('IMPORT_OK')"],
                         capture_output=True, text=True)
    print("IMPORT_OK" if imp.returncode == 0 else "IMPORT_FAIL", file=sys.stderr)
    if imp.returncode != 0:
        print(imp.stderr[:500], file=sys.stderr)

    pytest = subprocess.run([sys.executable, "-m", "pytest", "-q", "qa_artifacts/regression_tests/test_demo_and_messaging.py", "-q"],
                            capture_output=True, text=True, timeout=120)
    print("PYTEST_EXIT", pytest.returncode, file=sys.stderr)
    print(pytest.stdout[-1000:], file=sys.stderr)
    print(pytest.stderr[-1000:], file=sys.stderr)
else:
    print("SKIPPING IMPORT/PYTEST DUE TO COMPILE FAILURE", file=sys.stderr)

print("MATCHES_FIXED", matches_fixed, file=sys.stderr)
