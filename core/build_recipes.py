"""
core/build_recipes.py — how this machine builds each kind of artifact.

Why this exists
---------------
Routing a "dashboard" to the coding agent is only half the fix: an 8B local
model asked for "a dashboard" will happily invent a single HTML page with a
fake array of numbers in a <script> tag. That is the same failure in a new
costume — no data source, no API, nothing that runs.

A recipe is the concrete answer to "what does a real one of these look like on
this computer": the files that must exist, the order to write them, the command
that proves it runs, and the environment facts the model cannot guess (this
machine has MySQL, no Android SDK guarantee, Node 26, PyQt6 installed).

The block is appended to the build brief, so the agent builds a structure that
can be verified — not a page that looks like one.
"""

from __future__ import annotations

import re

# ── Recipes ───────────────────────────────────────────────────────────────
#
# Each recipe is deliberately concrete: file names, the run command, and the
# check that decides whether the build passed. A model that follows it ends
# with something the user can actually start.

RECIPES: dict[str, dict] = {
    "dashboard": {
        "label": "Data dashboard (real API + database)",
        "detect": r"\b(dashboard|dash\s?board|analytics|kpis?|data tool|reporting tool)\b",
        "files": ("app.py", "db.py", "schema.sql", "seed.py", "templates/index.html",
                  "static/dashboard.js", "static/style.css", "requirements.txt", ".env.example"),
        "steps": (
            "The database is the source of truth: schema.sql creates the tables, "
            "seed.py inserts clearly-labelled SAMPLE rows.",
            "db.py opens the connection from DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME "
            "in .env (never hardcode credentials); if MySQL is unreachable, fail with one "
            "clear message that says how to start it — do not silently switch to fake data.",
            "app.py exposes real JSON endpoints (e.g. /api/kpis, /api/series?range=30d) that "
            "query the database. The front end fetches those endpoints; no hardcoded arrays "
            "of numbers in the JavaScript.",
            "The page is an application shell: KPI row, at least two different chart types, "
            "a filter/range control, a table of the underlying rows, loading and error states.",
            "Every chart has a title, axis labels and units. Empty database renders an empty "
            "state, not a broken chart.",
        ),
        "verify": (
            "python -m py_compile app.py db.py seed.py",
            "python seed.py (reports the row counts it inserted)",
            "start the server and GET /api/kpis — it must return JSON from the database",
        ),
    },
    "game": {
        "label": "Playable game (pygame)",
        "detect": r"\b(games?|pygame|arcade game|shooter|platformer|"
                  r"space invaders|breakout|snake game|pong|bullet hell|"
                  r"tower defence|tower defense)\b",
        "files": ("main.py", "game/__init__.py", "game/state.py",
                  "game/scene.py", "game/theme.py", "requirements.txt",
                  "README.md"),
        "steps": (
            "This is a GAME, not a web page: pygame is installed on this machine "
            "(2.6.1). A canvas in an HTML file is not a game.",
            "Keep the rules in plain Python (game/state.py) with no pygame import, "
            "so they can be tested headless; the pygame scene only renders and "
            "reads input.",
            "The loop needs a fixed clock, a way to lose, a restart, and a pause. "
            "A game you cannot lose is a screensaver.",
            "Give it a --selftest flag that runs the rules and builds the scene "
            "under SDL_VIDEODRIVER=dummy, then prints OK.",
            "Colours come from the design tokens (game/theme.py), never from "
            "ad-hoc RGB triples.",
        ),
        "verify": (
            "python -m py_compile main.py game/*.py",
            "SDL_VIDEODRIVER=dummy python main.py --selftest (must print OK)",
        ),
    },
    "python-desktop": {
        "label": "Python desktop application (PyQt6)",
        "detect": r"\b(pyqt5?|pyqt6|qt app|tkinter|customtkinter|python desktop|"
                  r"desktop app in python)\b",
        "files": ("main.py", "app/__init__.py", "app/window.py", "app/db.py",
                  "app/theme.py", "requirements.txt", "README.md"),
        "steps": (
            "PyQt6 is installed on this machine — build a QMainWindow app, not a script "
            "that prints to a terminal.",
            "main.py stays a thin entry point (QApplication + window); logic lives in the app "
            "package so it can be imported and tested without a display.",
            "Give it a --selftest flag that constructs the window offscreen "
            "(QT_QPA_PLATFORM=offscreen) and prints OK, so the build can be verified without "
            "a human clicking anything.",
            "If the user asked for a database, use app/db.py for the desktop app's internal "
            "storage (SQLite by default). Do NOT skip the desktop app to only build database "
            "files — both parts are required when the request mentions both.",
        ),
        "verify": (
            "python -m py_compile main.py app/*.py",
            "set QT_QPA_PLATFORM=offscreen and run `python main.py --selftest`",
        ),
        # When combined with mysql recipe, also require these SQL files
        "combined_files": (
            "schema.sql",
            "seed.sql",
            "queries.sql",
            ".env.example",
        ),
    },
    "electron": {
        "label": "Electron desktop application",
        "detect": r"\belectron\b",
        "files": ("package.json", "main.js", "preload.js", "renderer/index.html",
                  "renderer/app.js", "renderer/style.css"),
        "steps": (
            "Node 26 is installed. package.json declares electron as a devDependency and a "
            "start script; main.js owns the BrowserWindow and all privileged work.",
            "preload.js exposes a narrow contextBridge API — contextIsolation stays on and "
            "nodeIntegration stays off.",
            "IPC handlers are named for what they do (db:list, db:save) and return errors as "
            "data, not thrown strings.",
        ),
        "verify": (
            "node --check main.js && node --check preload.js",
            "npm install (must complete), then npm start",
        ),
    },
    "android": {
        "label": "Android application (Kotlin + Gradle)",
        "detect": r"\b(android|kotlin|android studio|apk|jetpack|gradle)\b",
        "files": ("settings.gradle.kts", "build.gradle.kts", "gradle.properties",
                  "app/build.gradle.kts", "app/src/main/AndroidManifest.xml",
                  "app/src/main/java/.../MainActivity.kt",
                  "app/src/main/res/layout/activity_main.xml",
                  "app/src/main/res/values/strings.xml"),
        "steps": (
            "Write a Gradle Kotlin project that Android Studio can open directly — no "
            "IDE-only steps, no placeholder package names without the app id matching.",
            "Keep it to one Activity plus a layout unless the request needs more; use "
            "ViewBinding and a plain SQLiteOpenHelper or Room (state which and why).",
            "Android Studio is not guaranteed on PATH: if no SDK/gradlew is found, say so in "
            "README.md and do not claim the app was built.",
        ),
        "verify": (
            "gradlew assembleDebug when an SDK exists (report the real output)",
            "otherwise: every file present + README stating the exact first-run steps",
        ),
    },
    "mysql": {
        "label": "MySQL database work",
        "detect": r"\b(mysql|mariadb|sql|schema|database|tables?|queries|sqlite3?)\b",
        "files": ("schema.sql", "seed.sql", "queries.sql", "db.py", ".env.example"),
        "steps": (
            "MySQL is installed on this machine. Use it for SQL; do not quietly swap in "
            "SQLite unless the user asks for it.",
            "schema.sql is idempotent (CREATE TABLE IF NOT EXISTS, sensible PKs, FKs, "
            "indexes) and creates its own database with CREATE DATABASE IF NOT EXISTS.",
            "seed.sql inserts rows that are labelled as sample data and re-runnable.",
            "Credentials come from .env (DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME). "
            "Never write a password into a committed file; if .env is missing, ask the user "
            "for the MySQL password once instead of guessing.",
        ),
        "verify": (
            "python -m py_compile db.py",
            "run schema.sql + seed.sql and SELECT COUNT(*) per table",
            "queries.sql: every query in it must run without error",
        ),
    },
    "ecommerce": {
        "label": "Selling / e-commerce store (catalog, cart, checkout)",
        "detect": r"\b(ecommerce|e-?commerce|shopping cart|checkout|marketplace|"
                  r"online store|product catalog|catalogue|storefront)\b",
        "files": ("app.py", "db.py", "schema.sql", "seed.py", "templates/base.html",
                  "templates/catalog.html", "templates/cart.html",
                  "templates/checkout.html", "static/store.js", "static/style.css",
                  "requirements.txt", ".env.example"),
        "steps": (
            "The catalog is real: products, prices and stock come from the database and "
            "are rendered by the server. Never a hardcoded array of fake products.",
            "Cart and checkout write an order row; stock is decremented in the same "
            "transaction so an order cannot oversell.",
            "Payment: integrate a provider ONLY if the requirements give you credentials. "
            "Otherwise collect no card details at all — the checkout ends at an order "
            "confirmation that says payment is pending, and says plainly that no card "
            "data was collected. Never fabricate a successful charge.",
            "Validate on the server: quantity must be a positive integer, product must "
            "exist, stock must be available. Return a 4xx with a message, not a 200 with "
            "an error inside it.",
            "Pages needed: catalog with search/sort, product detail, cart, checkout, order "
            "confirmation, and an empty-cart state. Loading and error states everywhere.",
        ),
        "verify": (
            "python -m py_compile app.py db.py seed.py",
            "python seed.py (prints per-table row counts)",
            "start the server, add a product to the cart, check out, then SELECT the order "
            "row and confirm stock decreased",
        ),
    },
    "api-backend": {
        "label": "API backend",
        "detect": r"\b(api|rest|graphql|endpoint|backend|back[- ]end|fastapi|flask|express)\b",
        "files": ("app.py (or server.js)", "routes/", "models/", "tests/", "requirements.txt"),
        "steps": (
            "One module per resource, request validation at the edge, JSON errors with "
            "status codes — no 200 responses carrying an error string.",
            "Persist through the database layer, not module-level dicts, when the request "
            "mentions storing anything.",
        ),
        "verify": (
            "import the app and hit each route (Flask test client or an HTTP call)",
            "run the tests directory",
        ),
    },
}


