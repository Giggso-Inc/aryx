"""Tier 2 -- a recommendation rule already satisfied by `ctx.filled`.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.engine import (
    _DECISION_ANCHOR_VNS,
    _valid,
)

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def stage_satisfied_recommendation(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Resolve from an already-satisfied recommendation rule."""
    if state.done:
        return
    # 2. Recommendation rule already satisfied by the current filled
    # state — takes priority over the catalog's generic default_value
    # (see _satisfied_recommendation's docstring for the bug this closes).
    #
    # Constraint-filtered candidates, not the raw `attr.options` menu
    # (live regression, docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_
    # PLAN_2026_08_05.md follow-up): a script-backed recommendation
    # rule with a condition unrelated to the attribute a DIFFERENT,
    # ALREADY-ACTIVE constraint rule just narrowed can confidently
    # reassert a value the constraint has already ruled out —
    # confirmed live: "Default Service Type based on Solution Type
    # selected" unconditionally returns "ADVANCED" (its own
    # condition never depends on Hardware Version at all), while a
    # separate constraint rule keyed on Hardware Version had
    # already narrowed this same attr to 3 completely different
    # options. Passing the full, unfiltered menu here let the
    # recommendation win anyway — every turn, forever — because
    # _satisfied_recommendation's own membership check
    # (`candidate_opts`) only protects against a value that was
    # NEVER a real menu option, not one merely excluded by an
    # active constraint. This silently produced an internally
    # inconsistent "Configuration complete" (the recommendation
    # resolved the attribute so nothing was pending) that a
    # separate BOM-gate consistency check caught one full turn
    # later, only once the customer said "confirm".
    # 2026-08-18 fix (confirmed live via direct repro): a decision-
    # anchor attr (country/region/hardware version/product --
    # _DECISION_ANCHOR_VNS) whose CUSTOMER-CONFIRMED value was just
    # dropped THIS SAME pass (a few lines above, because a real
    # constraint narrowed it away) must never be silently reasserted
    # to a DIFFERENT value by a recommendation rule here -- that
    # silently overwrites a real customer decision with no re-ask,
    # no warning, and no trace of what happened to their answer.
    # Skipping this branch lets the attr fall through to `pending`
    # instead, so the customer is asked to re-confirm -- same
    # "never silently reguess a real decision" principle
    # `user_answered_dropped_ids` already enforces for the blind-
    # pick paths later in this function, extended here to close the
    # one place it didn't yet cover. Every OTHER attr (not a
    # decision anchor, or not dropped this pass) is unaffected --
    # this is a narrow, targeted exclusion, not a change to how
    # recommendation rules resolve in general.
    if (
        not state.value and scope.rec_by_target and attr.options
        and not (state.vn in _DECISION_ANCHOR_VNS and attr.entity_id in ctx.user_answered_dropped_ids)
    ):
        _allowed_for_rec = (
            set(scope.constrained_opts.get(attr.entity_id, []))
            if scope.constrained_opts else None
        )
        _rec_candidate_opts = [
            o for o in attr.options
            if _valid(o.item_value)
            and (_allowed_for_rec is None or o.item_value in _allowed_for_rec)
        ]
        rec_match = scope.satisfied_recommendation(attr, _rec_candidate_opts)
        if rec_match:
            state.value, state.display, state.fired_rule_name = rec_match
            state.source = "rule"
