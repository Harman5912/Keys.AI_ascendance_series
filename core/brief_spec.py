"""
core/brief_spec.py — read a build request for what it *requires*, and ask.

Why this exists
---------------
"Create a dashboard with proper graphs and API integration for market data"
used to reach the website path, where every brief is forced into the same
eight section kinds (about / projects / gallery / skills / faq / contact) with
a hardcoded portfolio plan as the guaranteed artifact. The result was a
portfolio-shaped page with none of the thing that was asked for: no charts,
no data source, no dashboard.

The cause was not the model. It was this: the request was classified as "a
website", and nothing ever asked what the website had to *do*.

So a build request is now read in two steps before any file is written:

    1. ARTIFACT   application or page? A dashboard, a data tool, anything with
                  a source of numbers and a login is an APPLICATION and is
                  built by the coding agent as real files — never rendered
                  from the page template.
    2. REQUIREMENTS  the facts a build cannot work without (which feed supplies
                  the data, which numbers each chart shows, which chart types,
                  which stack, single user or logged in). Anything the brief
                  does not state is turned into a QUESTION for the user.

No defaults are invented for a missing requirement. A guessed data source or
chart type is how a build ends up looking nothing like the request, and the
cost of one question is far below the cost of one wrong project.

Nothing here talks to a model: it is deterministic, so it can be tested and it
cannot hallucinate the answers it then builds from.
"""

from __future__ import annotations

import re

# ── What kind of artifact is this? ────────────────────────────────────────
#
# Strong markers name behaviour that only an application has: a data dashboard,
# a store of records, sign-in, a live feed. These win even when the brief calls
# the thing "a website" — which is exactly how the original request was lost.

_APP_STRONG = re.compile(
    r"\b(dashboards?|dash\s?board|analytics|kpis?|admin panel|admin dashboard|"
    r"back\s?office|crud|api integration|integrate (?:an?|the|my) api|rest api|"
    r"restful api|graphql|webhook|websocket|realtime|real[- ]time|live data|"
    r"database|databases|sql|postgres(?:ql)?|mysql|sqlite|mongo(?:db)?|supabase|"
    r"firebase|airtable|auth|authentication|login|log[- ]in|sign[- ]?up|"
    r"oauth|session|multi[- ]user|user accounts|etl|data pipeline|ingest(?:ion)?|"
    r"scraper|crawler|tracker|monitoring tool|inventory system|booking system|"
    r"point of sale|pos system|crm|erp|"
    # A program built for a platform is an application even when it has no
    # data source: "Electron desktop app: a focus timer" is not a page.
    r"electron|desktop app|mobile app|android app|ios app|iphone app|"
    r"macos app|windows app|linux app|"
    # A store is an application: it has a cart, stock and orders to keep.
    r"ecommerce|e-?commerce|shopping cart|checkout|marketplace|online store|"
    r"product catalog|storefront)\b",
    re.I,
)

# Weak markers: charts on their own are also used by marketing pages, so they
# only count when the brief is talking about actual numbers.
_APP_WEAK = re.compile(
    r"\b(charts?|graphs?|plots?|visuali[sz]ations?|sparklines?|heatmaps?|"
    r"candlesticks?|histograms?|gauge)\b",
    re.I,
)
_DATA_CONTEXT = re.compile(
    r"\b(data|dataset|api|feed|market|markets|finance|financial|stock|stocks|"
    r"equit(?:y|ies)|crypto|prices?|tickers?|sales|revenue|traffic|stats|"
    r"statistics|metrics|numbers|reports?|spend|budget)\b",
    re.I,
)

