"""Array-grid / per-option-quantity helper cluster (Phase 4 step 3
extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Re-exports every function so ``from aryx.cpq.grid_quantity import <name>``
works regardless of which submodule actually defines it.
"""

from __future__ import annotations

from aryx.cpq.grid_quantity.append import append_pending_grid_quantities
from aryx.cpq.grid_quantity.finalize import _finalize_grid_selections_from_quantities
from aryx.cpq.grid_quantity.links import (
    array_grid_controls_in_play,
    resolve_array_grid_links,
)
from aryx.cpq.grid_quantity.pending import resolve_pending_grid_quantities
from aryx.cpq.grid_quantity.replies import (
    is_grid_quantity_attr,
    parse_grid_quantity_reply,
)
from aryx.cpq.grid_quantity.selector_options import (
    grid_selector_remaining_options,
    unresolved_grid_quantity_options,
)

__all__ = [
    "_finalize_grid_selections_from_quantities",
    "append_pending_grid_quantities",
    "array_grid_controls_in_play",
    "grid_selector_remaining_options",
    "is_grid_quantity_attr",
    "parse_grid_quantity_reply",
    "resolve_array_grid_links",
    "resolve_pending_grid_quantities",
    "unresolved_grid_quantity_options",
]