def detect_stacks(description: str) -> list[str]:
    """Recipe keys that apply to a request, most specific first."""
    text = description or ""
    found = [key for key, recipe in RECIPES.items()
             if re.search(recipe["detect"], text, re.I)]
    # A dashboard is also an API backend and a MySQL job; keep the order by
    # recipe importance rather than match order, and drop the generic ones when
    # a specific one already covers the same ground.
    order = ("dashboard", "game", "ecommerce", "python-desktop", "electron",
             "android", "mysql", "api-backend")
    found.sort(key=lambda k: order.index(k))
    if "dashboard" in found and "api-backend" in found:
        found.remove("api-backend")     # the dashboard recipe already covers its API
    # A store defaults to a SQLite file (nothing to install, nothing to log in
    # to). Keep the MySQL recipe only when MySQL/MariaDB/Postgres is actually
    # named — otherwise the two recipes contradict each other on storage.
    if "ecommerce" in found and "mysql" in found and not re.search(
            r"\b(mysql|mariadb|postgres(?:ql)?)\b", text, re.I):
        found.remove("mysql")
    # When a Python desktop app is requested WITH a database, keep both recipes
    # so the agent builds the app AND standalone SQL files. The python-desktop
    # recipe builds the PyQt6 app with internal SQLite, but if the user also
    # asked for SQL files (schema.sql, seed.sql, queries.sql), the mysql recipe
    # adds those standalone artifacts.
    if "python-desktop" in found and "mysql" in found:
        # Both requested — keep both so the agent produces: the desktop app
        # (main.py, app/window.py, app/db.py) AND the SQL files (schema.sql,
        # seed.sql, queries.sql, .env.example). The brief must make it clear
        # these are complementary, not conflicting.
        pass  # Don't remove either — both are needed
    
    # If user asked for both python-desktop AND mysql/sql, ensure that the
    # request explicitly mentions both a Python app AND a database. Otherwise,
    # if only "sql" or "database" is mentioned without a Python app context,
    # we might be building just a database when the user wanted an app too.
    # The brief_spec.py analyse_brief() function handles this at a higher level
    # by asking clarifying questions, but we also add a detection hint here.
    if "mysql" in found and "python-desktop" not in found:
        # User mentioned database/sql but not a Python app — check if they
        # might have meant a Python app with database
        if re.search(r"\b(python|pyqt|desktop app|app\b.*\b(sql|database))\b", text, re.I):
            # If the text mentions Python AND database but python-desktop wasn't
            # detected (e.g., user didn't say "PyQt" explicitly), add a note
            # that both are likely needed
            pass  # The recipe_block will handle this
    
    return found