# A program that walks a folder and transforms what it finds is an application
# even with no data source and no login. "a tool that converts a folder of PDFs
# to text" used to be classified as a plain task, so it reached the agent with
# no questions about what goes in or where the output should land.
_FILE_TOOL = re.compile(
    r"\b(tool|utility|script|program|app|cli)\b[^.?!]{0,60}?"
    r"\b(convert(?:s|ing)?|rename(?:s|d|ing)?|resiz\w*|extract(?:s|ing)?|"
    r"merg\w*|split(?:s|ting)?|scan(?:s|ning)?|organi[sz]\w+|clean\w*|"
    r"compress\w*|batch(?:es|ing)?)\b",
    re.I,
)
_FILE_BATCH = re.compile(
    r"\b(batch|bulk|folder|directory|files?|pdfs?|images?|photos?|documents?|"
    r"spreadsheets?|workbooks?)\b",
    re.I,
)

# An input is stated only when the brief says where the files come from: "a
# folder of PDFs" says what is converted, not which folder to read.
_FILE_INPUT = re.compile(
    r"\b(?:from|in|inside|under)\s+(?:the\s+|a\s+|my\s+)?"
    r"(?:folder|directory|path|drive)\b"
    r"|\b[a-z]:[\\/]|~/|\binput folder\b|\binbox\b",
    re.I,
)
# Likewise, output is stated by a destination, not by the target format: "to
# text" is what to produce, not where to put it.
_FILE_OUTPUT = re.compile(
    r"\b(output|save[sd]?|write[sd]?|export(?:s|ed)?|store[sd]?)\s+(?:it\s+)?"
    r"(?:to|as|into|in)\b|\boutput folder\b|\b[a-z]:[\\/]",
    re.I,
)

_PAGE_WORDS = re.compile(
    r"\b(website|web site|web page|webpage|landing page|portfolio|microsite|"
    r"one[- ]?pager|homepage|home page|static site|marketing site|showcase|"
    r"brochure site)\b",
    re.I,
)

_GAME_INTENT = re.compile(
    r"\b(game|games|pygame|arcade|shooter|shoot[- ]em[- ]up|platformer|puzzle|rpg|"
    r"snake|pong|tetris|breakout|space invaders|flappy|asteroid|roguelike|racing)\b",
    re.I,
)
_ANDROID_INTENT = re.compile(
    r"\b(android|android app|apk|kotlin|jetpack compose|compose|mobile app|"
    r"flutter|react native|expo)\b",
    re.I,
)
_GAME_GENRES = re.compile(
    r"\b(arcade|2d|shooter|platformer|puzzle|snake|pong|racing|rpg|adventure|maze)\b",
    re.I,
)
_GAME_CONTROLS = re.compile(
    r"\b(keyboard|arrows?|wasd|mouse|click|spacebar|controller|touch)\b",
    re.I,
)
_GAME_VISUALS = re.compile(
    r"\b(pixel|retro|8[- ]bit|neon|vector|minimal|dark|cyberpunk|clean|sprites?)\b",
    re.I,
)
_MOBILE_FRAMEWORKS = re.compile(
    r"\b(kotlin|jetpack compose|compose|flutter|react native|expo|android)\b",
    re.I,
)
_MOBILE_FEATURES = re.compile(
    r"\b(feed|list|dashboard|database|room|sqlite|search|navigation|tabs|auth|profile)\b",
    re.I,
)
_SITE_SECTIONS = re.compile(
    r"\b(hero|features|about|pricing|portfolio|gallery|contact|testimonials|faq|services)\b",
    re.I,
)

# ── Requirement slots ─────────────────────────────────────────────────────

_CHART_TYPES = re.compile(
    r"\b(line|bar|column|area|pie|donut|doughnut|scatter|bubble|candlestick|"
    r"ohlc|heatmap|histogram|radar|sparkline|gauge|treemap|funnel|waterfall|"
    r"stacked|kpi cards?|data table)\b",
    re.I,
)

