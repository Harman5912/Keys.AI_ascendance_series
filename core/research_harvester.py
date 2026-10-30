"""
core/research_harvester.py — Autonomous Research Browser & Asset Harvester.

Harvests documentation, design references, vector icons, real images, and color
palettes into the target workspace BEFORE Crown Code writes a single line of code.

Pipeline Step 2:
  Task & Requirements -> Research Browser Crawl -> Asset Harvest -> Research Dossier
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from core.design_system import build_tokens, hex_to_hsl
from core.site_images import search as search_images, fetch_for

# Standard clean UI vector SVG definitions (Lucide / Feather compatible)
# Guaranteed to be offline-safe, lightweight, and valid SVGs.
COMMON_SVG_ICONS: dict[str, str] = {
    "dashboard": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/></svg>',
    "chart": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>',
    "wallet": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/></svg>',
    "settings": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>',
    "search": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>',
    "user": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
    "bell": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>',
    "database": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/></svg>',
    "check": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    "alert": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>',
    "refresh": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>',
    "arrow-up-right": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 7h10v10"/><path d="M7 17 17 7"/></svg>',
    "arrow-down-right": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m7 7 10 10"/><path d="M17 7v10H7"/></svg>',
    "gamepad": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="6" x2="10" y1="12" y2="12"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="15" x2="15.01" y1="13" y2="13"/><line x1="18" x2="18.01" y1="11" y2="11"/><rect width="20" height="12" x="2" y="6" rx="6"/></svg>',
    "play": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 3 20 12 6 21 6 3"/></svg>',
    "pause": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="14" y="4" width="4" height="16" rx="1"/><rect x="6" y="4" width="4" height="16" rx="1"/></svg>',
    "trophy": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/></svg>',
    "heart": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>',
    "smartphone": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/></svg>',
    "code": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
    "github": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-7-2"/></svg>',
    "external-link": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>',
    "mail": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>',
    "briefcase": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/><rect width="20" height="14" x="2" y="6" rx="2"/></svg>',
    "terminal": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/></svg>',
    "globe": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/></svg>',
    "layers": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/></svg>',
}


class ResearchHarvester:
    """Orchestrates Stage 2: Deep Research & Asset Harvesting."""

    def __init__(self, workspace: Path, player=None):
        self.workspace = Path(workspace).resolve()
        self.player = player
        self.assets_dir = self.workspace / "assets"
        self.icons_dir = self.assets_dir / "icons"
        self.images_dir = self.assets_dir / "images"
        self.refs_dir = self.workspace / "references"
        self.screenshots_dir = self.refs_dir / "screenshots"

        # Ensure directory structure exists
        for d in (self.icons_dir, self.images_dir, self.screenshots_dir):
            d.mkdir(parents=True, exist_ok=True)

    def _notify(self, icon: str, message: str) -> None:
        if self.player:
            try:
                fn = getattr(self.player, "creation_event", None)
                if fn:
                    fn(icon, message)
            except Exception:
                pass
        try:
            print(f"[ResearchHarvester] {icon} {message}")
        except Exception:
            try:
                safe_msg = f"[ResearchHarvester] {message}".encode("ascii", errors="replace").decode("ascii")
                print(safe_msg)
            except Exception:
                pass

    def harvest_icons(self, task: str) -> list[str]:
        """Deploy crisp SVG vector icons matching the domain."""
        written = []
        task_lower = task.lower()
        # Always supply core layout icons
        keys = ["dashboard", "settings", "search", "user", "bell", "check", "alert", "refresh"]

        if any(w in task_lower for w in ("crypto", "finance", "money", "wallet", "trade", "market")):
            keys.extend(["wallet", "chart", "arrow-up-right", "arrow-down-right"])
        if any(w in task_lower for w in ("database", "sql", "data", "store", "records")):
            keys.append("database")
        if any(w in task_lower for w in ("chart", "graph", "analytics", "stats", "kpi")):
            keys.extend(["chart", "arrow-up-right", "arrow-down-right"])
        if any(w in task_lower for w in ("game", "pygame", "arcade", "shooter", "snake", "pong")):
            keys.extend(["gamepad", "play", "pause", "trophy", "heart"])
        if any(w in task_lower for w in ("android", "mobile", "apk", "kotlin", "flutter")):
            keys.extend(["smartphone", "bell", "settings", "check", "search"])
        if any(w in task_lower for w in ("portfolio", "developer", "engineer", "architect", "harman", "website", "resume", "cv")):
            keys.extend(["code", "github", "external-link", "mail", "briefcase", "terminal", "globe", "layers", "user", "check", "arrow-up-right"])

        for key in set(keys):
            svg_content = COMMON_SVG_ICONS.get(key)
            if svg_content:
                path = self.icons_dir / f"{key}.svg"
                path.write_text(svg_content.strip() + "\n", encoding="utf-8")
                written.append(f"assets/icons/{key}.svg")

        self._notify("🎨", f"Saved {len(written)} vector SVG icons to assets/icons/")
        return written

    def harvest_images(self, task: str, count: int = 3) -> list[dict]:
        """Harvest authentic royalty-free images for the domain."""
        # Derive keyword for image search
        words = re.findall(r"\b[a-zA-Z]{4,15}\b", task)
        stop_words = {"create", "build", "make", "dashboard", "application", "website",
                      "proper", "please", "using", "with", "from", "that", "this"}
        candidates = [w for w in words if w.lower() not in stop_words]
        if any(w in task.lower() for w in ("game", "pygame", "arcade", "shooter")):
            query = "arcade video game"
        elif any(w in task.lower() for w in ("android", "mobile app", "kotlin")):
            query = "mobile app interface"
        elif any(w in task.lower() for w in ("portfolio", "developer", "engineer", "architect", "harman")):
            query = "software developer workspace technology"
        else:
            query = " ".join(candidates[:2]) if candidates else "technology abstract"

        self._notify("🌐", f"Researching image assets for query: '{query}'")
        try:
            downloaded = fetch_for(query, self.images_dir, count=count)
            self._notify("📸", f"Collected {len(downloaded)} real images to assets/images/")
            return downloaded
        except Exception as exc:
            self._notify("!", f"Image harvest note: {exc} (fallback clean styling used)")
            return []

    def harvest_design_tokens(self, task: str, image_paths: list[Path] | None = None) -> dict[str, Any]:
        """Extract dominant colors and generate WCAG-compliant design tokens."""
        # If images were collected, sample from their actual pixels
        hue = None
        if image_paths:
            for p in image_paths:
                if p.exists() and p.suffix.lower() in (".jpg", ".jpeg", ".png"):
                    try:
                        from core.design_research import sample_colours, hue_from_colours
                        cols = sample_colours(p, count=5)
                        h = hue_from_colours(cols)
                        if h is not None:
                            hue = h
                            break
                    except Exception:
                        pass

        # Build full token dictionary
        tokens_obj = build_tokens(seed=task, kind="web", mood="dark", hue=hue)
        pal = tokens_obj.palette
        tokens_dict = {
            "primary": pal.get("accent", "#3B82F6"),
            "primary_contrast": pal.get("on_accent", "#FFFFFF"),
            "background": pal.get("bg", "#0F172A"),
            "surface": pal.get("panel", "#1E293B"),
            "text": pal.get("ink", "#F8FAFC"),
            "text_muted": pal.get("muted", "#94A3B8"),
            "border": pal.get("line", "#334155"),
            "accent": pal.get("accent", "#3B82F6"),
            "font_family": "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            "mono_family": "'Fira Code', 'Courier New', monospace",
        }

        token_file = self.assets_dir / "design_tokens.json"
        token_file.write_text(json.dumps(tokens_dict, indent=2), encoding="utf-8")
        self._notify("✨", f"Generated design tokens (primary: {tokens_dict['primary']}) in assets/design_tokens.json")
        return tokens_dict

    def run_browser_inspection(self, task: str) -> list[str]:
        """Open research browser and inspect documentation / references if available."""
        # Check if research step is usable
        sources = []
        try:
            from core.research_step import run_ResearchThroughBrowser
            class Ctx:
                def __init__(self, ws, t, p):
                    self.workspace = ws
                    self.task = {"request": t}
                    self.ui = p
                    self.log = lambda m: None
                    self.check_cancel = lambda: False

            ctx = Ctx(self.workspace, task, self.player)
            res = run_ResearchThroughBrowser(ctx)
            if res.get("ok"):
                for art in res.get("artifacts", []):
                    sources.append(str(art))
                self._notify("🔍", f"Research browser gathered {len(sources)} source references")
        except Exception as exc:
            # Headless or standalone execution gracefully skips GUI browser inspection
            pass
        return sources

    def compile_dossier(self, task: str, stack: str, icons: list[str],
                        images: list[dict], tokens: dict[str, Any],
                        sources: list[str]) -> Path:
        """Synthesize the complete RESEARCH_DOSSIER.md for Crown Code."""
        dossier_path = self.refs_dir / "RESEARCH_DOSSIER.md"

        img_list_md = "\n".join(
            f"- `{img.get('filename')}`: {img.get('title')} (License: {img.get('license', 'CC')})"
            for img in images
        ) if images else "- No external images required (pure SVG & vector styling)."

        icon_list_md = "\n".join(f"- `{icon}`" for icon in icons)

        content = f"""# Research Dossier & Asset Blueprint

