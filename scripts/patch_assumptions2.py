from pathlib import Path

p = Path("actions/crown_code.py")
text = p.read_text(encoding="utf-8")
old = """    # Which builder owns this request, decided on what the user actually asked
    # for — before the build guidance is appended. The guidance text mentions
    # MySQL and logins while describing what to avoid, so testing it here would
    # disqualify the very recipes it is describing.
    app_kind = app_kind_for(brief)

    assumptions = []
    if analysis["questions"]:"""

new = """    # Which builder owns this request, decided on what the user actually asked
    # for — before the build guidance is appended. The guidance text mentions
    # MySQL and logins while describing what to avoid, so testing it here would
    # disqualify the very recipes it is describing.
    app_kind = app_kind_for(brief)

    if not assumptions and analysis["questions"]:"""

if old in text:
    text = text.replace(old, new)
    p.write_text(text, encoding="utf-8")
    print("Cleaned up second assumptions overwrite in crown_code.py")
else:
    print("Pattern not found")