_STACKS = re.compile(
    r"\b(react|react\.js|next\.?js|vue|nuxt|svelte|angular|tailwind|"
    r"streamlit|gradio|dash|plotly|d3(?:\.js)?|chart\.?js|recharts|echarts|"
    r"highcharts|apexcharts|flask|fastapi|django|express|node(?:\.js)?|"
    r"vanilla (?:js|javascript|html)|plain html|python|typescript|javascript|"
    # Non-web stacks Keys.AI builds for: mobile, desktop and database.
    # Without these, "stack: Kotlin, Gradle, ViewBinding" was reported as an
    # unanswered requirement and the build never started.
    r"kotlin|java|gradle|jetpack compose|androidx|xml|electron|"
    r"pyqt[3-6]?|pyside[26]?|tkinter|customtkinter|qt widgets|"
    r"flutter|dart|swift|react native|expo|sqlite|sql|mysql|postgres(?:ql)?|"
    r"mongo(?:db)?|rust|php|ruby|laravel)\b",
    re.I,
)

_SOURCES = re.compile(
    r"\b(yahoo finance|alpha vantage|binance|coinbase|kraken|polygon\.io|"
    r"polygon|finnhub|iex|twelve data|coingecko|coinmarketcap|coincap|"
    r"exchangerate|open ?weather|weather ?api|google sheets|airtable|supabase|"
    r"firebase|postgres(?:ql)?|mysql|sqlite|mongo(?:db)?|csv|excel|json file|"
    r"local file|sample data|mock data|dummy data|seed data|fake data|"
    r"i (?:already )?have (?:the )?(?:data|api|csv|key|token)|"
    r"no api|without (?:an? )?api|offline data)\b",
    re.I,
)

_METRICS = re.compile(
    r"\b(price|prices|ohlc|open|close|high|low|volume|market cap|returns?|"
    r"volatility|drawdown|revenue|profit|margin|costs?|spend|signups?|sign[- ]ups?|"
    r"users?|sessions?|conversion|churn|traffic|clicks?|impressions?|orders?|"
    r"inventory|stock level|latency|uptime|errors?|temperature|humidity|"
    r"sentiment|funding|holders|liquidity|fees|p\/e|eps)\b",
    re.I,
)

_SCOPE = re.compile(
    r"\b(single[- ]user|single user|for myself|local(?:ly)?|offline|no login|"
    r"without login|no auth|without auth|standalone|no backend|demo|"
    r"login|sign[- ]?in|sign[- ]?up|auth|accounts?|multi[- ]user|team|"
    r"share(?:d)? with|public|admin|role)\b",
    re.I,
)

# Only a brief that talks about charts, dashboards or analytics needs a data
# source, a metric list and chart types. An Android task list or a MySQL
# schema does not: asking it "which chart types?" is how eight real builds
# died as a questionnaire.
_DASH_INTENT = re.compile(
    r"\b(dashboards?|dash\s?board|charts?|graphs?|plots?|visuali[sz]ations?|"
    r"analytics|kpis?|sparklines?|heatmaps?|candlesticks?|histograms?|"
    r"gauges?|reporting (?:tool|view|dashboard)|data (?:tool|dashboard)|"
    r"business intelligence|\bbi\b)\b",
    re.I,
)

_APP_SLOTS = (
    {
        "slot": "data_source",
        "ask": "Which data source should feed the charts?",
        "examples": "a named API (e.g. Yahoo Finance, Alpha Vantage, Binance), "
                    "a file you already have (CSV/JSON/Excel), or sample data",
        "why": "it decides the fetch layer, the fields and whether keys are needed",
        "filled": lambda t: bool(_SOURCES.search(t)),
    },
    {
        "slot": "metrics",
        "ask": "Which numbers should each view show?",
        "examples": "e.g. price + volume, revenue vs. spend, signups by week",
        "why": "a chart with the wrong series is not the same chart",
        "filled": lambda t: bool(_METRICS.search(t)),
    },
    {
        "slot": "charts",
        "ask": "Which chart types should the views use?",
        "examples": "e.g. line for trend, candlestick for OHLC, bar for comparison, KPI cards on top",
        "why": "chart type is a requirement, not a styling choice",
        "filled": lambda t: bool(_CHART_TYPES.search(t)),
    },
    {
        "slot": "stack",
        "ask": "Which stack should it be built in?",
        "examples": "e.g. React + Vite, plain HTML/JS, Streamlit, FastAPI + a static front end",
        "why": "it decides the files, the run command and the dependencies",
        "filled": lambda t: bool(_STACKS.search(t)),
    },
    {
        "slot": "scope",
        "ask": "Is it a single-user tool on this machine, or does it need login / multiple users?",
        "examples": "e.g. local single user with sample data, or local front end plus a small backend with a login",
        "why": "auth, storage and deployment all follow from this",
        "filled": lambda t: bool(_SCOPE.search(t)),
    },
)

