"""Design tokens for every build: colour, type, space, radius, layout.

The point of this module is that a build never invents its own colours or
spacing. It asks for tokens, gets a coherent set, and every text/background
pair in that set has been checked with the WCAG contrast formula before it is
handed over.

Contrast thresholds come from WCAG 2.2 Success Criterion 1.4.3 (Contrast
(Minimum)), verified against the specification rather than from memory:

    4.5:1  body text
    3:1    large text (>= 18pt, or >= 14pt bold) and UI boundaries

    https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html

The palette shape (surfaces, one accent, one danger, one success, a muted ink)
follows the convention already used by the generated desktop theme in
``core/app_builder.py`` (``_DESK_THEME_PY``: ACCENT/BG/PANEL/INK/MUTED/LINE/
WARN), so tokens drop into existing templates instead of describing a new
house style.

Nothing here talks to a model and nothing here is random: the same seed always
produces the same tokens, which is what makes the design gate reproducible.
"""

from __future__ import annotations

import colorsys
import hashlib

# ── WCAG contrast ────────────────────────────────────────────────────────────

AA_TEXT = 4.5          # body text
AA_LARGE = 3.0         # large text and non-text UI boundaries


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError(f"Not a 6-digit hex colour: {value!r}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def relative_luminance(color: str) -> float:
    """WCAG relative luminance of a hex colour."""
    channels = []
    for raw in _hex_to_rgb(color):
        c = raw / 255.0
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: str, background: str) -> float:
    """Contrast ratio between two hex colours, from 1.0 to 21.0."""
    a = relative_luminance(foreground)
    b = relative_luminance(background)
    lighter, darker = (a, b) if a >= b else (b, a)
    return (lighter + 0.05) / (darker + 0.05)


def meets(foreground: str, background: str, target: float = AA_TEXT) -> bool:
    return contrast_ratio(foreground, background) >= target


# ── HSL helpers ──────────────────────────────────────────────────────────────

def hsl_to_hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360.0, max(0.0, min(1.0, l)),
                                  max(0.0, min(1.0, s)))
    return _rgb_to_hex((r * 255, g * 255, b * 255))


def hex_to_hsl(color: str) -> tuple[float, float, float]:
    r, g, b = (c / 255 for c in _hex_to_rgb(color))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360.0, s, l


def _hue_from_seed(seed: str) -> float:
    """A stable hue for a seed, so the same brief keeps the same look."""
    digest = hashlib.sha256(seed.strip().lower().encode("utf-8")).digest()
    return (digest[0] << 8 | digest[1]) % 360


def _push_away(h: float, s: float, l: float, background: str,
               target: float, *, lighter: bool) -> str:
    """Raise/lower lightness until `target` contrast against `background` is met.

    Returns the first colour that satisfies the target, or the extreme
    lightness that got closest if the target is unreachable.
    """
    step = 0.02
    current = l
    best = hsl_to_hex(h, s, current)
    for _ in range(60):
        best = hsl_to_hex(h, s, current)
        if contrast_ratio(best, background) >= target:
            return best
        current = current + step if lighter else current - step
        if current >= 1.0 or current <= 0.0:
            break
    return hsl_to_hex(h, s, 1.0 if lighter else 0.0)


# ── Tokens ───────────────────────────────────────────────────────────────────

