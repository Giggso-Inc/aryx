"""`resolve_one_attr` -- the stage pipeline for `CpqEngine.auto_fill`'s
per-attribute resolution (docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

This is the same 6-tier priority cascade `auto_fill`'s own docstring
documents (already filled -> NL hint -> satisfied recommendation -> XML
default_value -> rule-governed default-or-first -> first-eligible-option-by-
order), plus hidden-attr and multi-select handling woven through -- unchanged
in behavior, just no longer one 1,500-line function body.

The original was a single continuous decision tree: sequential/nested
if/elif chains sharing a dozen locals, with several bare `return`s exiting
the whole function early. Those locals now live on `AttrResolution` and the
early exits are `state.done = True`, checked here between every stage (and
again at the top of each stage). Stage order below is the original top-to-
bottom statement order of the function body, so the priority cascade is
preserved exactly.

`engine` is the live `CpqEngine` instance (for its own method calls, `self.`
in the original); `ctx` is a `FillContext` (mutable, shared across every
attr in one `auto_fill` call); `scope` is a `FillScope` (read-only, includes
already-bound closures for `is_pointer_default`/`satisfied_recommendation`/
`dt_never_governed_anywhere`, built once by `auto_fill`'s own P0 setup
before this loop starts).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages import (
    commit_and_tail,
    governance_flags,
    governed_boolean_fallback,
    region_and_base_model,
    tier0_already_filled,
    tier0_base_model_default,
    tier0_already_filled_multi,
    tier0_forward_fill,
    tier0_hidden,
    tier0_not_applicable_guard,
    tier1_hint_match,
    tier2_satisfied_rec,
    tier3_default_value,
    tier4_options,
)
from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.raven_log import would_log

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr

# Stage order == the original function body's statement order. Each stage
# takes (engine, attr, ctx, scope, state), mutates `state`/`ctx` in place,
# and sets `state.done` where the original returned out of the function.
_STAGES = (
    tier0_not_applicable_guard.stage_not_applicable_guard,
    tier0_base_model_default.stage_base_model_default,
    tier0_already_filled.stage_already_filled,
    tier0_already_filled_multi.stage_already_filled_multi,
    tier0_hidden.stage_hidden,
    tier0_forward_fill.stage_forward_fill,
    tier1_hint_match.stage_hint_match,
    tier2_satisfied_rec.stage_satisfied_recommendation,
    tier3_default_value.stage_default_value,
    governance_flags.stage_governance_flags,
    region_and_base_model.stage_region_and_base_model,
    tier4_options.stage_options,
    governed_boolean_fallback.stage_governed_boolean,
    commit_and_tail.stage_commit_and_tail,
)


def resolve_one_attr(
    engine: "CpqEngine", attr: "ConfigAttr", ctx: "FillContext", scope: "FillScope",
) -> None:
    """Resolve (fill, defer to `ctx.pending`, or skip) one attribute."""
    # `value`/`display`/`source` started as None/None/"auto" in the original
    # body; those are `AttrResolution`'s own defaults. `vn_flat` was derived
    # at the top of the NL-hint tier and is read by several later stages --
    # a pure derivation of `vn`, so computing it here is equivalent.
    # §2e (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md): `fired_rule_name`
    # is set by `satisfied_recommendation`'s call sites so the trace call in
    # `commit_value` can attribute the fill to the specific rule that fired
    # instead of a generic tag -- also an `AttrResolution` default (None).
    vn = attr.variable_name
    state = AttrResolution(vn=vn, vn_flat=vn.lower().replace("_", ""))
    trace = would_log("DEBUG")
    trail: list = []
    prev_src = ctx.sources.get(vn)
    had = vn in ctx.filled or vn in ctx.filled_multi
    before_value = ctx.filled_multi.get(vn) if vn in ctx.filled_multi else ctx.filled.get(vn)
    for stage in _STAGES:
        snap = fill_log.stage_snapshot(ctx, state) if trace else None
        stage(engine, attr, ctx, scope, state)
        if trace:
            trail.append([stage.__module__.rsplit(".", 1)[-1],
                          fill_log.stage_outcome(snap, fill_log.stage_snapshot(ctx, state))])
        if state.done:
            break
    if trace:
        fill_log.log_stage_trail(ctx, state, trail, prev_src, had, before_value, attr)