# A file-processing tool has no charts, so the answers it actually needs are
# which files it takes, where the results go, and who runs it.
_FILE_TOOL_SLOTS = (
    {
        "slot": "input",
        "ask": "Which files or folder should it read?",
        "examples": "e.g. a specific folder path, or an input folder the user picks at run time",
        "why": "it decides the file discovery, the accepted formats and the error handling",
        "filled": lambda t: bool(_FILE_INPUT.search(t)),
    },
    {
        "slot": "output",
        "ask": "Where should the results go?",
        "examples": "e.g. one file per input next to it, a single combined file, or an output folder",
        "why": "per-file and combined output are different programs, and both overwrite",
        "filled": lambda t: bool(_FILE_OUTPUT.search(t)),
    },
    {
        "slot": "scope",
        "ask": "Is it a single-user tool on this machine, or does it need login / multiple users?",
        "examples": "e.g. a local command-line tool, or a small web page other people upload to",
        "why": "it decides whether there is a UI, a server and any authentication at all",
        "filled": lambda t: bool(_SCOPE.search(t)),
    },
)

# An application that does not draw charts still needs two answers: what it
# is built in, and who uses it. Everything else it needs is in the brief.
_APPS_PLAIN_SLOTS = ("stack", "scope")
_APPS_PLAIN = tuple(s for s in _APP_SLOTS if s["slot"] in _APPS_PLAIN_SLOTS)


_GAME_SLOTS = (
    {
        "slot": "game_genre",
        "ask": "What is the game genre and core gameplay loop?",
        "examples": "e.g. 2D Arcade Classic (Snake, Shooter, Platformer, Puzzle)",
        "why": "it dictates the game mechanics, physics loop and win/loss rules",
        "filled": lambda t: bool(_GAME_GENRES.search(t)),
    },
    {
        "slot": "game_controls",
        "ask": "What control scheme should the player use?",
        "examples": "e.g. Arrow keys / WASD + Spacebar to Action, or Mouse aim & click",
        "why": "event handling and key listeners depend on this",
        "filled": lambda t: bool(_GAME_CONTROLS.search(t)),
    },
    {
        "slot": "game_visuals",
        "ask": "What visual aesthetic and color theme do you want?",
        "examples": "e.g. Retro Neon Arcade, Clean Minimalist Vector, 8-bit Pixel Art",
        "why": "it decides color palettes, sprite drawing, and asset generation",
        "filled": lambda t: bool(_GAME_VISUALS.search(t)),
    },
    {
        "slot": "stack",
        "ask": "Which game engine or library should be used?",
        "examples": "e.g. Python (Pygame), Python Arcade, or HTML5 Canvas",
        "why": "it decides the dependencies and execution command",
        "filled": lambda t: bool(_STACKS.search(t)),
    },
)

