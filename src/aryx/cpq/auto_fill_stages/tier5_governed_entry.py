"""Tier 5 -- the rule-governed, non-decision option branch: dispatches to
the multi-select handler, the two deliberate ask-instead-of-guess
``pass`` cases, or the single-select final chain.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages import tier5_governed_multi
from aryx.cpq.auto_fill_stages import tier6_single_a
from aryx.cpq.auto_fill_stages import tier6_single_b
from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.auto_fill_stages.state import AttrResolution

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def governed_entry(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Dispatch the governed/non-decision option case."""
    if (
        state.is_governed and not state.is_decision_attr and state.valid_opts
        # skip_always_ask only means "the native UI never shows
        # a question for this" — it must NOT also unlock the
        # blind first-by-order fallback below for
        # productSelectionProduct_all specifically. That list is
        # shared/catalog-wide (hundreds of unrelated product
        # codes across every family), so first-by-order silently
        # picks a foreign product's code (confirmed live: SVX
        # session filled "APX6500" this way). Without this guard,
        # suppressing the ask (is_decision_attr -> False) directly
        # re-opens the exact failure this attr's is_decision_attr
        # branch above exists to prevent.
        and not (state.vn == "productSelectionProduct_all"
                 and state.vn in (scope.skip_always_ask or ()))
        # A real customer decision that a cascade just cleared
        # deserves to be re-asked, not silently re-guessed — same
        # "never blind-fill a real decision" principle as
        # productSelectionProduct_all above, generalized to any
        # attr whose cascade-dropped value was filled_source
        # "user" (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 4).
        and attr.entity_id not in ctx.user_answered_dropped_ids
    ):
        if attr.select_type == "multi":
            tier5_governed_multi.governed_multi(engine, attr, ctx, scope, state)
        elif state.governed_source == "optional" and attr.entity_id in scope.conflicted_optional_ids:
            # This attr shares a real option value with another
            # "optional"-tier attr — first-by-order would silently
            # pick a competing value for what's very likely the
            # same hardware/accessory slot (§ surveillance-package
            # double-fill). Ask instead of guessing which one wins.
            fill_log.log_decision(state.vn, "governed_entry", "left_open", "OPTIONAL_DATA_TABLE_CONFLICT")
            pass
        elif state.vn in (scope.negated_vns or ()):
            # The customer explicitly negated this attr's concept
            # (e.g. "exclude any multikey capability") but no
            # option text let extract_catalog_hints resolve which
            # specific option that means — first-by-order has no
            # way to know either, and confirmed live it picked
            # the literal opposite ("MULTIKEY"). Ask instead.
            fill_log.log_decision(state.vn, "governed_entry", "left_open", "NEGATED_BY_CUSTOMER")
            pass
        else:
            if not tier6_single_a.single_chain_head(engine, attr, ctx, scope, state):
                tier6_single_b.single_chain_tail(engine, attr, ctx, scope, state)
    else:
        fill_log.log_decision(state.vn, "governed_entry", "not_governed_path", "NOT_GOVERNED_OR_DECISION_OR_NO_OPTIONS", is_governed=state.is_governed, valid_opt_count=len(state.valid_opts))
