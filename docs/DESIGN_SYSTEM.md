# Design system and design gate

Two modules, one contract: a build is given concrete tokens, and the finished
project is checked against the same numbers it was given.

```
brief ──► core/design_system.design_brief()  ──► prompt tokens + layout pattern
                                                     │
generated files ──► core/design_check.check_project() ──► pass / fail + reasons
```

## `core/design_system.py`

| Piece | What it produces |
|---|---|
| `build_tokens(seed, kind, mood)` | bg, panel, line, ink, muted, accent, accent_hover, on_accent, danger, success |
| Type scale | modular ~1.25 from a base (16 px web, 13 px desktop) |
| Spacing scale | 4, 8, 12, 16, 24, 32, 48, 64 px |
| Radii | 6 / 8 / 12 px |
| `to_css(":root")` | CSS custom properties |
| `to_qt_theme(title)` | a drop-in `app/theme.py` (ACCENT/BG/PANEL/INK/MUTED/LINE/WARN/GOOD) |
| `to_prompt_block()` | the token list plus the rules, for the build prompt |
| `layout_guidance(kind)` | named layout patterns per target (web, dashboard, python-desktop, game) |

Deterministic: the same brief yields the same palette, which is what makes the
gate reproducible. `hue=` overrides the seed when a colour is specified.

**Contrast.** Every pair is checked before the tokens are returned, using the
WCAG relative-luminance formula. The palette generator walks lightness until
the pair clears its target rather than hoping a hand-picked colour is fine:

- body text on background and on panel — **4.5:1**
- muted text on background and on panel — **4.5:1**
- label on the accent — **4.5:1**
- accent and danger as UI boundaries — **3:1**
- divider visible against panel — 1.15:1 (presence, not readability)

Threshold source, verified against the specification rather than memory:
[WCAG 2.2 SC 1.4.3 Contrast (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
— 4.5:1 for normal text, 3:1 for large text (≥ 18 pt, or ≥ 14 pt bold).

`selftest()` sweeps 84 combinations of seed × kind × mood and asserts none of
them produce a failing pair. It is called from the test suite.

## `core/design_check.py`

Errors (the build must not claim success):

| Code | Caught |
|---|---|
| `contrast` | any text/surface or on-accent/accent pair below AA |
| `placeholder` | lorem ipsum, "your text here", "sample text", TODO/FIXME in visible copy |
| `broken-image` | a local `<img src>` that does not exist on disk |
| `nothing-checked` | no HTML, CSS or theme module to check — an empty pass is not a pass |

Warnings (reported, not blocking): `type-scale` (>8 distinct font sizes),
`spacing-scale` (≥3 values off the 4 px scale), `dead-link` (`href="#"`),
`palette-unverified` (a theme module whose palette is still a template
placeholder), `limit` (file cap reached).

Only `<html>`/`.css` files and `theme.py`/`styles.py` are scanned. Tags,
`<script>`, `<style>` internals and attributes are stripped before copy is
read, so `placeholder="Search stock"` is not mistaken for placeholder text.

## Where it is wired in

- `actions/crown_code.py` appends `design_brief(task, kind=…)` to every build
  brief, choosing the kind from the detected stacks.
- After a build, and only when the workspace actually contains a UI, the gate
  runs. Errors flip the build to not-ok with the first failure quoted in the
  summary and the full list in `design_errors`.
- A crash in the checker is reported as *unverified* (`design gate could not
  run`), not as a failure of the user's project — our bug is not their defect.

## Runtime gate — `design_check.check_rendered(url)`

Source checks cannot see an image that 404s once a server resolves it, or a
script that throws on load. This loads the page in QtWebEngine and reports:

| Error | How it is found |
|---|---|
| `broken-image` | `Array.from(document.images)` filtered by `!complete || naturalWidth === 0` — what the DOM actually thinks |
| `console-error` | uncaught errors plus `console.error`, captured by a `window.onerror` hook injected at `DocumentCreation` |
| `load-failed` | the page never reached `loadFinished` |

It needs a real engine, so it runs where a build is previewed. `crown_code`
calls it after launching a web build: **a broken image fails the build**;
console errors are reported in `runtime_issues` without overriding the
verification that already ran, since an engine quirk should not certify a build
as broken.

## Palettes from real references — `core/design_research.py`

The research browser saves genuine screenshots and images with their source and
licence. `tokens_from_research(paths)` samples the dominant colours from those
pixels, takes the hue of the most saturated one, and builds the token set from
it. Lightness and every other role still come from `design_system`, so the
result is contrast-checked like any other palette.

It claims only what it did: the hue came from pixels. It does not claim to have
understood the reference's layout, and the prompt block says so explicitly
(`Copy the *feel*. Do not copy the reference's layout, text or assets.`). When
no usable hue is found, the provenance records `brief (no usable hue found)`
rather than pretending the reference was used.

## Games

`core/game_builder.py` uses the same tokens (`kind="game"`) for `game/theme.py`,
so a game inherits the contrast-checked palette. Rules live in `game/state.py`
with no pygame import, which is what lets `--selftest` verify them headlessly.

## Honest limits

- The gate reads source. It does not look at a rendered pixel, so it cannot
  judge composition, hierarchy or whether a layout looks good — only that the
  measurable part is correct.
- Contrast is checked on declared colour pairs. A colour set in JavaScript at
  runtime is invisible to it.
- Layout patterns are guidance for the prompt, not a check on the result.
