"""Find what holds builds/sql_dashboard and builds/sql_core open on Windows."""
import subprocess

possible_paths = [
    'handle.exe',
    r'C:\Windows\System32\handle.exe',
    r'C:\Program Files (x86)\Sysinternals\handle.exe',
    r'C:\Program Files\Sysinternals\handle.exe',
]

handle_exe = None
for p in possible_paths:
    try:
        result = subprocess.run([p, '/?'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 or 'usage' in (result.stdout or '').lower() or 'usage' in (result.stderr or '').lower():
            handle_exe = p
            print(f"found handle.exe at: {p}")
            break
    except FileNotFoundError:
        continue
    except Exception as e:
        print(f"checking {p}: {e}")
        continue

if handle_exe:
    print(f"\n=== running handle.exe on builds/sql_dashboard and builds/sql_core ===")
    result = subprocess.run([handle_exe, 'builds/sql_dashboard', 'builds/sql_core'], capture_output=True, text=True, timeout=30)
    print("stdout:")
    print(result.stdout)
    print("\nstderr:")
    print(result.stderr)
    print(f"\nreturncode: {result.returncode}")
else:
    print("handle.exe not found in any location")