_ANDROID_SLOTS = (
    {
        "slot": "mobile_framework",
        "ask": "Which mobile framework should it be built with?",
        "examples": "e.g. Native Android Kotlin (Jetpack Compose), Flutter (Dart), or React Native (Expo)",
        "why": "it determines the project structure, build tools, and package manifests",
        "filled": lambda t: bool(_MOBILE_FRAMEWORKS.search(t)),
    },
    {
        "slot": "app_features",
        "ask": "What are the core screens and capabilities of the app?",
        "examples": "e.g. Interactive Dashboard with List/Detail navigation and local SQLite storage",
        "why": "it sets the navigation graph and data models",
        "filled": lambda t: bool(_MOBILE_FEATURES.search(t)),
    },
    {
        "slot": "theme",
        "ask": "What UI style and color theme should it follow?",
        "examples": "e.g. Material 3 Modern Dark, Clean Minimalist Light",
        "why": "it generates the Theme and Color tokens",
        "filled": lambda t: bool(re.search(r"\b(dark|light|material|minimal)\b", t, re.I)),
    },
)

_SITE_SLOTS = (
    {
        "slot": "subject",
        "ask": "Who or what is the website for?",
        "examples": "a person's name, a business/studio name, or the product being shown",
        "why": "the copy, brand and metadata are all built from it",
        "filled": None,
    },
    {
        "slot": "site_sections",
        "ask": "Which sections or views should the website include?",
        "examples": "e.g. Hero showcase + Features + Portfolio gallery + Contact form",
        "why": "it defines the layout structure and component hierarchy",
        "filled": lambda t: bool(_SITE_SECTIONS.search(t)),
    },
    {
        "slot": "theme",
        "ask": "What visual theme and aesthetic do you prefer?",
        "examples": "e.g. Sleek Modern Dark, Clean Minimalist Light, Creative Neon",
        "why": "it sets the design tokens and typography",
        "filled": lambda t: bool(re.search(r"\b(dark|light|minimal|neon|sleek|creative)\b", t, re.I)),
    },
    {
        "slot": "stack",
        "ask": "Which front-end stack should be used?",
        "examples": "e.g. Single Page HTML + Tailwind CSS, React + Vite, or Next.js",
        "why": "it defines the build tool and asset bundler",
        "filled": lambda t: bool(_STACKS.search(t)),
    },
)
_PAGE_SLOTS = (
    {
        "slot": "subject",
        "ask": "Who or what is the page for?",
        "examples": "a person's name, a business name, or the product being shown",
        "why": "the copy, brand and metadata are all built from it",
        "filled": None,   # handled by _named_subject() below
    },
)

# A name only counts when it is actually a name: quoted, "for <Name>", or two
# capitalised words. "my studio" is not a name — asking for one is the point.
_NAME_QUOTED = re.compile(r"[\"“'‘]([^\"”'’]{2,40})[\"”'’]")
_NAME_FOR = re.compile(r"\bfor\s+((?:[A-Z][\w'’-]+\s*){2,3})")
_NAME_CAPS = re.compile(r"\b([A-Z][a-z]{1,15})\s+([A-Z][a-z]{1,15})\b")
_STOP_NAMES = {"build", "create", "make", "design", "please", "the", "and", "for"}


def _named_subject(text: str) -> bool:
    if _NAME_QUOTED.search(text):
        return True
    m = _NAME_FOR.search(text)
    if m and m.group(1).strip().lower() not in _STOP_NAMES:
        return True
    for a, b in _NAME_CAPS.findall(text):
        if a.lower() not in _STOP_NAMES and b.lower() not in _STOP_NAMES:
            return True
    return False


def is_file_tool(brief: str) -> bool:
    """True when the request is a program that transforms files in bulk."""
    text = brief or ""
    return bool(_FILE_TOOL.search(text) and _FILE_BATCH.search(text))


def is_app_brief(brief: str) -> bool:
    """True when the request describes an application, not an information page."""
    text = brief or ""
    if _APP_STRONG.search(text):
        return True
    if is_file_tool(text):
        return True
    return bool(_APP_WEAK.search(text) and _DATA_CONTEXT.search(text))


