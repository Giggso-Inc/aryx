"""Company-level/system "noise" attrs -- auto-default instead of asking.

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


def try_noise_default(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> bool:
    """Auto-default a noise var. True if this branch matched."""
    if engine._is_noise_var(state.vn) and attr.options:
        # Company-level/system attrs (_BM_USER_CURRENCY, _BM_USER_
        # LANGUAGE, _BM_USER_NUMBER_FORMAT, ...) are already excluded
        # from the final payload by _is_noise_var (build_payload) —
        # asking about them in conversation is inconsistent with that
        # (confirmed live: these got asked, with duplicate options,
        # right before a bug that never affects the submitted BOM).
        # Auto-default instead of asking: prefer the XML default_value
        # if it's a real option, else first by order — same rule
        # already used for governed single/boolean attrs above.
        valid_opts = [o for o in attr.options if _valid(o.item_value)]
        fallback = next(
            (o for o in valid_opts if o.item_value == attr.default_value),
            valid_opts[0] if valid_opts else None,
        )
        if fallback:
            fill_log.log_write(ctx, attr, state.vn, fallback.item_value, fallback.display_name,
                               "default", "noise_var_default")
            ctx.filled[state.vn] = fallback.item_value
            ctx.display_filled[state.vn] = fallback.display_name
            ctx.sources.setdefault(state.vn, "default")
        else:
            fill_log.log_pruned(state.vn, "NOISE_VAR_NO_VALID_OPTION", "try_noise_default")
        return True
    return False
