"""Tier 0c -- hidden attrs only ever take their own XML default_value.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.engine import _valid

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def stage_hidden(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Fill a hidden attr from its literal default_value, then stop."""
    if state.done:
        return
    if attr.hidden:
        # Never asked, never NL-hint-matched, never blind-first-picked
        # — a hidden attr only ever gets its own XML default_value
        # (BML scripts elsewhere may reference it), or is left out of
        # `filled` entirely if it has none. Never enters `pending`.
        # Pointer-defaults are NOT literals — resolved (or left
        # unfilled) by the post-pass below, never written verbatim.
        if _valid(attr.default_value) and not scope.is_pointer_default(attr):
            fill_log.log_write(ctx, attr, state.vn, attr.default_value, attr.default_value,
                               "default", "tier0_hidden")
            ctx.filled[state.vn] = attr.default_value
            ctx.display_filled[state.vn] = next(
                (o.display_name for o in attr.options
                 if o.item_value == attr.default_value),
                attr.default_value,
            )
            ctx.sources.setdefault(state.vn, "default")
        else:
            fill_log.log_pruned(state.vn, "HIDDEN_NO_LITERAL_DEFAULT", "stage_hidden", state="hidden")
        state.done = True
        return
