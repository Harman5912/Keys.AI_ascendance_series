"""Website design presets — 50+ looks, chosen for the brief automatically.

A *studio* is a layout system (ten of them, see ``themes.py``). A *preset* is a
look within a studio: its accent palette, the mood it suits, and the kinds of
site it belongs on. Two restaurant sites should not always be the same site, so
the builder scores every preset against the brief, keeps the best matches and
lets the brief's own hash decide between the near-ties. That is deliberate
variety, not randomness: the same brief rebuilt gets the same look, a different
brief in the same category usually gets another one.

The palettes are pre-checked against each studio's own surfaces: bright accents
on the dark studios, dark accents on the light ones, and the acid/gold studios
keep their character instead of being repainted with a generic blue.
"""

from __future__ import annotations

import hashlib
import re

from .content import score_studios
from .themes import ORDER

# Which CSS variables carry a preset's two accents inside each studio. The
# studios deliberately do not share variable names (that is why they do not
# look alike), so the mapping lives here instead of being guessed at render
# time. Third entry is the focus-ring colour.
_STUDIO_VARS = {
    "aurora":    ("--accent", "--accent2", "--crown-focus"),
    "editorial": ("--accent", "--accent2", "--crown-focus"),
    "brutalist": ("--acid", "--hot", "--crown-focus"),
    "swiss":     ("--red", None, "--crown-focus"),
    "terminal":  ("--accent", "--accent2", "--crown-focus"),
    "organic":   ("--green", "--clay", "--crown-focus"),
    "luxury":    ("--gold", "--gold-soft", "--crown-focus"),
    "pop":       ("--pink", "--lime", "--crown-focus"),
    "cinematic": ("--amber", "--ember", "--crown-focus"),
    "newsroom":  ("--red", "--navy", "--crown-focus"),
}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# id, label, studio, accent, accent2, moods, kinds, summary
_RAW: list[tuple] = [
    # ── Aurora — dark glass / lightfield ──────────────────────────────────
    ("aurora-nocturne", "Aurora Nocturne", "aurora", "#7c5cff", "#22d3ee",
     ("ai", "artificial", "intelligence", "saas", "developer", "api", "platform"),
     ("website", "webapp"), "Dark glass, violet and cyan lightfield"),
    ("aurora-signal", "Aurora Signal", "aurora", "#3b82f6", "#34d399",
     ("cloud", "devops", "infrastructure", "analytics", "dashboard", "data"),
     ("website", "webapp"), "Blue signal with green telemetry"),
    ("aurora-ember", "Aurora Ember", "aurora", "#ff7a45", "#f472b6",
     ("creative", "agency", "studio", "brand", "marketing"),
     ("website", "portfolio"), "Warm ember glow, pink edge light"),
    ("aurora-mint", "Aurora Mint", "aurora", "#2dd4bf", "#c084fc",
     ("health", "wellness", "medical", "care", "therapy"),
     ("website", "webapp"), "Mint calm with lilac highlights"),
    ("aurora-rose", "Aurora Rose", "aurora", "#f43f5e", "#818cf8",
     ("fintech", "finance", "banking", "crypto", "payments"),
     ("website", "webapp"), "Rose fintech with indigo depth"),
    ("aurora-solar", "Aurora Solar", "aurora", "#fbbf24", "#2dd4bf",
     ("energy", "climate", "solar", "sustainability", "green"),
     ("website", "webapp"), "Solar amber against teal glass"),
    ("aurora-forest", "Aurora Forest", "aurora", "#22c55e", "#84cc16",
     ("nature", "outdoor", "conservation", "eco", "farm"),
     ("website", "portfolio"), "Forest green lightfield"),

    # ── Editorial — paper / magazine ──────────────────────────────────────
    ("editorial-broadsheet", "Editorial Broadsheet", "editorial", "#b23a2b", "#1f4e46",
     ("magazine", "publishing", "journal", "news", "writer", "editor"),
     ("website", "portfolio"), "Oxblood headlines on warm paper"),
    ("editorial-coastal", "Editorial Coastal", "editorial", "#1d4ed8", "#0f766e",
     ("travel", "culture", "museum", "tourism", "guide"),
     ("website", "portfolio"), "Navy and sea-teal reading layout"),
    ("editorial-vine", "Editorial Vine", "editorial", "#4d7c0f", "#b45309",
     ("food", "restaurant", "cafe", "craft", "farm", "recipe"),
     ("website", "portfolio"), "Olive and brick, menu-friendly"),
    ("editorial-ink", "Editorial Ink", "editorial", "#1f2937", "#a16207",
     ("law", "consulting", "advisory", "finance", "legal"),
     ("website", "portfolio"), "Ink serif with restrained gold"),
    ("editorial-rose", "Editorial Rose", "editorial", "#9f1239", "#1e3a8a",
     ("fashion", "beauty", "lifestyle", "wedding"),
     ("website", "portfolio"), "Rose press with couture navy"),

    # ── Brutalist — acid / protest ────────────────────────────────────────
    ("brutalist-acid", "Brutalist Acid", "brutalist", "#e8ff00", "#ff3b00",
     ("art", "music", "band", "festival", "gallery", "punk"),
     ("website", "portfolio"), "Acid yellow, hard borders"),
    ("brutalist-lime", "Brutalist Lime", "brutalist", "#b9ff2e", "#ff2d55",
     ("startup", "launch", "event", "conference", "hackathon"),
     ("website", "portfolio"), "Signal lime with hot pink strike"),
    ("brutalist-cyber", "Brutalist Cyber", "brutalist", "#00e5ff", "#ff00a8",
     ("gaming", "esports", "tech", "streamer", "clothing"),
     ("website", "portfolio"), "Cyber cyan and magenta"),
    ("brutalist-warning", "Brutalist Warning", "brutalist", "#ffb300", "#ff1744",
     ("sports", "fitness", "gym", "training", "boxing"),
     ("website", "portfolio"), "Warning amber and red"),
    ("brutalist-concrete", "Brutalist Concrete", "brutalist", "#ff3d00", "#0a0a0a",
     ("protest", "news", "activism", "zine", "collective"),
     ("website", "portfolio"), "Concrete grey with hot orange"),

    # ── Swiss — grid / reduction ──────────────────────────────────────────
    ("swiss-red", "Swiss Red", "swiss", "#e0002b", None,
     ("design", "architecture", "graphic", "studio", "typography"),
     ("portfolio", "website"), "Classic red on a strict grid"),
    ("swiss-blue", "Swiss Blue", "swiss", "#0b57d0", None,
     ("engineering", "b2b", "industrial", "manufacturing", "systems"),
     ("website", "portfolio"), "Engineered blue, hairline rules"),
    ("swiss-green", "Swiss Green", "swiss", "#157f3c", None,
     ("sustainability", "climate", "recycling", "energy", "esg"),
     ("website", "portfolio"), "Measured green on off-white"),
    ("swiss-black", "Swiss Black", "swiss", "#111111", None,
     ("photography", "photographer", "photojournalism", "portfolio", "personal", "designer"),
     ("portfolio", "website"), "Monochrome grid, no decoration"),
    ("swiss-violet", "Swiss Violet", "swiss", "#5b21b6", None,
     ("research", "education", "science", "university", "lab"),
     ("website", "portfolio"), "Academic violet, numbered sections"),

    # ── Terminal — phosphor / CLI ─────────────────────────────────────────
    ("terminal-phosphor", "Terminal Phosphor", "terminal", "#41ff7e", "#ffcf4d",
     ("developer", "cli", "devtools", "linux", "open", "source"),
     ("webapp", "website"), "Classic green phosphor terminal"),
    ("terminal-amber", "Terminal Amber", "terminal", "#ffb000", "#4ade80",
     ("security", "ops", "infrastructure", "pentest"),
     ("webapp", "website"), "Amber CRT with green confirmation"),
    ("terminal-cyan", "Terminal Cyan", "terminal", "#22d3ee", "#a3e635",
     ("data", "ml", "machine", "analytics", "pipeline"),
     ("webapp", "website"), "Cyan shell with lime output"),
    ("terminal-magenta", "Terminal Magenta", "terminal", "#f472b6", "#38bdf8",
     ("creative", "coding", "generative", "shader", "demo"),
     ("webapp", "portfolio"), "Magenta debug console"),
    ("terminal-ice", "Terminal Ice", "terminal", "#a5f3fc", "#c084fc",
     ("cloud", "mainframe", "network", "platform", "sre"),
     ("webapp", "website"), "Cold cyan mainframe light"),

    # ── Organic — botanical / warm ────────────────────────────────────────
    ("organic-fern", "Organic Fern", "organic", "#3f6b46", "#d98c5f",
     ("wellness", "yoga", "food", "restaurant", "cafe", "tea"),
     ("website", "portfolio"), "Fern green and warm clay"),
    ("organic-grove", "Organic Grove", "organic", "#5f6f2e", "#c2703a",
     ("farm", "organic", "market", "harvest", "agriculture"),
     ("website", "portfolio"), "Olive grove with terracotta"),
    ("organic-terracotta", "Organic Terracotta", "organic", "#8a4b2f", "#5d7c4a",
     ("ceramics", "craft", "pottery", "handmade", "artisan"),
     ("website", "portfolio"), "Clay brown and kiln green"),
    ("organic-moss", "Organic Moss", "organic", "#4a6b5a", "#b08968",
     ("retreat", "travel", "spa", "nature", "cabin"),
     ("website", "portfolio"), "Moss and stone, slow living"),
    ("organic-heather", "Organic Heather", "organic", "#6b4f7a", "#8a9a5b",
     ("beauty", "skincare", "botanical", "lifestyle"),
     ("website", "portfolio"), "Heather purple with field green"),

    # ── Luxury — ink / gold ───────────────────────────────────────────────
    ("luxury-antique", "Luxury Antique", "luxury", "#c9a227", "#e8d9b5",
     ("jewelry", "jewellery", "watches", "hospitality", "hotel"),
     ("website", "portfolio"), "Antique gold on deep ink"),
    ("luxury-champagne", "Luxury Champagne", "luxury", "#e2c799", "#b08d57",
     ("events", "wedding", "fashion", "couture", "planner"),
     ("website", "portfolio"), "Champagne and soft brass"),
    ("luxury-platinum", "Luxury Platinum", "luxury", "#c0c6cf", "#8b93a1",
     ("automotive", "yacht", "aviation", "premium", "technology"),
     ("website", "portfolio"), "Platinum cool, restrained"),
    ("luxury-burgundy", "Luxury Burgundy", "luxury", "#c94a55", "#d4af37",
     ("wine", "vineyard", "dining", "restaurant", "cigar"),
     ("website", "portfolio"), "Wine red with brass rules"),
    ("luxury-emerald", "Luxury Emerald", "luxury", "#2f6b53", "#d4af37",
     ("real", "estate", "property", "private", "wealth"),
     ("website", "portfolio"), "Emerald and gold, private office"),

    # ── Pop — candy / playful ─────────────────────────────────────────────
    ("pop-bubblegum", "Pop Bubblegum", "pop", "#ff4d6d", "#b8ff3d",
     ("kids", "children", "candy", "bakery", "dessert", "toys"),
     ("website", "portfolio"), "Bubblegum pink and lime"),
    ("pop-electric", "Pop Electric", "pop", "#15803d", "#facc15",
     ("fitness", "dance", "music", "festival", "party"),
     ("website", "portfolio"), "Electric green and sun yellow"),
    ("pop-sky", "Pop Sky", "pop", "#0369a1", "#f97316",
     ("education", "app", "learning", "school", "tutor"),
     ("website", "webapp"), "Sky blue with orange pops"),
    ("pop-peach", "Pop Peach", "pop", "#be123c", "#a3e635",
     ("beauty", "lifestyle", "makeup", "salon", "spa"),
     ("website", "portfolio"), "Peach fizz and soft lime"),
    ("pop-arcade", "Pop Arcade", "pop", "#f43f5e", "#fde047",
     ("games", "gaming", "arcade", "esports", "streamer"),
     ("website", "webapp"), "Arcade red and screen yellow"),

    # ── Cinematic — film / full-bleed ─────────────────────────────────────
    ("cinematic-gold", "Cinematic Gold", "cinematic", "#e8c547", "#ff5a36",
     ("film", "cinema", "photography", "photographer", "director"),
     ("portfolio", "website"), "Warm gold print, ember highlights"),
    ("cinematic-teal", "Cinematic Teal", "cinematic", "#2dd4bf", "#f97316",
     ("documentary", "travel", "adventure", "outdoor"),
     ("portfolio", "website"), "Teal grade, sunset contrast"),
    ("cinematic-crimson", "Cinematic Crimson", "cinematic", "#ef4444", "#fbbf24",
     ("music", "band", "thriller", "video", "production"),
     ("portfolio", "website"), "Crimson reel with amber light"),
    ("cinematic-silver", "Cinematic Silver", "cinematic", "#cbd5e1", "#60a5fa",
     ("studio", "agency", "motion", "production", "design"),
     ("portfolio", "website"), "Silver screen, cool projector blue"),
    ("cinematic-desert", "Cinematic Desert", "cinematic", "#f59e0b", "#dc2626",
     ("desert", "overland", "motorsport", "adventure", "travel"),
     ("portfolio", "website"), "Desert amber with red dust"),

    # ── Newsroom — broadsheet / data ──────────────────────────────────────
    ("newsroom-red", "Newsroom Red", "newsroom", "#c8102e", "#003366",
     ("news", "politics", "journalism", "daily", "report"),
     ("website", "portfolio"), "Classic broadsheet red and navy"),
    ("newsroom-market", "Newsroom Market", "newsroom", "#0f766e", "#1e3a8a",
     ("finance", "business", "market", "economy", "investing"),
     ("website", "portfolio"), "Market green with business navy"),
    ("newsroom-sport", "Newsroom Sport", "newsroom", "#b91c1c", "#111827",
     ("sports", "football", "cricket", "club", "league"),
     ("website", "portfolio"), "Sport crimson and ink"),
    ("newsroom-tech", "Newsroom Tech", "newsroom", "#1d4ed8", "#0f766e",
     ("technology", "tech", "gadgets", "software", "startup"),
     ("website", "portfolio"), "Tech navy with teal data"),
    ("newsroom-culture", "Newsroom Culture", "newsroom", "#7e22ce", "#9a3412",
     ("arts", "culture", "theatre", "books", "review"),
     ("website", "portfolio"), "Culture plum with burnt orange"),
]


