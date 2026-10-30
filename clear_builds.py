"""Clear builds/sql_dashboard and builds/sql_core with admin escalation."""
import ctypes
import shutil
import os
import sys
from pathlib import Path

# ── Try normal deletion first ──────────────────────────────────────────────
for d in ['builds/sql_dashboard', 'builds/sql_core']:
    p = Path(d)
    print(f"=== {d} ===")
    print("exists:", p.exists())
    print("is_dir:", p.is_dir() if p.exists() else None)

# Normal rmtree
print("\n--- normal shutil.rmtree ---")
for d in ['builds/sql_dashboard', 'builds/sql_core']:
    try:
        shutil.rmtree(d)
        print(f"removed {d}")
    except Exception as e:
        print(f"FAILED to remove {d}: {e}")

print("\n--- remaining in builds/ ---")
print(os.listdir('builds'))


# ── Escalate: restart self as admin and retry ─────────────────────────────
if os.listdir('builds') and {'sql_dashboard', 'sql_core'} & set(os.listdir('builds')):
    print("\n=== directories still present; checking admin status ===")
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
        print("IsUserAnAdmin:", is_admin)
    except Exception as e:
        print("IsUserAnAdmin check failed:", e)
        is_admin = False

    if not is_admin:
        print("Restarting this script elevated via ShellExecute...")
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, __file__, None, 1
        )
        sys.exit(0)

    # If we are here, we are admin (or IsUserAnAdmin wasn't available)
    print("\n=== retrying deletion as admin ===")
    for d in ['builds/sql_dashboard', 'builds/sql_core']:
        try:
            shutil.rmtree(d)
            print(f"removed {d}")
        except Exception as e:
            print(f"FAILED to remove {d}: {e}")

    print("\n--- final builds/ contents ---")
    print(os.listdir('builds'))