def _coerce_requirements(requirements) -> str:
    """Accept dict answers, a list of strings, or free prose."""
    if not requirements:
        return ""
    if isinstance(requirements, dict):
        return "\n".join(f"{k.replace('_', ' ')}: {v}" for k, v in requirements.items() if v)
    if isinstance(requirements, (list, tuple)):
        return "\n".join(str(r) for r in requirements if str(r).strip())
    return str(requirements).strip()


def analyse_brief(brief: str, kind: str = "", requirements=None) -> dict:
    """Inspect a brief (plus any answers already given) and list what is missing.

    Returns:
        {
          "artifact": "app" | "page" | "task",
          "ready": bool,                 # no questions left
          "questions": [{"slot", "ask", "examples", "why"}],
          "answered": [slot, ...],       # requirements the brief already states
        }
    """
    text = (brief or "").strip()
    answers = _coerce_requirements(requirements)
    # Answers count as part of the brief: a requirement stated by the user is
    # not a requirement that needs asking again.
    combined = f"{text}\n{answers}" if answers else text

    if _GAME_INTENT.search(combined):
        artifact = "game"
        slots = _GAME_SLOTS
    elif _ANDROID_INTENT.search(combined):
        artifact = "android"
        slots = _ANDROID_SLOTS
    elif is_app_brief(combined):
        artifact = "app"
        if is_file_tool(combined):
            slots = _FILE_TOOL_SLOTS
        elif _DASH_INTENT.search(combined):
            slots = _APP_SLOTS
        else:
            slots = _APPS_PLAIN
    elif _PAGE_WORDS.search(combined) or str(kind).lower() in (
            "portfolio", "website", "site", "page", "landing"):
        artifact = "page"
        slots = _PAGE_SLOTS
    else:
        artifact = "task"
        slots = ()
    answered: list[str] = []
    questions: list[dict] = []
    for slot in slots:
        checker = slot.get("filled")
        filled = (checker(combined) if checker
                  else (_named_subject(combined) if slot["slot"] == "subject" else False))
        if filled:
            answered.append(slot["slot"])
            continue
        questions.append({key: slot[key] for key in ("slot", "ask", "examples", "why")})

    return {
        "artifact": artifact,
        "ready": not questions,
        "questions": questions,
        "answered": answered,
    }


def merge_brief(brief: str, requirements=None) -> str:
    """The brief the build agent receives: the request plus the confirmed facts.

    The wording is explicit on purpose — a model handed a list of requirements
    still tends to "improve" them by inventing a data source or a framework.
    """
    text = (brief or "").strip()
    answers = _coerce_requirements(requirements)
    if not answers:
        return text
    return (
        f"{text}\n\n"
        "CONFIRMED REQUIREMENTS — supplied by the user, do not change, replace "
        "or extend them:\n"
        f"{answers}\n\n"
        "Build exactly this. Do not invent a data source, metric, chart type, "
        "framework or feature that is not listed above. If something needed to "
        "finish is genuinely missing, stop and report which requirement is "
        "missing instead of choosing one on the user's behalf."
    )


def questions_text(analysis: dict) -> str:
    """The numbered question list, for the assistant to read back to the user."""
    lines = []
    for i, q in enumerate(analysis.get("questions", []), 1):
        lines.append(f"{i}. {q['ask']} ({q['examples']}) — {q['why']}.")
    return "\n".join(lines)


# ── Interactive question generation & recommended smart defaults ─────────

