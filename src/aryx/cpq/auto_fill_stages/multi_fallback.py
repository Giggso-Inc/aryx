"""The multi-select final fallback (recommendation / layout-select-all /
default_value / blind pick / empty).

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.rule_trace import rule_trace
from aryx.cpq.auto_fill_stages import multi_fallback_layout
from aryx.cpq.auto_fill_stages import multi_fallback_unconstrained
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.constants import NONE_DISPLAY_PLACEHOLDER
from aryx.cpq.engine import (
    _no_real_fill_justification,
    _valid,
)
from aryx.cpq.model_policy import resolve_blind_fill_risk_accepted_membership

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def try_multi_fallback(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> bool:
    """Resolve a not-yet-filled optional multi-select. True if it fired."""
    if (
        attr.select_type == "multi" and not attr.required
        and state.vn not in scope.grid_selector_vns
        and not (
            _no_real_fill_justification(attr, scope.rec_by_target)
            and not resolve_blind_fill_risk_accepted_membership(
                state.vn, ctx.filled.get("productSelectionProduct_all", ""),
                scope.workspace_id, scope.catalog_prefix, ctx.dt_cache,
            )
        )
    ):
        # A multi-select that reached here (no single-remaining-
        # option, not required=1 in the raw XML) has nothing
        # unambiguous to justify picking a subset on its own —
        # `valid_opts` from the branch above is NOT reliably in
        # scope here (only assigned inside the sibling `if not
        # value and attr.options:` block, which this attr never
        # entered if attr.options was empty — confirmed live:
        # UnboundLocalError on "APX NEXT All Band"). Recomputed
        # independently against the same constraint. Grid-linked
        # selectors (vn in grid_selector_vns) are excluded from
        # this branch — see grid_selector_vns comment above.
        #
        # Two distinct cases (explicit product decisions,
        # docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_2026_08_
        # 05.md):
        #
        # 1. Genuinely UNCONSTRAINED (no active constraint rule
        #    ever targeted this attr this turn — real Oracle CPQ
        #    UI behavior for e.g. Service Type/Carrier Selection):
        #    prefer default_value; else first real menu option by
        #    order — never leave it silently empty. Confirmed
        #    live: relatedServicesType_astro ("Service Type") has
        #    zero active constraints and no default_value; the
        #    catalog's own first-listed real option is picked
        #    instead of guessing nothing.
        #
        # 2. CONSTRAINED but ambiguous (a real rule narrowed this
        #    attr to 2+ remaining options, just not exactly one):
        #    prefer default_value if still valid under that
        #    constraint; otherwise default to EMPTY, not first-
        #    available — picking an arbitrary one of several
        #    rule-narrowed options is exactly the guessing risk
        #    Fix 1 exists to prevent (confirmed live:
        #    additionalSystemEnhancementFeatureType_astro narrowed
        #    to 9 of 11 by a real constraint — picking option #1
        #    there would be exactly as arbitrary as picking all
        #    9 was). KNOWN, ACCEPTED RISK: _filled_by_rule_id
        #    treats that [] as a real, known-empty value, so a
        #    sibling rule keyed on "does NOT contain value X"
        #    (operator "8", disjoint-from) can fire on it as if
        #    the customer had confirmed nothing — the same
        #    mechanism that collapsed Package Type live via a
        #    separate, pre-existing catalog rule contradiction
        #    (see plan doc's "Known remaining issue").
        is_unconstrained = attr.entity_id not in (scope.constrained_opts or {})
        current_allowed = (
            set(scope.constrained_opts.get(attr.entity_id, []))
            if scope.constrained_opts else None
        )
        candidate_opts = [
            o for o in attr.options
            if _valid(o.item_value)
            and (current_allowed is None or o.item_value in current_allowed)
        ]
        # Priority, highest first: (1) a targeted RecommendationRule
        # already satisfied by the current filled state -- more
        # specific than a generic default_value, same "rule beats
        # default" priority _satisfied_recommendation's own
        # docstring establishes for single-select; (2) the XML
        # default_value; (3) first available (unconstrained case
        # only, see above). Multi-select attrs never reach
        # _satisfied_recommendation via the sibling "else" branch
        # above (mutually exclusive if/elif with this one), so it
        # must be checked here directly.
        rec_match = (
            scope.satisfied_recommendation(attr, candidate_opts)
            if scope.rec_by_target else None
        )
        default_opt = next(
            (o for o in candidate_opts if o.item_value == attr.default_value),
            None,
        ) if attr.default_value else None
        if rec_match:
            rec_value, rec_display, state.fired_rule_name = rec_match
            ctx.filled_multi[state.vn] = [rec_value]
            ctx.display_filled[state.vn] = rec_display
            ctx.sources.setdefault(state.vn, "rule")
            # §2e: this multi-select path never traced its fill at
            # all before — a real, separate gap from the
            # single-select trace call above, closed the same way.
            rule_trace.record_fire(
                rule_type="recommendation", rule_id=state.fired_rule_name,
                attr=state.vn, outcome=f"set={rec_value}",
            )
        elif scope.display_order is not None and not (
            is_unconstrained and candidate_opts
            and (attr.entity_id in scope.rule_governed or state.vn in scope.dt_governed_vns)
        ):
            multi_fallback_layout.select_all_constrained(
                engine, attr, ctx, scope, state, candidate_opts)
        elif default_opt:
            ctx.filled_multi[state.vn] = [default_opt.item_value]
            ctx.display_filled[state.vn] = default_opt.display_name
            ctx.sources.setdefault(state.vn, "default")
        elif is_unconstrained and candidate_opts:
            multi_fallback_unconstrained.blind_pick_narrowed(
                engine, attr, ctx, scope, state, candidate_opts)
        else:
            ctx.filled_multi[state.vn] = []
            ctx.display_filled[state.vn] = NONE_DISPLAY_PLACEHOLDER
            ctx.sources.setdefault(state.vn, "default")
        return True
    return False
