"""Region-from-country and Base-Model region-allow derivations.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.derive_base_model_pick import derived_base_model_option

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def stage_region_and_base_model(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Derive region from the confirmed country / base model from a
    real per-region ALLOW value."""
    if state.done:
        return
    # Region-from-country derivation: region is a decision-required
    # key (always ask, D2/§Phase M-adjacent) UNLESS the confirmed
    # country resolves to one of this attr's real options — country
    # itself is untouched, still always asked (D1).
    if not state.value and "region" in state.vn_flat and scope.country and attr.options:
        derived = engine.derive_region(scope.country, attr, scope.workspace_id, scope.catalog_prefix, ctx.dt_cache)
        if derived:
            state.value, state.display = derived
            state.source = "country_derived"

    # Base Model region-allow default (see the precompute above) --
    # a real, confirmed per-region ALLOW value from an ingested
    # region-rule-shaped Data Table, not a blind guess. Checked
    # BEFORE the unconditional "basemodel" always-ask anchor above
    # gets to force this to `pending` -- only ever applies when
    # exactly one such value resolved.
    if not state.value and "basemodel" in state.vn_flat and scope.bm_region_allow_value and attr.options:
        match = next(
            (o for o in attr.options if o.item_value == scope.bm_region_allow_value),
            None,
        )
        if match:
            state.value = match.item_value
            state.display = match.display_name
            state.source = "region_allow_default"

    # Port of aryxent D10 (PR 8): no per-region default -- derive the base
    # model from the attrs already known this turn. Flag-gated no-op.
    if not state.value and "basemodel" in state.vn_flat and attr.options:
        derived = derived_base_model_option(
            attr.options, ctx.filled, scope.workspace_id, scope.catalog_prefix, ctx.dt_cache,
            sources=ctx.sources,
        )
        if derived is not None:
            state.value = derived.item_value
            state.display = derived.display_name
            state.source = "derived_from_known_attrs"

    _defer_base_model_question(attr, scope, state)


def _defer_base_model_question(attr: "ConfigAttr", scope: "FillScope", state: AttrResolution) -> None:
    """Base model narrowing (flag): the base model is not asked while an attribute that separates the model's base
    models is still unanswered (the derivation fills it once they are), and a part-number attribute the layout hides
    (its options are not base model codes) is not asked at all."""
    narrowing = scope.base_model_narrowing
    if narrowing is None or state.value or "basemodel" not in state.vn_flat or not attr.options:
        return
    part_number = not any(o.item_value.strip().upper() in narrowing.base_model_codes for o in attr.options)
    if part_number and scope.display_order is not None and state.vn not in scope.display_order:
        fill_log.log_decision(state.vn, "base_model_narrowing", "left_open", "PART_NUMBER_ATTR_LAYOUT_HIDDEN")
        state.done = True
    elif narrowing.ask_first:
        fill_log.log_decision(state.vn, "base_model_narrowing", "left_open", "BASE_MODEL_DEFERRED_TO_DISCRIMINATORS",
                              ask_first=sorted(narrowing.ask_first))
        state.done = True
