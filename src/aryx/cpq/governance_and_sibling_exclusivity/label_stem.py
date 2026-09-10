"""``normalized_label_stem`` -- the display-label normalizer the
exclusive-sibling-family detector groups by (Phase 4 step 7 extraction
from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from __future__ import annotations

import re


def normalized_label_stem(label: str) -> str:
    """Lowercase, whitespace-collapsed, singular-ized display label --
    used only to detect whether two attrs are labeled as the "same"
    real-world concept (e.g. "Frequency Bands" and "Frequency Band"),
    never to identify a specific attribute by name."""
    s = re.sub(r"\s+", " ", label.strip().lower())
    if s.endswith("s") and not s.endswith("ss"):
        s = s[:-1]
    return s
