"""The last resort -- ask (append to ``ctx.pending``) when no layout map
is loaded, or the layout shows this attr and no data table anywhere
governs it.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.auto_fill_stages.state import AttrResolution

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def try_final_pending(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> bool:
    """Append this attr to `ctx.pending`. True if this branch matched."""
    if (
        scope.display_order is None
        # docs/CPQ_DATA_TABLE_GOVERNED_LAYOUT_VISIBILITY_GAP_
        # PLAN_2026_08_10.md: `vn in display_order and` added --
        # this was the THIRD, dominant instance of the same gap
        # (confirmed live: backupPTT_astro/rFIDRFIDEquipped_
        # astro/cableDataCable_astro have zero real attrSequence
        # coverage for ANY base model, so _dt_never_governed_
        # anywhere is True for them regardless of layout). That
        # safety net exists to never silently drop an attr the
        # catalog tracks nowhere AND the layout gives no
        # guidance on either -- but when the layout EXPLICITLY
        # hides an attr, that is not silence, it is a real
        # instruction, and it must win over an "unknown, ask to
        # be safe" fallback the same way it wins everywhere
        # else. No behavior change when no layout map is loaded
        # or the attr is layout-visible. This branch is now only
        # reached by attrs with ZERO rule governance at all
        # (Group 2's blind-pick above already claims every
        # rule-governed case with a real option to pick).
        or (state.vn in scope.display_order and scope.dt_never_governed_anywhere(state.vn))
    ):
        ctx.pending.append(attr)
        fill_log.log_decision(state.vn, "ask_final_pending", "pending", "FINAL_ASK")
        return True
    fill_log.log_decision(state.vn, "ask_final_pending", "left_open", "LAYOUT_HIDDEN_OR_GOVERNED_ELSEWHERE")
    return False
