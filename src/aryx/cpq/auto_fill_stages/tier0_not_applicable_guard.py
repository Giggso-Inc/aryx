"""Tier 0 (first) -- skip and clear attrs confirmed not applicable to the
device resolved from the customer's wording (port of dev-rv-msi #364/#365).

Behind ``cpq_not_applicable_guard_enabled``. One-sided and never-guess: only
removes, only when a device is confidently resolved AND Data Table evidence
shows it never governs the attr. Hardware Version uses its own named check;
other structural anchors (required, Product selector) are never checked. A
customer-confirmed ('user' source) value is NEVER cleared.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aryx.config import get_settings
from aryx.cpq.auto_fill_stages.state import AttrResolution

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr

logger = logging.getLogger(__name__)


def stage_not_applicable_guard(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Skip (and clear any earlier blind fill of) a not-applicable attr."""
    if state.done or not get_settings().cpq_not_applicable_guard_enabled:
        return
    vn = state.vn
    if ctx.sources.get(vn) == "user":
        return  # customer-confirmed value is never cleared
    if engine._is_hardware_version_attr(attr):
        not_applicable = engine._hardware_version_confirmed_not_applicable(
            scope.product_anchor_hint, scope.workspace_id, scope.catalog_prefix,
            ctx.dt_cache,
        )
    elif attr.required or engine._is_product_line_selector(attr):
        return
    else:
        not_applicable = engine._named_attr_confirmed_not_applicable(
            vn, scope.product_anchor_hint, scope.workspace_id,
            scope.catalog_prefix, ctx.dt_cache,
        )
    if not not_applicable:
        return
    if vn in ctx.filled:
        logger.info(
            "cpq: clearing previously blind-filled %r=%r -- confirmed no "
            "concept for this resolved device (hint=%r)",
            vn, ctx.filled[vn], scope.product_anchor_hint,
        )
    ctx.filled.pop(vn, None)
    ctx.display_filled.pop(vn, None)
    ctx.sources.pop(vn, None)
    ctx.filled_multi.pop(vn, None)
    state.done = True
