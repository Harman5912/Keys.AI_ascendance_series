"""
crown_code — Crown Code v2 engine package for Keys.AI.

Feature-flag entry point:
    CROWN_ENGINE=legacy   →  use original CrownBridge (headless.js subprocess)
    CROWN_ENGINE=v2       →  use new Python-native v2 engine
    (default: legacy, so rollback is one env-var change)
"""
from __future__ import annotations

import os

ENGINE = os.environ.get("CROWN_ENGINE", "legacy").lower().strip()

__all__ = ["ENGINE"]