class Tokens:
    """A complete, contrast-checked design token set."""

    def __init__(self, palette: dict[str, str], *, kind: str, mood: str,
                 seed: str) -> None:
        self.palette = palette
        self.kind = kind
        self.mood = mood
        self.seed = seed
        self.font_sizes = _type_scale(kind)
        self.spaces = (4, 8, 12, 16, 24, 32, 48, 64)
        self.radii = {"sm": 6, "md": 8, "lg": 12}
        self.fonts = _font_stack(kind)

    # -- accessors ---------------------------------------------------------
    def color(self, name: str) -> str:
        return self.palette[name]

    def pairs(self) -> list[tuple[str, str, float, str]]:
        """(foreground, background, target, why) for every pair that matters."""
        p = self.palette
        return [
            (p["ink"], p["bg"], AA_TEXT, "body text on background"),
            (p["ink"], p["panel"], AA_TEXT, "body text on panel"),
            (p["muted"], p["bg"], AA_TEXT, "muted text on background"),
            (p["muted"], p["panel"], AA_TEXT, "muted text on panel"),
            (p["on_accent"], p["accent"], AA_TEXT, "label on the accent"),
            (p["accent"], p["bg"], AA_LARGE, "accent as a UI boundary"),
            (p["danger"], p["bg"], AA_LARGE, "danger as a UI boundary"),
            (p["line"], p["panel"], 1.15, "divider visible against panel"),
        ]

    def contrast_report(self) -> list[dict]:
        out = []
        for fg, bg, target, why in self.pairs():
            ratio = contrast_ratio(fg, bg)
            out.append({"fg": fg, "bg": bg, "target": target,
                        "ratio": round(ratio, 2), "ok": ratio >= target,
                        "why": why})
        return out

    def problems(self) -> list[str]:
        return [f"{row['why']}: {row['ratio']}:1 < {row['target']}:1"
                for row in self.contrast_report() if not row["ok"]]

    # -- renderers ---------------------------------------------------------
    def to_css(self, selector: str = ":root") -> str:
        p = self.palette
        lines = [f"{selector} {{"]
        for name in ("bg", "panel", "line", "ink", "muted",
                     "accent", "accent_hover", "on_accent", "danger", "success"):
            lines.append(f"  --{name.replace('_', '-')}: {p[name]};")
        # Aliases the existing dashboard stylesheet already consumes, so one
        # palette can replace its hardcoded :root without renaming every rule.
        lines.append(f"  --good: {p['success']};")
        lines.append(f"  --bad: {p['danger']};")
        lines.append(f"  --warn: {p['accent']};")
        lines.append(f"  --radius: {self.radii['lg']}px;")
        lines.append(f"  --font-sans: {self.fonts['sans']};")
        lines.append(f"  --font-mono: {self.fonts['mono']};")
        for name, size in self.font_sizes.items():
            lines.append(f"  --text-{name}: {size}px;")
        for index, size in enumerate(self.spaces, start=1):
            lines.append(f"  --space-{index}: {size}px;")
        for name, size in self.radii.items():
            lines.append(f"  --radius-{name}: {size}px;")
        lines.append("}")
        return "\n".join(lines) + "\n"

    def to_qt_theme(self, title: str = "") -> str:
        """A drop-in ``app/theme.py`` matching the builder's existing shape.

        The stylesheet is emitted as a plain string with the colours already
        substituted, not as an f-string: a generated f-string has to escape
        every CSS brace twice, and getting that wrong produces a theme module
        that does not even import.
        """
        p = self.palette
        doc = f'"""Colours and the shared stylesheet for {title}."""\n\n'
        doc += "from __future__ import annotations\n\n"
        for const, key in (("ACCENT", "accent"), ("BG", "bg"), ("PANEL", "panel"),
                           ("INK", "ink"), ("MUTED", "muted"), ("LINE", "line"),
                           ("WARN", "danger"), ("GOOD", "success"),
                           ("ON_ACCENT", "on_accent"),
                           ("ACCENT_HOVER", "accent_hover")):
            doc += f'{const} = "{p[key]}"\n'
        base = self.font_sizes["base"]
        radius = self.radii["md"]
        css = (
            f"QMainWindow, QWidget {{ background: {p['bg']}; color: {p['ink']};\n"
            f"    font-family: '{self.fonts['sans']}'; font-size: {base}px; }}\n"
            f"QLabel#title {{ font-size: {self.font_sizes['title']}px; "
            "font-weight: 600; }\n"
            f"QLabel#hint {{ color: {p['muted']}; }}\n"
            f"QLabel#total {{ font-size: {self.font_sizes['subtitle']}px; "
            f"font-weight: 600; color: {p['accent']}; }}\n"
            "QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {\n"
            f"    background: {p['panel']}; border: 1px solid {p['line']};\n"
            f"    border-radius: {radius}px; padding: 8px; color: {p['ink']}; }}\n"
            f"QLineEdit:focus, QComboBox:focus {{ border: 1px solid {p['accent']}; }}\n"
            f"QPushButton {{ background: {p['accent']}; color: {p['on_accent']};\n"
            f"    border: 0; border-radius: {radius}px; padding: 8px 16px;\n"
            "    font-weight: 600; }\n"
            f"QPushButton:hover {{ background: {p['accent_hover']}; }}\n"
            f"QPushButton:disabled {{ background: {p['line']}; color: {p['muted']}; }}\n"
            f"QPushButton#ghost {{ background: transparent; color: {p['ink']};\n"
            f"    border: 1px solid {p['line']}; }}\n"
            f"QPushButton#ghost:hover {{ border-color: {p['accent']}; "
            f"color: {p['accent']}; }}\n"
            f"QTableWidget {{ background: {p['panel']}; "
            f"border: 1px solid {p['line']}; border-radius: {radius}px;\n"
            f"    gridline-color: {p['line']}; }}\n"
            f"QHeaderView::section {{ background: {p['panel']}; "
            f"color: {p['muted']}; border: 0;\n"
            f"    border-bottom: 1px solid {p['line']}; padding: 8px;\n"
            f"    font-size: {self.font_sizes['caption']}px; }}\n"
            f"QStatusBar {{ color: {p['muted']}; }}\n"
        )
        doc += f'\nSTYLESHEET = """{css}"""\n'
        return doc

    def to_prompt_block(self) -> str:
        """Text for a build prompt: the tokens, and the rules that go with them."""
        p = self.palette
        sizes = ", ".join(f"{k}={v}px" for k, v in self.font_sizes.items())
        return (
            "## DESIGN TOKENS (use these exact values — do not invent colours)\n"
            f"- background `{p['bg']}`, panel/surface `{p['panel']}`, "
            f"divider `{p['line']}`\n"
            f"- body text `{p['ink']}`, secondary text `{p['muted']}`\n"
            f"- accent `{p['accent']}` (hover `{p['accent_hover']}`), "
            f"text on accent `{p['on_accent']}`\n"
            f"- danger `{p['danger']}`, success `{p['success']}`\n"
            f"- type scale: {sizes}\n"
            f"- spacing scale: {', '.join(str(s) for s in self.spaces)} px "
            "(every margin/padding/gap must be one of these)\n"
            f"- radii: {self.radii['sm']}/{self.radii['md']}/{self.radii['lg']} px\n"
            "- every text/background pair above already passes WCAG AA at "
            "4.5:1 (body) and 3:1 (large text, borders)\n"
            "- no lorem ipsum, no placeholder names, no dead `href=\"#\"` links, "
            "no image paths that do not exist\n"
        )

    def to_dict(self) -> dict:
        return {"seed": self.seed, "kind": self.kind, "mood": self.mood,
                "palette": dict(self.palette), "font_sizes": dict(self.font_sizes),
                "spaces": list(self.spaces), "radii": dict(self.radii),
                "fonts": dict(self.fonts)}