def recipe_block(keys: list[str]) -> str:
    """The guidance appended to a build brief. Empty string when nothing matched."""
    if not keys:
        return ""
    parts = ["## BUILD RECIPES (verified on this machine — follow them)"]
    
    # Special handling when both python-desktop and mysql are requested:
    # The user wants BOTH the desktop app AND standalone SQL files.
    if "python-desktop" in keys and "mysql" in keys:
        parts.append("""
### Python Desktop App WITH Standalone SQL Files (COMBINED BUILD)

You are building a Python desktop application (PyQt6) AND standalone SQL database files.
Both are required — do not skip either part.

#### PART 1: Python Desktop Application (PyQt6)
Files that must exist:
- main.py — entry point with QApplication, window launch, and --selftest/--seed flags
- app/__init__.py — package marker
- app/window.py — QMainWindow with UI (table, search, form, totals)
- app/db.py — all SQL operations (schema, list, add, delete, totals, seed)
- app/theme.py — palette and stylesheet
- requirements.txt — PyQt6>=6.6
- README.md — run instructions

#### PART 2: Standalone SQL Database Files
Files that must exist:
- schema.sql — idempotent CREATE TABLE statements with indexes
- seed.sql — sample data, labelled as sample, re-runnable
- queries.sql — example queries that run without error
- .env.example — DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME placeholders

#### VERIFICATION (both parts):
1. python -m py_compile main.py app/*.py
2. set QT_QPA_PLATFORM=offscreen and run `python main.py --selftest` (must print OK)
3. Run schema.sql and seed.sql — verify tables created and rows inserted
4. Run every query in queries.sql — all must execute without error

#### IMPORTANT:
- The desktop app uses SQLite internally (app/db.py with app.db file)
- The standalone SQL files (schema.sql, seed.sql) should use the SAME schema
- If MySQL is explicitly named, use MySQL for the standalone files; otherwise SQLite
- Do NOT skip the desktop app to only build SQL files
- Do NOT skip the SQL files to only build the desktop app
- Report BOTH parts as complete or the build is not done
""")
        # Remove both from keys so they're not added again below
        keys = [k for k in keys if k not in ("python-desktop", "mysql")]
        # Add remaining recipes if any
        for key in keys:
            recipe = RECIPES.get(key)
            if not recipe:
                continue
            parts.append(f"\n### {recipe['label']}")
            parts.append("Files that must exist: " + ", ".join(recipe["files"]))
            parts.append("Steps:")
            parts.extend(f"- {step}" for step in recipe["steps"])
            parts.append("Verify before reporting success:")
            parts.extend(f"- {check}" for check in recipe["verify"])
    else:
        for key in keys:
            recipe = RECIPES.get(key)
            if not recipe:
                continue
            parts.append(f"\n### {recipe['label']}")
            parts.append("Files that must exist: " + ", ".join(recipe["files"]))
            parts.append("Steps:")
            parts.extend(f"- {step}" for step in recipe["steps"])
            parts.append("Verify before reporting success:")
            parts.extend(f"- {check}" for check in recipe["verify"])
    
    parts.append("\nIf a recipe cannot be followed (missing SDK, missing server, no "
                 "credentials), report exactly which step blocked it. Do not substitute "
                 "a different structure and call the build finished.")
    return "\n".join(parts)
