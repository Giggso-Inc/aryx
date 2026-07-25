"""Shared value normalization for cross-column identity comparison.

Used by both the exact-match FK join (fk_edges.link_by_attribute) and the
dynamic value-overlap FK detector (dynamic_fk.py) so a value normalized one
way in detection matches the same way at join time.
"""
from __future__ import annotations


def normalize_value(value: str) -> str:
    """Normalize a raw cell value for cross-column identity comparison.

    Case/whitespace-insensitive, plus leading-zero-aware so a numeric-looking
    code stored as "007" in one source and 7 in another compare equal. Only
    applied to values that are purely digits after stripping, so real
    alphanumeric identifiers (e.g. "DS000E1LA") are never touched.
    """
    v = value.strip().lower()
    if v.isdigit():
        v = v.lstrip("0") or "0"
    return v
