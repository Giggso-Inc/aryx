"""Tier 6 (head) -- first four branches of the governed single-select
final chain: satisfied recommendation, Data Table match,
``_NEVER_GUESS_SCRIPT_GOVERNED``, constraint-confirmed default_value.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.

Returns True when one of its branches matched, so the caller only
runs the tail chain when the head matched nothing -- exactly the
first-match-wins semantics of the original single ``elif`` chain.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.engine import (
    _NEVER_GUESS_SCRIPT_GOVERNED,
    _valid,
)

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def single_chain_head(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> bool:
    """Try the four evidence-backed branches. True if one matched."""
    # Check for an already-satisfied recommendation before
    # the blind first-by-order pick below claims this attr
    # (see docstring — apply_recommendation_rules() runs
    # AFTER this method in evaluate_rules_loop and never
    # revisits an attr already in `filled`).
    rec_match = (
        scope.satisfied_recommendation(attr, state.valid_opts)
        if scope.rec_by_target else None
    )
    if rec_match:
        state.value, state.display, state.fired_rule_name = rec_match
        state.source = "rule"
    elif (
        dt_match := engine._resolve_via_data_tables(
            state.vn, ctx.filled, state.valid_opts, scope.workspace_id, scope.catalog_prefix, ctx.dt_cache,
        )
    ):
        # This attr is governed (some rule targets it)
        # but no active constraint narrowed it here —
        # the governing rule is either script-based and
        # just failed to resolve, or never fired at all.
        # Before falling to "no recommendation applies"
        # (_NEVER_GUESS_SCRIPT_GOVERNED) or a blind
        # first-by-order guess, try the real ingested
        # Data Table source (§11-§12 of the proof doc) —
        # a different, catalog-wide data source than the
        # script/rule evaluation that just failed, not a
        # second guess at the same one. Only ever fills
        # when exactly one real value resolves (see
        # _resolve_via_data_tables); a no-op (None) when
        # the caller didn't pass workspace_id.
        state.value = dt_match.item_value
        state.display = dt_match.display_name
        state.source = "data_table"
    elif state.vn in _NEVER_GUESS_SCRIPT_GOVERNED:
        # This attr's only governing rule is script-based
        # and just failed to resolve to a value above —
        # confirmed live to legitimately mean "no
        # recommendation applies" for this specific attr,
        # not "unknown, guess anyway". Falls through to
        # pending/ungoverned handling instead of guessing.
        pass
    elif (
        scope.display_order is not None
        and state.allowed_for_attr is not None
        and _valid(attr.default_value)
    ):
        # §2g (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md):
        # narrow carve-out to §2f's skip below — an active
        # constraint (allowed_for_attr is not None) means
        # this attr's default_value has been CONFIRMED
        # valid for this exact product/configuration right
        # now, not just present in the catalog in the
        # abstract (the bare-default case §2d/§2f still
        # skip). Live-verified: APX NEXT Single Band's
        # Frequency Bands (UHF/VHF/700/800 MHz, catalog
        # default "700/800 MHZ") and Antenna Type
        # (Whip/No Antenna, catalog default "WHIP APX
        # NEXT") both survive their own active constraint.
        # Case-insensitive match: the constraint rule's own
        # `allowed_values` list and the menu's real
        # item_value casing aren't guaranteed to agree
        # character-for-character (confirmed live — same
        # "700/800 MHz" concept, different case) even
        # though every other exact-string comparison in
        # this file assumes they do; only this new
        # cross-source comparison needs the normalization.
        _default_norm = attr.default_value.strip().upper()
        match = next(
            (o for o in state.valid_opts
             if o.item_value.strip().upper() == _default_norm),
            None,
        )
        if match:
            state.value = match.item_value
            state.display = match.display_name
            state.source = "default"
    else:
        return False
    return True
