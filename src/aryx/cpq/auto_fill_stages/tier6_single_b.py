"""Tier 6 (tail) -- remaining branches of the governed single-select final
chain: menu-declared opt-out, layout-visible first-by-order,
layout-hidden skip, and the final blind first-by-order pick.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.engine import (
    _BLIND_FILL_RISK_ACCEPTED_VNS,
    _no_real_fill_justification,
    _sole_opt_out_option,
)

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def single_chain_tail(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Run the tail of the chain (head matched nothing)."""
    if (
        _no_real_fill_justification(attr, scope.rec_by_target)
        and state.vn not in _BLIND_FILL_RISK_ACCEPTED_VNS
        and (opt_out_match := _sole_opt_out_option(state.valid_opts))
    ):
        # Nothing justifies picking among the REAL choices
        # here, but the menu itself declares one option as
        # the explicit "nothing needed" answer -- filling
        # that isn't a guess among business alternatives,
        # it's recognizing a choice the catalog already
        # made for the customer. See
        # `_sole_opt_out_option`'s own docstring.
        state.value = opt_out_match.item_value
        state.display = opt_out_match.display_name
        state.source = "opt_out_default"
    elif (
        scope.display_order is not None and state.vn in scope.display_order
        and not (
            _no_real_fill_justification(attr, scope.rec_by_target)
            and state.vn not in _BLIND_FILL_RISK_ACCEPTED_VNS
        )
    ):
        # §2f, superseded by explicit instruction
        # (2026-08-09): governed (some rule targets this
        # attr) but nothing -- no active constraint, no
        # satisfied recommendation, no Data Table match,
        # no confirmed default_value -- resolved a value.
        # Previously skipped entirely (never asked,
        # never defaulted); now picks the first real,
        # catalog-defined eligible option instead of
        # falling through to `pending`, matching the
        # identical first-by-order fallback the sibling
        # `else` branch below already uses when no
        # layout map is loaded. Tagged with a distinct
        # source (not "default") so a later audit or
        # revalidation pass can tell "guessed, nothing
        # to justify it" apart from a genuine catalog
        # default_value match -- same convention the
        # multi-select "is_unconstrained" branch already
        # uses (`source="default_first_available"`).
        #
        # docs/CPQ_DATA_TABLE_GOVERNED_LAYOUT_VISIBILITY_
        # GAP_PLAN_2026_08_10.md: `and vn in display_order`
        # added -- this was the DOMINANT source of the
        # layout-visibility-baseline gap (26 real
        # attributes confirmed live), bigger than the
        # sibling _dt_governed_vns fix in this same file.
        # `display_order is not None` alone only proves a
        # layout map exists, not that THIS attr is in its
        # visible set -- a layout-hidden but rule-governed
        # attr with no other resolution signal was still
        # blind-picked unconditionally. See the `elif`
        # immediately below for the new layout-hidden case.
        state.value = state.valid_opts[0].item_value
        state.display = state.valid_opts[0].display_name
        state.source = "default_first_available"
    elif scope.display_order is not None:
        # Layout map loaded, but this attr isn't in its
        # visible set -- the layout explicitly says never
        # show it. Falls through with no value set, same
        # as any other layout-hidden, unresolved attr
        # (the final ask/skip decision below correctly
        # skips it, since it's neither a decision attr
        # nor a grid selector).
        pass
    elif not (
        _no_real_fill_justification(attr, scope.rec_by_target)
        and state.vn not in _BLIND_FILL_RISK_ACCEPTED_VNS
    ):
        # single/boolean, 2+ options, no default: first by
        # menu order — well-defined for boolean (only two
        # states) and safe here because a rule REQUIRES this
        # attr to be resolved for the cascade to proceed.
        state.value = state.valid_opts[0].item_value
        state.display = state.valid_opts[0].display_name
        state.source = state.governed_source
    # else: nothing above (rec/data-table/confirmed-
    # default) justified a value for this specific,
    # confirmed-no-real-basis attr -- leave unset
    # rather than guess first-by-order, same principle
    # as the multi-select guard below.
