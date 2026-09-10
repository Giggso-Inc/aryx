"""Grid-quantity reply recognition -- deciding whether a pending attr is
one of the per-option quantity companions, and parsing its answer (Phase 4
step 3 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless and purely
functional -- no ``CpqEngine`` instance needed.
"""

from __future__ import annotations

from aryx.cpq.engine import (
    _GRID_QUANTITY_SKIP_RE,
    _GRID_QUANTITY_WORD_NUMBERS,
    _parse_grid_quantity_dozen_phrase,
)
from aryx.cpq.grid_quantity.links import resolve_array_grid_links
from aryx.cpq.state import ConfigAttr


def is_grid_quantity_attr(attr: ConfigAttr, attrs: list[ConfigAttr]) -> bool:
    """True when `attr` is one of `resolve_array_grid_links`' hidden
    per-option quantity companions (any selector's item_map value) —
    used to gate the skip/zero reply parsing below to exactly the
    upfront-flow's own quantity attrs, never an ordinary free-text
    field."""
    links = resolve_array_grid_links(attrs)
    return any(
        attr.variable_name in item_map.values() for item_map in links.values()
    )


def parse_grid_quantity_reply(text: str) -> str | None:
    """Parse a reply to one grid-selector option's upfront quantity
    question (2026-08-26, explicit product decision): "skip" or a bare
    "0" both mean the option isn't included — stored as the literal
    "0" so it still appears in the final payload (a real, confirmed
    customer decision, not an unanswered gap) — and a plain whole
    number is that option's quantity.

    2026-08-27 follow-up: also recognizes a small, fixed vocabulary of
    natural-language quantities — spelled-out numbers ("three" -> 3)
    and the "dozen" family ("a dozen" -> 12, "half a dozen" -> 6, "2
    dozen"/"two dozen" -> 24) — converting each to its digit string.
    Deliberately NOT a general NLP number parser (see
    _GRID_QUANTITY_WORD_NUMBERS' own comment); a negative quantity
    ("-5", "minus 6") is intentionally never recognized here — a
    negative mount count has no real business meaning.

    Returns None for anything else, letting the caller fall back to
    its normal answer handling rather than guessing.
    """
    t = text.strip()
    if _GRID_QUANTITY_SKIP_RE.match(t):
        return "0"
    if t.isdigit():
        return t
    tl = t.lower()
    if tl in _GRID_QUANTITY_WORD_NUMBERS:
        return str(_GRID_QUANTITY_WORD_NUMBERS[tl])
    dozen_val = _parse_grid_quantity_dozen_phrase(t)
    if dozen_val is not None:
        return str(dozen_val)
    return None