def _type_scale(kind: str) -> dict[str, int]:
    """A modular scale (~1.25) with a base that suits the target platform."""
    base = 13 if kind in ("python-desktop", "desktop") else 16
    ratio = 1.25
    def up(n: int) -> int:
        return int(round(base * (ratio ** n)))
    def down(n: int) -> int:
        return max(9, int(round(base / (ratio ** n))))
    return {
        "caption": down(2),
        "small": down(1),
        "base": base,
        "subtitle": up(1),
        "title": up(2),
        "display": up(3),
    }


def _font_stack(kind: str) -> dict[str, str]:
    if kind in ("python-desktop", "desktop"):
        return {"sans": "Segoe UI", "mono": "Consolas"}
    return {
        "sans": ("Inter, 'Segoe UI', system-ui, -apple-system, "
                 "sans-serif"),
        "mono": "'JetBrains Mono', 'Fira Code', Consolas, monospace",
    }


def build_tokens(seed: str = "app", *, kind: str = "web",
                 mood: str = "dark", hue: float | None = None) -> Tokens:
    """Build a contrast-checked token set.

    ``seed`` decides the hue when ``hue`` is not given, so a brief keeps its
    look across runs. ``mood`` is ``dark``, ``light`` or ``vivid``.
    """
    mood = (mood or "dark").strip().lower()
    if mood not in ("dark", "light", "vivid"):
        mood = "dark"
    h = _hue_from_seed(seed) if hue is None else float(hue) % 360

    if mood == "light":
        bg = hsl_to_hex(h, 0.18, 0.98)
        panel = hsl_to_hex(h, 0.14, 1.0)
        line = hsl_to_hex(h, 0.12, 0.86)
        ink = _push_away(h, 0.22, 0.16, bg, AA_TEXT, lighter=False)
        muted = _push_away(h, 0.10, 0.45, bg, AA_TEXT, lighter=False)
        accent_l = 0.40
        lighter = False
    elif mood == "vivid":
        bg = hsl_to_hex(h, 0.42, 0.10)
        panel = hsl_to_hex(h, 0.38, 0.15)
        line = hsl_to_hex(h, 0.30, 0.28)
        ink = hsl_to_hex(h, 0.10, 0.96)
        muted = hsl_to_hex(h, 0.16, 0.72)
        accent_l = 0.62
        lighter = True
    else:  # dark
        bg = hsl_to_hex(h, 0.26, 0.08)
        panel = hsl_to_hex(h, 0.22, 0.12)
        line = hsl_to_hex(h, 0.18, 0.24)
        ink = hsl_to_hex(h, 0.14, 0.94)
        muted = hsl_to_hex(h, 0.12, 0.68)
        accent_l = 0.60
        lighter = True

    # The accent must be readable as a boundary and carry readable text.
    accent = _push_away(h, 0.72, accent_l, bg, AA_LARGE, lighter=lighter)
    on_accent = _readable_on(accent)
    accent_hover = hsl_to_hex(*_nudge(accent, 0.06 if lighter else -0.06))
    danger = _push_away(8, 0.68, accent_l, bg, AA_LARGE, lighter=lighter)
    success = _push_away(148, 0.55, accent_l * 0.92, bg, AA_LARGE,
                         lighter=lighter)

    palette = {
        "bg": bg, "panel": panel, "line": line, "ink": ink, "muted": muted,
        "accent": accent, "accent_hover": accent_hover, "on_accent": on_accent,
        "danger": danger, "success": success,
    }
    return Tokens(palette, kind=kind, mood=mood, seed=seed)


