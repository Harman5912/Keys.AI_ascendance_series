"""core/site_studio — multi-studio website engine for Crown Code.

Ten independent design systems, one content model. The live site pipeline uses
``plan_to_content`` + ``choose_studio`` + ``render_site`` so every build gets a
layout and motion language chosen for its brief, not one shared template.
"""

from __future__ import annotations

from .content import SAMPLE_SITES, all_samples, choose_studio, plan_to_content, score_studios
from .render import render_gallery, render_site
from .themes import ORDER, STUDIOS, studio, studio_css

__all__ = [
    "SAMPLE_SITES", "all_samples", "choose_studio", "plan_to_content",
    "score_studios", "render_gallery", "render_site", "ORDER", "STUDIOS",
    "studio", "studio_css",
]