def _preset(row: tuple) -> dict:
    pid, label, studio, accent, accent2, moods, kinds, summary = row
    return {
        "id": pid,
        "label": label,
        "studio": studio if studio in ORDER else "aurora",
        "accent": accent,
        "accent2": accent2 or accent,
        "moods": tuple(moods),
        "kinds": tuple(kinds),
        "summary": summary,
    }


PRESETS: list[dict] = [_preset(row) for row in _RAW]
_BY_ID: dict[str, dict] = {p["id"]: p for p in PRESETS}


def get(preset_id: str) -> dict | None:
    return _BY_ID.get(str(preset_id or "").strip())


def preset_css(preset: dict) -> str:
    """The `:root` override that gives a studio this preset's palette."""
    if not preset:
        return ""
    studio_vars = _STUDIO_VARS.get(preset.get("studio") or "", ("--accent", None, "--crown-focus"))
    accent, accent2, focus = studio_vars
    pairs = []
    if accent and _HEX.match(str(preset.get("accent") or "")):
        pairs.append(f"{accent}:{preset['accent']}")
    if accent2 and _HEX.match(str(preset.get("accent2") or "")):
        pairs.append(f"{accent2}:{preset['accent2']}")
    if focus:
        pairs.append(f"{focus}:{preset.get('accent') or preset.get('accent2')}")
    return ":root{" + ";".join(pairs) + "}" if pairs else ""


