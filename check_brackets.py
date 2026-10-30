import sys

with open('main.py', 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()

# Find TOOL_DECLARATIONS = [
start_line = None
for i, line in enumerate(lines):
    if 'TOOL_DECLARATIONS = [' in line:
        start_line = i
        break

if start_line is None:
    print("TOOL_DECLARATIONS not found")
    sys.exit(1)

print(f"TOOL_DECLARATIONS starts at line {start_line + 1}")

# Track bracket depth from start_line
depth = 0
in_single_str = False
in_double_str = False
escape_next = False

for i in range(start_line, len(lines)):
    line = lines[i]
    for j, ch in enumerate(line):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and (in_single_str or in_double_str):
            escape_next = True
            continue
        if in_single_str:
            if ch == "'":
                in_single_str = False
            continue
        if in_double_str:
            if ch == '"':
                in_double_str = False
            continue
        if ch == "'":
            in_single_str = True
        elif ch == '"':
            in_double_str = True
        elif ch == '#':
            break
        elif ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
            if depth < 0:
                print(f"NEGATIVE DEPTH at line {i+1}: {line.rstrip()[:120]}")
                sys.exit(1)
    if depth == 0 and i > start_line:
        print(f"List closes at line {i+1}: {line.rstrip()[:120]}")
        break
else:
    print(f"End of file, depth = {depth}")
