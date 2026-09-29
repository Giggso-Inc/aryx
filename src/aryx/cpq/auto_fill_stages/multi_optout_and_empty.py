"""Two multi-select no-value fallbacks: the menu-declared opt-out option,
and the confirmed-optional "select nothing is the answer" case.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.

Each returns True when it fired, so the caller stops there -- the
original ``elif`` chain's first-match-wins semantics. Necessary here:
the optional-empty branch's condition does NOT negate the opt-out
branch's, so both could be true for one attr and only the first may
run.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.engine import (
    _no_real_fill_justification,
    _sole_opt_out_option,
    _valid,
)
from aryx.cpq.model_policy import (
    resolve_blind_fill_risk_accepted_membership,
    resolve_optional_empty_fill_membership,
)

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def try_multi_opt_out(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> bool:
    """Fill the menu's own explicit opt-out option. True if filled."""
    if (
        attr.select_type == "multi" and not attr.required
        and state.vn not in scope.grid_selector_vns
        and _no_real_fill_justification(attr, scope.rec_by_target)
        and not resolve_blind_fill_risk_accepted_membership(
            state.vn, ctx.filled.get("productSelectionProduct_all", ""),
            scope.workspace_id, scope.catalog_prefix, ctx.dt_cache,
        )
        and (opt_out_match := _sole_opt_out_option(
            [o for o in attr.options if _valid(o.item_value)]
        ))
    ):
        # Same "the menu itself declares a safe opt-out" case as
        # the single-select branch above, just for multi-select's
        # separate fallback (valid_opts isn't reliably in scope
        # here -- see the sibling elif's own comment on that).
        ctx.filled_multi[state.vn] = [opt_out_match.item_value]
        ctx.display_filled[state.vn] = opt_out_match.display_name
        ctx.sources.setdefault(state.vn, "opt_out_default")
        state.filled_multi_now = True
        return True
    return False


def try_multi_optional_empty(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> bool:
    """Fill a confirmed-optional multi with the empty selection."""
    # CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T6 Phase 3: the membership
    # check is resolved through model_policy for the session's actual CPQ
    # model, falling back to the hardcoded _OPTIONAL_EMPTY_FILL_ACCEPTED_
    # VNS constant when resolution is unavailable. This started as a
    # shadow-only, log-only comparison (pilot follow-up) and became real
    # once wired here directly -- see resolve_optional_empty_fill_
    # membership's own docstring for the gate/fallback contract.
    if (
        attr.select_type == "multi" and not attr.required
        and state.vn not in scope.grid_selector_vns
        and resolve_optional_empty_fill_membership(
            state.vn, ctx.filled.get("productSelectionProduct_all", ""),
            scope.workspace_id, scope.catalog_prefix, ctx.dt_cache,
        )
        and state.allowed_for_attr is None
    ):
        # Confirmed genuinely optional (Attrsequence: 0 Required
        # rows) with no menu-declared opt-out option for
        # _sole_opt_out_option to find -- "select nothing" is
        # itself the real, valid answer here, distinct from the
        # blind-pick-one-real-option fallback a few lines below.
        # `allowed_for_attr is None` (truly unconstrained) guards
        # this from ever overriding a REAL active constraint's own
        # narrowed set -- a constrained-but-ambiguous case for one
        # of these three attrs must still select-all from the
        # narrowed candidates via the sibling mechanism upstream,
        # never resolve to empty just because the attr's name is
        # in this allowlist (confirmed live: without this guard,
        # this branch wrongly intercepted promoApplicationServices_
        # astro's own constrained-and-ambiguous regression test).
        ctx.filled_multi[state.vn] = []
        ctx.display_filled[state.vn] = "(none)"
        ctx.sources.setdefault(state.vn, "optional_empty")
        state.filled_multi_now = True
        return True
    return False