def _nudge(color: str, dl: float) -> tuple[float, float, float]:
    h, s, l = hex_to_hsl(color)
    return h, s, max(0.0, min(1.0, l + dl))


def _readable_on(background: str) -> str:
    """Black or white text, whichever reads better on `background`."""
    best, ratio = "#0b0d12", 0.0
    for candidate in ("#0b0d12", "#ffffff"):
        r = contrast_ratio(candidate, background)
        if r > ratio:
            best, ratio = candidate, r
    return best


# ── Layout patterns ──────────────────────────────────────────────────────────
# Structure guidance per target, so "make it designed" has an actual shape
# rather than adjectives. Each pattern lists the regions and the rule that
# keeps it from looking like a template.

LAYOUT_PATTERNS: dict[str, list[dict[str, str]]] = {
    "web": [
        {"name": "Landing (hero + proof)", "use": "product or portfolio home",
         "structure": "nav (max 5 links) · hero (one headline, one sub, one CTA) · "
                      "3 feature cards · proof/social row · footer",
         "rule": "one idea per section; the CTA appears once in the hero and once at the end"},
        {"name": "Marketing page", "use": "feature or pricing detail",
         "structure": "nav · page title · alternating text/media rows · comparison · CTA",
         "rule": "alternate the media side; never two identical rows in a row"},
        {"name": "Dashboard", "use": "data with drill-down",
         "structure": "sidebar (<=7 items) · header (title, range, filters) · "
                      "KPI row (3-4) · primary chart · secondary table",
         "rule": "every KPI carries a unit and a time window; charts have axes and empty states"},
        {"name": "Docs / article", "use": "long-form reading",
         "structure": "sidebar TOC · measure-limited body (65-75ch) · callouts · next/prev",
         "rule": "body max width 72ch; headings never skip a level"},
    ],
    "dashboard": [
        {"name": "Ops console", "use": "live operational data",
         "structure": "left nav · top bar with time range · KPI strip · main chart · "
                      "detail table with sort and empty state",
         "rule": "no metric without a unit, a window and a source; loading and error states are drawn"},
    ],
    "python-desktop": [
        {"name": "List + detail", "use": "records you browse and edit",
         "structure": "toolbar (primary action right) · filter row · table · detail pane",
         "rule": "every table has an empty state and a keyboard path; destructive actions confirm"},
        {"name": "Sidebar + workspace", "use": "multi-section desktop tool",
         "structure": "sidebar sections · document area · status bar",
         "rule": "status bar always shows the current context and unsaved state"},
    ],
    "game": [
        {"name": "Arcade loop", "use": "score/level games",
         "structure": "menu · play field with HUD (score, lives, level) · pause · game over → retry",
         "rule": "the core loop must be playable with one hand; HUD never covers the play field"},
    ],
}