def apply_preset_css(html: str, preset: dict) -> str:
    """Append the preset override to the page's own <style> block."""
    css = preset_css(preset)
    if not css or "</style>" not in html:
        return html
    return html.replace("</style>", css + "</style>", 1)


def score_presets(brief: str, kind: str = "website") -> list[tuple[int, str]]:
    """(score, preset id) for every preset, best last-match order preserved."""
    text = (brief or "").lower()
    studio_scores = dict(score_studios(brief, kind))
    out: list[tuple[int, str]] = []
    for preset in PRESETS:
        score = studio_scores.get(preset["studio"], 0)
        if kind in preset["kinds"]:
            score += 3
        for word in preset["moods"]:
            if re.search(rf"\b{re.escape(word)}\b", text):
                score += 2
        out.append((score, preset["id"]))
    return out


def choose_preset(brief: str, kind: str = "website", seed: str = "") -> dict:
    """The best preset for this brief; near-ties vary by the brief's hash.

    Same brief + seed → same preset (builds are reproducible); a different
    brief in the same category usually gets another look, which is the point of
    having more than one preset per kind.
    """
    scores = score_presets(brief, kind)
    best = max(score for score, _ in scores)
    tied = [pid for score, pid in scores if score == best]
    if best <= 3:
        # No keyword matched: stay inside the presets built for this kind and
        # let the brief pick, instead of always landing on the first one.
        by_kind = [p["id"] for p in PRESETS if kind in p["kinds"]] or [p["id"] for p in PRESETS]
        tied = by_kind
    digest = hashlib.sha256((str(brief or "") + "|" + str(seed or "")).encode("utf-8")).hexdigest()
    return _BY_ID[sorted(tied)[int(digest[:8], 16) % len(sorted(tied))]]


__all__ = ["PRESETS", "choose_preset", "score_presets", "get", "preset_css",
           "apply_preset_css"]
