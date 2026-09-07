"""Commit a resolved value into the fill context (+ rule_trace).

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq import rule_trace
from aryx.cpq.auto_fill_stages.state import AttrResolution

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def commit_value(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Write `state.value` to filled/filled_multi and trace it."""
    # A value can reach here from several upstream paths (hint
    # match, default_value, region-derivation, single-remaining-
    # option, rule recommendation, boolean-default) — none of
    # which check select_type before this point. Route multi-
    # select attrs to filled_multi here too, not just in the
    # dedicated multi branch above, or a value assigned via any
    # of those other paths would land in `filled` as a scalar
    # and silently defeat build_payload's array serialization
    # for it (confirmed live: this is exactly what happened to
    # two attrs that got their value via hint-matching rather
    # than the dedicated multi/constrained-options branch).
    if attr.select_type == "multi":
        ctx.filled_multi[state.vn] = [state.value]
    else:
        ctx.filled[state.vn] = state.value
    ctx.display_filled[state.vn] = state.display or state.value
    ctx.sources.setdefault(state.vn, state.source)
    # Trace step 3 ("already-satisfied recommendation", source
    # == "rule") and step 5 ("rule-governed default-or-first",
    # source == governed_source == "rule") -- the two auto_fill
    # paths this method's own docstring documents as having
    # previously shipped real fill-ordering bugs
    # (solutionTypeDevices_astro, hWVersion_astro). Raven review
    # on PR #156: these were the only evaluate_rules_loop stage
    # ("hide -> recommend -> constrain -> auto-fill") left
    # untraced by the original rule_trace wiring.
    if state.source == "rule" or (state.is_governed and state.source == state.governed_source == "rule"):
        # §2e (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md):
        # attribute to the specific rule _satisfied_recommendation
        # matched when we have one — lands in the same
        # rule_type="recommendation" bucket apply_recommendation_
        # rules' own trace entries use, so one query answers
        # "which rule fired this attribute" either way. Falls
        # back to the old generic tag only for step 5's
        # governed_source path, which isn't _satisfied_
        # recommendation-backed and has no single rule to name.
        if state.fired_rule_name:
            rule_trace.record_fire(
                rule_type="recommendation", rule_id=state.fired_rule_name,
                attr=state.vn, outcome=f"set={state.value}",
            )
        else:
            rule_trace.record_fire(
                rule_type="auto_fill", rule_id=f"auto_fill:{state.source}",
                attr=state.vn, outcome=f"set={state.value}",
            )