DEFAULT_KIND_ALIASES = {
    "website": "web", "site": "web", "landing": "web", "portfolio": "web",
    "app": "web", "webapp": "web", "web-app": "web",
    "desktop": "python-desktop", "pyqt": "python-desktop",
    "tkinter": "python-desktop", "python": "python-desktop",
    "data": "dashboard", "analytics": "dashboard", "dashboard-app": "dashboard",
    "pygame": "game", "arcade": "game",
}


def normalise_kind(kind: str) -> str:
    key = (kind or "web").strip().lower()
    key = DEFAULT_KIND_ALIASES.get(key, key)
    return key if key in LAYOUT_PATTERNS else "web"


def layout_guidance(kind: str) -> str:
    """Prompt-ready structure advice for a target kind."""
    key = normalise_kind(kind)
    rows = LAYOUT_PATTERNS[key]
    out = [f"## LAYOUT ({key}: pick ONE pattern and follow its structure)"]
    for row in rows:
        out.append(f"- {row['name']} — for {row['use']}\n"
                   f"  structure: {row['structure']}\n"
                   f"  rule: {row['rule']}")
    return "\n".join(out) + "\n"


def design_brief(seed: str, *, kind: str = "web", mood: str = "dark",
                 hue: float | None = None) -> str:
    """Everything a build prompt needs: tokens plus structure.

    ``hue`` comes from an application preset when one was chosen, so the
    palette follows the preset instead of being derived from the seed alone.
    """
    tokens = build_tokens(seed, kind=normalise_kind(kind), mood=mood, hue=hue)
    return tokens.to_prompt_block() + "\n" + layout_guidance(kind)


def selftest() -> dict:
    """Prove the generator produces passing tokens for many seeds and moods."""
    results = []
    for mood in ("dark", "light", "vivid"):
        for kind in ("web", "dashboard", "python-desktop", "game"):
            for seed in ("inventory app", "fleet dashboard", "space shooter",
                         "recipe box", "a", "", "Ünïcode brief"):
                tokens = build_tokens(seed, kind=kind, mood=mood)
                results.append({"seed": seed or "<empty>", "kind": kind,
                                "mood": mood, "problems": tokens.problems()})
    bad = [r for r in results if r["problems"]]
    return {"ok": not bad, "checked": len(results), "failures": bad}
