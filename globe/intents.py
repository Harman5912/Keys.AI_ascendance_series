"""globe.intents — turn an utterance into a validated globe command.

This is the deterministic half of globe routing. The primary path is the
model calling the ``globe`` tool; this module is the *guard* underneath it, so
that an explicit globe request still works when no model round-trip happens
(startup, a transcript that arrives before the session is ready, or the
user naming the globe directly).

The rules here matter more than they look:

* Only *explicit* globe requests match. "Research the best 3D globe libraries"
  is a web-research task, not an instruction to open the globe, so research and
  comparison wording vetoes the match.
* A bare "take me to <place>" matches only when the whole utterance is that
  instruction — no other intent markers — so ordinary conversation is left to
  the model instead of yanking the user into a globe workspace.
* Coordinates are never geocoded. If the user gives a latitude and longitude,
  they are used as given.
* Speech recognition mangles names. "Open GRO" is an accepted alias for the
  globe because it is unambiguous in context, but "grow", "go" and "gross" are
  not, and the alias only fires on an open/launch verb.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Commands ───────────────────────────────────────────────────────────────
# Logical actions. Each maps to a real God's Eye View mechanism in
# globe.service — these are NOT a guess about the app's API.

OPEN_GLOBE = "OPEN_GLOBE"
CLOSE_GLOBE = "CLOSE_GLOBE"
NAVIGATE_TO_LOCATION = "NAVIGATE_TO_LOCATION"
SEARCH_GLOBE = "SEARCH_GLOBE"
ZOOM_IN = "ZOOM_IN"
ZOOM_OUT = "ZOOM_OUT"
RESET_GLOBE = "RESET_GLOBE"
TOGGLE_DATA_LAYER = "TOGGLE_DATA_LAYER"
GET_GLOBE_STATUS = "GET_GLOBE_STATUS"

ACTIONS = (
    OPEN_GLOBE, CLOSE_GLOBE, NAVIGATE_TO_LOCATION, SEARCH_GLOBE,
    ZOOM_IN, ZOOM_OUT, RESET_GLOBE, TOGGLE_DATA_LAYER, GET_GLOBE_STATUS,
)

# ── Layer vocabulary ──────────────────────────────────────────────────────
# Keys are what a person says; values are the layer ids the running app
# actually toggles (src/voice/layerManifest.js). A phrase that is not in this
# table is never toggled — the adapter reports the unknown layer instead.
LAYER_ALIASES: dict[str, str] = {
    "flights": "flights",
    "flight": "flights",
    "aircraft": "flights",
    "planes": "flights",
    "airplanes": "flights",
    "commercial flights": "flights",
    "military": "military",
    "military flights": "military",
    "military aircraft": "military",
    "ships": "ais-live-vessels",
    "ship": "ais-live-vessels",
    "vessels": "ais-live-vessels",
    "boats": "ais-live-vessels",
    "marine": "ais-live-vessels",
    "satellites": "satellites",
    "satellite": "satellites",
    "launches": "rocket-launches",
    "rocket launches": "rocket-launches",
    "space missions": "rocket-launches",
    "earthquakes": "earthquakes",
    "quakes": "earthquakes",
    "seismic": "earthquakes",
    "fires": "local-firms",
    "fire": "local-firms",
    "wildfires": "local-firms",
    "fire perimeters": "fire-perimeters",
    "weather": "weather-radar",
    "radar": "weather-radar",
    "weather radar": "weather-radar",
    "clouds": "weather-satellite",
    "lightning": "weather-lightning",
    "cyclones": "weather-cyclones",
    "hurricanes": "weather-cyclones",
    "wind": "wind",
    "air quality": "air-quality",
    "cameras": "cctv",
    "camera": "cctv",
    "cctv": "cctv",
    "traffic": "traffic",
    "transit": "transit",
    "bikeshare": "bikeshare",
    "radio": "radio",
    "alpr": "alpr-cameras",
    "license plate cameras": "alpr-cameras",
    "street level": "street-level",
    "recent imagery": "recent-imagery",
    "submarine cables": "telegeography-submarine-cables",
    "cables": "telegeography-submarine-cables",
    "datacenters": "local-datacenters",
    "data centers": "local-datacenters",
    "dams": "local-dams",
    "military installations": "military-installations",
    "gnss": "gnss-integrity",
    "gnss integrity": "gnss-integrity",
    "ghost maps": "s2-ghostmaps",
    "directions": "directions",
}

ZOOM_AMOUNTS: dict[str, str] = {
    "a little": "little",
    "a bit": "little",
    "slightly": "little",
    "little": "little",
    "a lot": "lot",
    "a tonne": "lot",
    "a ton": "lot",
    "way": "lot",
    "far": "lot",
    "lot": "lot",
}

# Wording that means "this is a question about globes, not a globe command".
_VETO = re.compile(
    r"\b(research|compare|comparison|explain|explain to|what is|what are|"
    r"which is|best|better|recommend|suggest|library|libraries|framework|"
    r"frameworks|open[- ]source|github|tutorial|documentation|docs|"
    r"how do i|how to|why|write|build me a|code for|pros and cons|review)\b",
    re.I,
)

# Wording that opens / closes the globe.
_OPEN_VERB = re.compile(
    r"\b(open|launch|start|show|display|bring up|pull up|switch to|go to|"
    r"take me to|view|see)\b",
    re.I,
)
_CLOSE_VERB = re.compile(r"\b(close|hide|dismiss|exit|shut|quit|leave)\b", re.I)

# The globe, by any name a person or a speech recogniser might use.
_GLOBE_NOUN = re.compile(
    r"\b(globe|earth|world\s*view|worldview|gods?\s*eye(\s*view)?|"
    r"god'?s?\s*eye(\s*view)?|geov|g\.?e\.?v\.?|satellite\s*view|"
    r"globe\s*view|global\s*view|whole\s+world|entire\s+world|"
    r"whole\s+earth|entire\s+earth)\b",
    re.I,
)
# "open gro" — a common mis-transcription of "globe"/"GRO". Only valid with an
# open verb directly before it, and never as part of a longer word.
_GRO_ALIAS = re.compile(r"\b(?:open|launch|start|show|bring up|pull up)\s+gro\b", re.I)

# Explicit navigation verbs, for place requests that name no globe noun.
_NAV_VERB = re.compile(
    r"\b(take me to|navigate to|fly me to|fly to|zoom (?:in )?(?:on|into)|"
    r"zoom into|show me|focus on|centre on|center on|locate|point the globe at)\b",
    re.I,
)

# Words that make "take me to X" mean something other than a place.
_NOT_A_PLACE = re.compile(
    r"\b(settings|preferences|menu|panel|chat|inbox|folder|file|"
    r"document|page|tab|console|dashboard|next|previous|back|there|"
    r"bed|sleep|the gym|the store|lunch|dinner|the top|the bottom|"
    r"the beginning|the end)\b",
    re.I,
)

#: Words that carry no place information on their own. A "place" made only of
#: these is not a place — it is the leftover of sentence scaffolding.
_STOPWORDS = frozenset({
    "for", "me", "to", "on", "in", "at", "the", "a", "an", "of", "my",
    "it", "that", "this", "please", "and", "with", "from", "up", "down",
    "over", "into", "onto", "about", "out", "is", "are", "be", "can",
    "you", "could", "would", "will", "just", "now", "then", "here",
})

_COORD_PAIR = re.compile(
    r"(-?\d{1,3}(?:\.\d+)?)\s*[,;]?\s*(?:n|s)?\s*[,;/]?\s*(-?\d{1,3}(?:\.\d+)?)"
    r"\s*(?:,|;)?\s*(?:e|w)?",
    re.I,
)
_GEO_URI = re.compile(r"geo:\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", re.I)

_FILLER = re.compile(
    r"^(?:keys[,.]?\s*|hey keys[,.]?\s*|okay keys[,.]?\s*|ok keys[,.]?\s*|"
    r"please\s+|could you\s+|can you\s+|would you\s+|i want you to\s+|"
    r"i'?d like you to\s+|let'?s\s+)",
    re.I,
)
_TRAILING_PLEASE = re.compile(r"[, ]*\bplease\b[,.]?\s*$", re.I)
_PUNCT = re.compile(r"[?!\.]+$")


@dataclass
class GlobeCommand:
    """One validated globe instruction, ready for the adapter."""

    action: str
    location: str = ""
    latitude: float | None = None
    longitude: float | None = None
    direction: str = ""
    amount: str = "medium"
    layer: str = ""
    enabled: bool = True
    query: str = ""
    raw: str = ""
    ambiguity: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "location": self.location,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "direction": self.direction,
            "amount": self.amount,
            "layer": self.layer,
            "enabled": self.enabled,
            "query": self.query,
            "raw": self.raw,
            "ambiguity": list(self.ambiguity),
        }


def _clean(text: str) -> str:
    """Strip wake words, politeness and trailing punctuation."""
    out = str(text or "").strip()
    for _ in range(3):
        stripped = _FILLER.sub("", out)
        if stripped == out:
            break
        out = stripped
    out = _TRAILING_PLEASE.sub("", out)
    out = _PUNCT.sub("", out)
    return out.strip()


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """Return (lat, lon) when `text` states coordinates explicitly.

    Accepts ``26.4499, 80.3319``, ``geo:26.4499,80.3319`` and hemisphere
    suffixes. Returns None unless both numbers are in range and the string
    really is a coordinate pair rather than prose containing numbers.
    """
    raw = str(text or "")
    geo = _GEO_URI.search(raw)
    if geo:
        lat, lon = float(geo.group(1)), float(geo.group(2))
        return (lat, lon) if _valid_latlon(lat, lon) else None

    # Only believe a pair when the text around it carries no other numbers a
    # user might actually mean (prices, dates, counts).
    numbers = re.findall(r"-?\d+(?:\.\d+)?", raw)
    if len(numbers) != 2:
        return None
    match = _COORD_PAIR.search(raw)
    if not match:
        return None
    try:
        lat, lon = float(match.group(1)), float(match.group(2))
    except (TypeError, ValueError):
        return None
    if not _valid_latlon(lat, lon):
        return None
    return (lat, lon)


def _valid_latlon(lat: float, lon: float) -> bool:
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return False
    # 0,0 is the null island — almost always a parse accident, not intent.
    return not (abs(lat) < 1e-9 and abs(lon) < 1e-9)


def _find_layer(text: str) -> tuple[str, bool] | None:
    """Return (layer_id, enabled) if the utterance toggles a known layer."""
    lowered = text.lower()
    # Longest alias first so "weather radar" wins over "weather".
    enable = True
    if re.search(r"\b(off|disable|hide|turn off|switch off|remove|stop)\b", lowered):
        enable = False
    for alias in sorted(LAYER_ALIASES, key=len, reverse=True):
        if re.search(r"\b" + re.escape(alias) + r"\b", lowered):
            return LAYER_ALIASES[alias], enable
    return None


def _strip_globe_nouns(text: str) -> str:
    out = _GLOBE_NOUN.sub(" ", text)
    # "open gro" is the globe too, so it must not survive as a place name.
    out = re.sub(r"\bgro\b", " ", out, flags=re.I)
    out = re.sub(r"\b(?:on|in|at|to|the|a|an|me|my|the globe|view)\b", " ", out, flags=re.I)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,;:-")
    return out


def _has_place_word(text: str) -> bool:
    """True when `text` contains a word that can name something."""
    words = re.findall(r"[A-Za-z0-9'À-￿]+", text or "")
    return any(word.lower() not in _STOPWORDS for word in words)


def try_parse(text: str) -> GlobeCommand | None:
    """Return the globe command `text` asks for, or None if it is not one.

    Returning None is the normal, expected answer for most utterances: the
    model handles everything this function does not recognise.
    """
    cleaned = _clean(text)
    if not cleaned or len(cleaned) > 400:
        return None
    if _VETO.search(cleaned):
        return None

    lowered = cleaned.lower()
    has_globe_noun = bool(_GLOBE_NOUN.search(cleaned)) or bool(_GRO_ALIAS.search(cleaned))
    has_open = bool(_OPEN_VERB.search(cleaned))
    has_close = bool(_CLOSE_VERB.search(cleaned))

    # ── Close ─────────────────────────────────────────────────────────────
    if has_close and (has_globe_noun or lowered in ("close it", "hide it", "dismiss it")):
        return GlobeCommand(action=CLOSE_GLOBE, raw=text)

    # ── Status ────────────────────────────────────────────────────────────
    if has_globe_noun and re.search(
        r"\b(status|ready|working|loaded|running|is it up|state)\b", lowered
    ):
        return GlobeCommand(action=GET_GLOBE_STATUS, raw=text)

    # ── Reset / full earth ────────────────────────────────────────────────
    if re.search(
        r"\b(reset|home view|whole earth|full earth|the whole world|"
        r"entire earth|zoom (?:all the way )?out to (?:the )?(?:globe|earth|world)|"
        r"back to (?:the )?(?:globe|earth|world) view)\b", lowered
    ) and (has_globe_noun or re.search(r"\b(reset|home)\b", lowered)):
        return GlobeCommand(action=RESET_GLOBE, raw=text)

    # ── Zoom ──────────────────────────────────────────────────────────────
    zoom = re.search(
        r"\bzoom(?:ing)?\s+(in|out)\b|\b(?:go )?(closer|further|farther)\b",
        lowered,
    )
    if zoom:
        if not (has_globe_noun
                or re.search(r"\bzoom(?:ing)?\b|\b(closer|further|farther)\b",
                             lowered)):
            return None
        direction = "in" if (zoom.group(1) == "in" or zoom.group(2)) else "out"
        amount = "medium"
        for phrase, value in ZOOM_AMOUNTS.items():
            if phrase in lowered:
                amount = value
                break
        target = _strip_globe_nouns(cleaned)
        target = re.sub(r"\b(zooming|zoom|in|out|closer|further|farther|a little|"
                        r"a bit|a lot|slightly|way|far|lot|please)\b", " ",
                        target, flags=re.I)
        target = re.sub(r"\s{2,}", " ", target).strip(" ,;:-")
        cmd = GlobeCommand(action=ZOOM_IN if direction == "in" else ZOOM_OUT,
                           direction=direction, amount=amount, raw=text)
        # "zoom into Kanpur" is a navigation, not a bare zoom on the current view.
        if direction == "in" and target and len(target.split()) <= 6:
            cmd.action = NAVIGATE_TO_LOCATION
            cmd.location = target
        return cmd

    # ── Layers ────────────────────────────────────────────────────────────
    layer = _find_layer(cleaned)
    if layer and re.search(
        r"\b(turn|toggle|switch|enable|disable|show|hide|add|remove|put|layer|"
        r"on|off|display)\b", lowered
    ):
        layer_id, enabled = layer
        # Only claim it when the utterance is about the globe, or is a bare
        # "turn on the satellite layer" instruction. The alias table is specific
        # ("satellites", "submarine cables"), so "enable dark mode" cannot reach
        # here — "mode" is not a layer name.
        looks_bare = re.search(
            r"\blayer\b|\bturn (?:on|off)\b|\btoggle\b|\b(?:enable|disable|switch)\b",
            lowered,
        )
        if has_globe_noun or looks_bare:
            return GlobeCommand(action=TOGGLE_DATA_LAYER, layer=layer_id,
                                enabled=enabled, raw=text)

    # ── Explicit coordinates ──────────────────────────────────────────────
    coords = parse_coordinates(cleaned)
    if coords:
        return GlobeCommand(action=NAVIGATE_TO_LOCATION, latitude=coords[0],
                            longitude=coords[1], raw=text)

    # ── Named place ───────────────────────────────────────────────────────
    if has_globe_noun:
        place = _strip_globe_nouns(cleaned)
        place = re.sub(r"\b(open|launch|start|show|display|bring up|pull up|"
                       r"switch to|go to|view|see|me|the|a|an|for)\b", " ", place, flags=re.I)
        place = re.sub(r"\s{2,}", " ", place).strip(" ,;:-")
        if _has_place_word(place) and not _NOT_A_PLACE.search(place):
            return GlobeCommand(action=NAVIGATE_TO_LOCATION, location=place,
                                query=place, raw=text)
        return GlobeCommand(action=OPEN_GLOBE, raw=text)

    # ── "Take me to India" with no globe noun ─────────────────────────────
    # Accepted only when the whole utterance is that instruction and the
    # target is not something that is obviously not a place.
    nav = _NAV_VERB.search(cleaned)
    if nav and len(cleaned.split()) <= 12:
        place = cleaned[nav.end():].strip(" ,;:-")
        # "the geographical location of the Taj Mahal" -> "the Taj Mahal"
        place = re.sub(
            r"^(?:the\s+)?(?:geographical\s+|geographic\s+|exact\s+)?"
            r"(?:location|position|whereabouts)\s+(?:of\s+)?", "", place, flags=re.I)
        place = re.sub(r"\s{2,}", " ", place).strip(" ,;:-")
        if (_has_place_word(place) and not _NOT_A_PLACE.search(place)
                and not re.search(r"\b(it|that|this|him|her|them)\b", place)):
            return GlobeCommand(action=NAVIGATE_TO_LOCATION, location=place,
                                query=place, raw=text)

    # ── Bare open ─────────────────────────────────────────────────────────
    if has_open and has_globe_noun:
        return GlobeCommand(action=OPEN_GLOBE, raw=text)

    return None


def is_globe_request(text: str) -> bool:
    """True when `text` is an explicit globe instruction."""
    return try_parse(text) is not None


def describe(command: GlobeCommand) -> str:
    """A short human sentence for the acknowledgement, matching the action."""
    if command.action == OPEN_GLOBE:
        return "Opening the globe."
    if command.action == CLOSE_GLOBE:
        return "Closing the globe."
    if command.action == RESET_GLOBE:
        return "Resetting the globe view."
    if command.action == ZOOM_IN:
        return "Zooming in."
    if command.action == ZOOM_OUT:
        return "Zooming out."
    if command.action == GET_GLOBE_STATUS:
        return "Checking the globe."
    if command.action == NAVIGATE_TO_LOCATION:
        if command.latitude is not None:
            return f"Flying to {command.latitude:.4f}, {command.longitude:.4f}."
        return f"Flying to {command.location or command.query}."
    if command.action == TOGGLE_DATA_LAYER:
        state = "on" if command.enabled else "off"
        return f"Turning the {command.layer} layer {state}."
    return command.action