## Task Overview
{task}

## Technical Stack & Guidance
- Recommended Stack: **{stack}**
- Architecture Mode: Autonomous Execution with Local Model Fortifications

## Collected Design Tokens
- Primary Color: `{tokens.get('primary')}`
- Primary Contrast: `{tokens.get('primary_contrast')}`
- Background: `{tokens.get('background')}`
- Surface / Cards: `{tokens.get('surface')}`
- Text: `{tokens.get('text')}`
- Muted Text: `{tokens.get('text_muted')}`
- Border: `{tokens.get('border')}`

## Local Asset Inventory (Ready for Import)
### Vector Icons (`assets/icons/`)
{icon_list_md}

### Real Images (`assets/images/`)
{img_list_md}

## References & Sources
{chr(10).join(f"- {s}" for s in sources) if sources else "- Official framework documentation and verified local libraries."}
"""
        dossier_path.write_text(content, encoding="utf-8")
        self._notify("📋", f"Compiled research dossier at references/RESEARCH_DOSSIER.md")
        return dossier_path

    def run(self, task: str, stack: str = "") -> dict[str, Any]:
        """Execute full Stage 2 research and asset harvesting."""
        self._notify("🚀", "Starting Autonomous Research Mode...")
        icons = self.harvest_icons(task)
        images = self.harvest_images(task, count=3)

        image_files = [self.images_dir / img["filename"] for img in images if "filename" in img]
        tokens = self.harvest_design_tokens(task, image_files)
        sources = self.run_browser_inspection(task)
        dossier = self.compile_dossier(task, stack or "React + Vite + Tailwind CSS",
                                       icons, images, tokens, sources)

        return {
            "ok": True,
            "dossier": str(dossier),
            "icons": icons,
            "images": [img.get("filename") for img in images],
            "tokens": tokens,
            "sources": sources,
        }
