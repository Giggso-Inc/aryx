"""``disambiguated_label`` -- announcement-time label disambiguation for
attrs sharing the same raw catalog display_label (Phase 4 step 2
extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless -- needs no
engine-instance callback.
"""

from __future__ import annotations

import re

from aryx.cpq.engine import _ACRONYM_BOUNDARY_RE, _CAMEL_BOUNDARY_RE
from aryx.cpq.state import ConfigAttr


# ── Announcement label disambiguation ──────────────────────────────────────

def disambiguated_label(attr: ConfigAttr, attrs: list[ConfigAttr]) -> str:
    """`attr.display_label`, suffixed to stay unique when 2+ attrs in
    `attrs` share the same raw catalog label.

    Live-confirmed gap (2026-07-28): `serviceType_astro`,
    `serviceTypeRSM_astro`, and `serviceTypeAdditionalDMSCoverage_astro`
    all carry the literal display_label "Service Type" — when a cascade
    turn changes more than one of them (the user's own change plus an
    independently-firing recommendation rule), the customer sees
    multiple identical "Updated **Service Type** → ..." lines that read
    as duplicates/contradictions instead of distinct facts. This is the
    same root cause `_label_collision_for` already disambiguates at
    QUESTION time — this is the ANNOUNCEMENT-time equivalent.

    No catalog field carries a friendly, human grouping name for an
    attr (checked live: the raw ingested JSON has only structural/UI
    codes — "category": "2", not a label) — so the fallback is the
    attr's own variable_name, camelCase/acronym-split into words, with
    the words already present in the shared label removed. E.g.
    "serviceTypeRSM_astro" vs. shared label "Service Type" -> "RSM";
    "serviceTypeAdditionalDMSCoverage_astro" -> "Additional DMS
    Coverage". The catalog suffix (e.g. "_astro") is stripped first —
    it's shared by every attr, never a distinguishing fact. Returns the
    bare label unchanged when a sibling's variable_name has no fragment
    left to distinguish it (e.g. the "plainest" one, whose variable_name
    collapses to the label itself) rather than surface a raw,
    customer-meaningless variable_name.
    """
    label = attr.display_label
    siblings = [a for a in attrs if a.display_label == label]
    if len(siblings) < 2:
        return label
    label_words = {w.lower() for w in re.split(r"[^A-Za-z0-9]+", label) if w}
    # `attr.catalog_prefix` is a different, BM-type-level field (e.g.
    # "ApxNextConfig") — NOT the "_astro"-style suffix variable_names
    # actually carry, so it can't be used to strip that suffix (live-
    # verified: checking it left "astro" un-stripped, leaking as a
    # meaningless "Service Type (astro)"). Instead, derive it: any
    # underscore-part shared by EVERY sibling's variable_name is by
    # definition not a distinguishing fact for one of them — exclude
    # those words the same way label_words are excluded.
    _sibling_parts = [
        {p.lower() for p in s.variable_name.split("_") if p} for s in siblings
    ]
    _shared_parts = set.intersection(*_sibling_parts) if _sibling_parts else set()
    _excluded = label_words | _shared_parts
    for part in attr.variable_name.split("_"):
        if not part or part.lower() in _shared_parts:
            continue
        spaced = _CAMEL_BOUNDARY_RE.sub(r"\1 \2", part)
        spaced = _ACRONYM_BOUNDARY_RE.sub(r"\1 \2", spaced)
        words = [w for w in spaced.split() if w.lower() not in _excluded]
        if words:
            return f"{label} ({' '.join(words)})"
    # No distinguishing fragment left after stripping shared label
    # words and the catalog suffix (this attr's variable_name IS the
    # label, e.g. the plainest sibling among several sharing it) —
    # better to leave it as the bare label than surface a raw,
    # customer-meaningless variable_name fragment.
    return label
