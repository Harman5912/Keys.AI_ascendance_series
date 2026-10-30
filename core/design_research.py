"""Derive a design from real collected material, not from adjectives.

The research browser already saves genuine screenshots and images to disk, with
their source URLs and licence status. This module turns that material into the
two things a build needs: a palette whose hue comes from the reference the user
actually pointed at, and a provenance record saying which file it came from.

The rule this enforces is narrow and honest: **the hue is sampled from pixels**.
It does not claim to have understood a design, reproduced a layout, or judged
whether the reference is good. Everything except the hue still comes from
``core.design_system``, which guarantees the resulting pairs pass WCAG.
"""

from __future__ import annotations

from pathlib import Path

from core.design_system import Tokens, build_tokens, hex_to_hsl


def sample_colours(path: str | Path, count: int = 6) -> list[str]:
    """Dominant colours of an image, as hex, from its actual pixels.

    Quantised on a downscaled copy — the same technique the research browser
    uses for its own palettes. Returns an empty list when Pillow cannot read the
    file, because a failed read must not look like a design decision.
    """
    try:
        from PIL import Image

        with Image.open(path) as image:
            small = image.convert("RGB").resize((80, 80))
            quantised = small.quantize(colors=count)
            table = quantised.getpalette() or []
            out: list[str] = []
            for _count, index in sorted(quantised.getcolors() or [], reverse=True):
                base = index * 3
                if base + 2 >= len(table):
                    continue
                hexcode = "#{:02x}{:02x}{:02x}".format(*table[base:base + 3])
                if hexcode not in out:
                    out.append(hexcode)
                if len(out) >= count:
                    break
            return out
    except Exception:
        return []


def hue_from_colours(colours: list[str]) -> float | None:
    """The hue of the most strongly coloured sample, or None if all are grey.

    Saturation, not luminance, decides: a reference's identity is its colour,
    and near-grey pixels (text, chrome, whitespace) carry no hue worth copying.
    """
    best_hue: float | None = None
    best_sat = 0.12               # below this a pixel is effectively grey
    for colour in colours:
        try:
            hue, saturation, lightness = hex_to_hsl(colour)
        except ValueError:
            continue
        if saturation < best_sat or lightness < 0.05 or lightness > 0.95:
            continue
        best_sat, best_hue = saturation, hue
    return best_hue


def tokens_from_research(
        images: list[str | Path], *, seed: str = "", kind: str = "web",
        mood: str = "dark") -> tuple[Tokens, dict]:
    """Build tokens whose hue is taken from the collected images.

    Returns ``(tokens, provenance)``. When no image yields a usable hue the
    tokens fall back to the seed-derived palette and provenance says so — it
    never silently pretends the reference was used.
    """
    usable: list[dict] = []
    collected: list[str] = []
    for raw in images or []:
        path = Path(raw)
        if not path.is_file():
            continue
        colours = sample_colours(path)
        if not colours:
            continue
        collected.extend(colours)
        usable.append({"file": str(path), "colours": colours})

    hue = hue_from_colours(collected)
    tokens = build_tokens(seed or "build", kind=kind, mood=mood, hue=hue)
    provenance = {
        "images": usable,
        "sampled": len(collected),
        "hue": round(hue, 1) if hue is not None else None,
        "source": "reference images" if hue is not None else "brief (no usable hue found)",
    }
    return tokens, provenance


def design_research_brief(images: list[str | Path], *, seed: str = "",
                          kind: str = "web", mood: str = "dark",
                          notes: str = "") -> str:
    """Prompt-ready design block derived from collected references."""
    if not images:
        return ""
    tokens, provenance = tokens_from_research(
        images, seed=seed, kind=kind, mood=mood)

    lines = [tokens.to_prompt_block()]
    lines.append("## WHERE THESE COLOURS CAME FROM")
    if provenance["hue"] is None:
        lines.append("- No usable colour was found in the supplied references, so "
                     "the palette comes from the brief instead. Say so if asked.")
    else:
        lines.append(f"- Accent hue {provenance['hue']}° sampled from "
                     f"{len(provenance['images'])} collected image(s):")
        for item in provenance["images"][:5]:
            lines.append(f"  - `{item['file']}` → {', '.join(item['colours'][:4])}")
        lines.append("- Copy the *feel* (hue, contrast, density). Do not copy the "
                     "reference's layout, text or assets.")
    if notes:
        lines.append(f"- Reference notes: {notes.strip()[:600]}")
    return "\n".join(lines) + "\n"


def selftest() -> dict:
    """Prove the sampler reads pixels and the resulting tokens pass contrast."""
    import tempfile

    from PIL import Image

    results = []
    for name, rgb, expected in (("blue", (47, 111, 237), (200, 260)),
                                ("orange", (232, 96, 60), (0, 40)),
                                ("grey", (128, 128, 128), None)):
        path = Path(tempfile.mkdtemp(prefix="design_ref_")) / f"{name}.png"
        Image.new("RGB", (40, 40), rgb).save(path)
        tokens, prov = tokens_from_research([path], seed="t", kind="web")
        hue_ok = (prov["hue"] is None if expected is None
                  else expected[0] <= prov["hue"] <= expected[1])
        results.append({"reference": name, "hue": prov["hue"],
                        "hue_ok": hue_ok, "problems": tokens.problems(),
                        "source": prov["source"]})
    bad = [r for r in results if not r["hue_ok"] or r["problems"]]
    return {"ok": not bad, "checked": len(results), "failures": bad,
            "results": results}
