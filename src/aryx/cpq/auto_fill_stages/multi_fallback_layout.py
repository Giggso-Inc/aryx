"""Layout-map-loaded multi-select case: skip entirely, or (2026-08-18
override) select ALL currently-constraint-allowed options.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.engine import logger

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def select_all_constrained(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
    candidate_opts: list,
) -> None:
    """Select every option the active constraint currently allows."""
    # §2d (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md):
    # once a layout map is loaded, nothing satisfying a
    # recommendation rule means skip entirely — never fall
    # to default_value, never guess first-available, never
    # even the explicit-empty placeholder below. Leaves
    # filled_multi/display_filled/sources untouched for vn.
    # `test_multiselect_first_available_skipped_when_layout_
    # loaded` locks this in for a genuinely UNGOVERNED
    # multi-select -- still correctly skipped, unchanged.
    #
    # Narrowed (docs/CPQ_MULTISELECT_GOVERNED_NO_MATCH_ASK_
    # PLAN_2026_08_10.md): excludes the `is_unconstrained
    # and candidate_opts` shape ONLY when the attr is also
    # genuinely governed (rule_governed or _dt_governed_vns,
    # the exact same distinction Group 1/Group 2 already
    # established today for the single-select final chain)
    # so THAT case falls through to its own, already-
    # correct, already-tested handler a few lines below
    # instead of being silently dropped here first.
    # Confirmed live: carrierSelectionMultiSelect_astro
    # (governed via real attrSequence Data Table coverage,
    # no active constraint at all, 6 real options, nothing
    # else resolves it) was reaching this `pass` and
    # vanishing -- neither filled nor asked -- purely
    # because a layout map happened to be loaded, which
    # this branch was never meant to block for an attr the
    # catalog's own data proves is governed. The
    # CONSTRAINED-but-ambiguous case (is_unconstrained=
    # False): 2026-08-18 explicit override (HITL-confirmed
    # after the "never guess among rule-narrowed options"
    # rationale was re-cited in full) -- select ALL options
    # a real rule has currently narrowed this attr to,
    # instead of leaving it empty. Distinct from the
    # single-select blind-fill override above (which picks
    # ONE first-eligible value): for multi-select the
    # requested behavior is "check every currently-allowed
    # box", not "guess one of them". `candidate_opts` here
    # is already filtered to `current_allowed` (the real
    # constraint's narrowed set) a few lines up, so this
    # never selects an option the active rule has excluded.
    if candidate_opts:
        ctx.filled_multi[state.vn] = [o.item_value for o in candidate_opts]
        ctx.display_filled[state.vn] = ", ".join(
            o.display_name for o in candidate_opts)
        ctx.sources.setdefault(state.vn, "auto_all_constrained")
        logger.info(
            "cpq: multi-select %r constrained to %d option(s) "
            "with no rule/default resolving a subset -- "
            "auto-selected all of them instead of leaving "
            "empty (2026-08-18 override of the prior "
            "leave-empty default)", state.vn, len(candidate_opts),
        )