SLOT_OPTIONS: dict[str, list[str]] = {
    "game_genre": [
        "(Recommended) 2D Arcade Classic (Responsive loop with scoring, obstacles, and game over/restart)",
        "Top-down Arena Shooter (Player movement, projectiles, enemy waves)",
        "Puzzle / Logic Grid Game (Turn-based mechanics, smooth animations)",
        "Platformer (Gravity, jumping, obstacles, collectibles)",
    ],
    "game_controls": [
        "(Recommended) Keyboard Arrow Keys / WASD + Spacebar to Action/Shoot",
        "Mouse Movement + Left Click to Interact/Fire",
        "Hybrid Keyboard Movement + Mouse Aiming",
    ],
    "game_visuals": [
        "(Recommended) Retro Neon Arcade (Vibrant glowing vectors, dark background)",
        "Clean Minimalist Geometric (Crisp high-contrast shapes)",
        "Pixel Art Style (8-bit nostalgic color palette)",
    ],
    "mobile_framework": [
        "(Recommended) Android Native Kotlin + Jetpack Compose (Modern Material 3)",
        "Flutter / Dart (Cross-platform native UI)",
        "React Native / Expo (TypeScript/JavaScript mobile)",
    ],
    "app_features": [
        "(Recommended) Interactive Dashboard + List/Detail Views + Local SQLite Persistence",
        "Feed with Search, Filtering, and Bookmark Favorites",
        "Task & Activity Tracker with Notifications & Metrics",
    ],
    "site_sections": [
        "(Recommended) Hero Showcase + Feature Grid + Interactive Demo/Portfolio + Contact Form",
        "Single-page Marketing Landing with Pricing Tables & FAQ",
        "Product Documentation & Feature Tour",
    ],
    "stack": [
        "(Recommended) React + Vite + Tailwind CSS",
        "FastAPI + Modern HTML/JS Front-end",
        "Next.js (React Framework)",
        "Streamlit (Python Data App)",
        "Vanilla HTML + Tailwind CSS + JavaScript",
        "PyQt6 / Desktop GUI",
    ],
    "data_source": [
        "(Recommended) Mock / Seed data generator with local JSON state",
        "Real Public REST API (e.g. CoinGecko, Yahoo Finance, OpenWeather)",
        "Local CSV / SQLite database",
        "Custom REST API endpoint",
    ],
    "charts": [
        "(Recommended) KPI Summary Cards + Trend Line & Bar Charts",
        "Interactive Candlestick & Volume Charts",
        "Full Analytics Suite (Line, Donut, Area & Heatmap)",
    ],
    "metrics": [
        "(Recommended) Key activity KPIs, volume trends, and performance over time",
        "Real-time prices, percentage change, and 24h highs/lows",
        "Revenue, user acquisition, and conversion funnel metrics",
    ],
    "scope": [
        "(Recommended) Local single-user tool with persistent storage",
        "Single-user with local file export/import",
        "Multi-user / Team tool with authentication",
    ],
    "theme": [
        "(Recommended) Sleek Modern Dark Theme (Obsidian & Indigo accents)",
        "Clean Minimalist Light Theme (Apple / Stripe aesthetic)",
        "High-Contrast Cyberpunk / Terminal Theme",
    ],
    "input": [
        "(Recommended) Current workspace directory",
        "User-specified input folder via UI picker",
    ],
    "output": [
        "(Recommended) Dedicated output/ folder inside workspace",
        "Directly alongside input files",
    ],
    "subject": [
        "(Recommended) Default Project Showcase",
        "Personal Portfolio",
        "Business / Agency Brand",
    ],
}


def generate_interactive_questions(analysis: dict) -> list[dict]:
    """Generate structured questions compatible with ask_question / interactive UI."""
    result = []
    for q in analysis.get("questions", []):
        slot = q.get("slot", "")
        options = list(SLOT_OPTIONS.get(slot, ["(Recommended) Standard defaults"]))
        result.append({
            "question": f"{q.get('ask', '')} ({q.get('why', '')})",
            "slot": slot,
            "options": options,
            "is_multi_select": False,
        })
    return result


