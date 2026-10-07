"""One debug line naming what the grid-quantity step removed from / added to a turn's pending list.

ws 1267 (2026-10-07): APX N30 / 4500 turns ended with seven `hidden=1` quantity holders in the open list (conventional /
G-series arrays that have nothing to do with a portable radio). The pending counts only showed the net change, so which
step added them could not be told from the logs.
"""
from __future__ import annotations

from typing import Any

from aryx.raven_log import raven_log, would_log

_MAX_NAMES = 40


def names_before(pending: Any) -> list[str] | None:
    """Variable names of `pending` now, or None when DEBUG is off (so nothing is copied)."""
    if not would_log("DEBUG"):
        return None
    return [str(getattr(a, "variable_name", a)) for a in (pending or [])]


def log_grid_diff(before: list[str] | None, pending: Any) -> None:
    """Debug record of the names the grid step removed and added; never affects the turn."""
    if before is None:
        return
    try:
        after = [str(getattr(a, "variable_name", a)) for a in (pending or [])]
        before_set, after_set = set(before), set(after)          # the pending list can hold ~3,000 names
        removed = [v for v in before if v not in after_set]
        added = [v for v in after if v not in before_set]
        raven_log("DEBUG", "P4", "ask.recompute.grid_diff grid-quantity step changed the pending list", context={
            "selected_option": "changed" if removed or added else "unchanged",
            "available_options": ["changed", "unchanged"], "reason_code": "GRID_QUANTITY_APPEND",
            "removed": removed[:_MAX_NAMES], "added": added[:_MAX_NAMES],
            "removed_count": len(removed), "added_count": len(added)})
    except Exception:  # noqa: BLE001 -- a diagnostic must never change the turn
        return