def get_smart_defaults(brief: str, artifact: str = "app") -> dict[str, str]:
    """Return top-tier production defaults for any missing slot without guessing randomly."""
    text = (brief or "").lower()
    defaults = {}
    if artifact == "game" or _GAME_INTENT.search(text):
        defaults["stack"] = "Python (Pygame)"
        defaults["game_genre"] = "2D Arcade Action (Core loop with scoring and restart)"
        defaults["game_controls"] = "Keyboard Arrow Keys / WASD + Spacebar to Action"
        defaults["game_visuals"] = "Retro Neon Arcade (Dark background with glowing vectors)"
        return defaults
    if artifact == "android" or _ANDROID_INTENT.search(text):
        defaults["stack"] = "Android Kotlin (Jetpack Compose)"
        defaults["mobile_framework"] = "Android Native Kotlin + Jetpack Compose"
        defaults["app_features"] = "Interactive Dashboard + List/Detail Views + Local SQLite"
        defaults["theme"] = "Material 3 Dark Theme"
        return defaults
    if artifact == "site" or _PAGE_WORDS.search(text):
        defaults["subject"] = "Project Showcase"
        defaults["site_sections"] = "Hero Showcase + Feature Grid + Interactive Demo + Contact Form"
        defaults["theme"] = "Sleek Modern Dark Theme (Obsidian & Indigo accents)"
        defaults["stack"] = "Single Page HTML + Tailwind CSS"
        return defaults

    if "python" in text or "fastapi" in text or "flask" in text:
        defaults["stack"] = "FastAPI + Modern HTML/JS Front-end"
    elif "desktop" in text or "gui" in text:
        defaults["stack"] = "PyQt6 Desktop App"
    else:
        defaults["stack"] = "React + Vite + Tailwind CSS"

    defaults["scope"] = "Local single-user tool with persistent storage"
    defaults["data_source"] = "Mock / Seed data generator with local JSON state"
    defaults["charts"] = "KPI Summary Cards + Trend Line & Bar Charts"
    defaults["metrics"] = "Key activity KPIs, volume trends, and performance over time"
    defaults["theme"] = "Sleek Modern Dark Theme (Obsidian & Indigo accents)"
    defaults["input"] = "Current workspace directory"
    defaults["output"] = "Dedicated output/ folder inside workspace"
    defaults["subject"] = "Project Showcase"
    defaults["site_sections"] = "Hero Showcase + Feature Grid + Demo + Contact Form"
    return defaults


def apply_recommended_defaults(brief: str, analysis: dict) -> dict:
    """Fill unanswered slots with high-quality smart defaults so build can proceed."""
    defaults = get_smart_defaults(brief, analysis.get("artifact", "app"))
    assumptions = []
    requirements_parts = []
    for q in analysis.get("questions", []):
        slot = q.get("slot")
        val = defaults.get(slot, "Standard defaults")
        assumptions.append(f"{slot}: {val}")
        requirements_parts.append(f"{slot}: {val}")

    updated = dict(analysis)
    updated["ready"] = True
    updated["assumptions"] = assumptions
    updated["auto_requirements"] = "\n".join(requirements_parts)
    updated["questions"] = []
    return updated


def refusal_text(analysis: dict, brief: str = "") -> str:
    """What a build call returns instead of building on assumptions.

    This string is shown to the assistant, which relays the questions to the
    user. It states plainly that nothing ran, so the assistant cannot report a
    build that did not happen.
    """
    artifact_names = {
        "app": "an application",
        "page": "a page",
        "site": "a website",
        "game": "a game",
        "android": "an android app",
        "task": "a build",
    }
    artifact = artifact_names.get(analysis.get("artifact", "task"), "a build")
    asked = questions_text(analysis)
    listed = "; ".join(q["slot"].replace("_", " ") for q in analysis["questions"])
    return (
        f"NEED REQUIREMENTS — nothing was built and nothing was started.\n"
        f"This request describes {artifact}, but it does not state: {listed}.\n\n"
        f"Ask the user these questions, one at a time, and do not answer them "
        f"yourself or pick a default:\n{asked}\n\n"
        f"Then call crown_code again with the same description and "
        f"requirements=\"<the user's answers, in their words>\". "
        f"Only pass confirmed=true if the user explicitly tells you to go ahead "
        f"without answering."
    )
