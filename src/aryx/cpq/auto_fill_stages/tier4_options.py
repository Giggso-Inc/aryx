"""Tier 4 -- option-set resolution entry point: compute the eligible
option set, then take the single-remaining-option shortcut or hand off
to the rule-governed chain.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.

The original ``elif`` after the single-option shortcut became an
``else:`` delegating to ``governed_entry`` -- structurally identical
first-match-wins semantics, just with the body in another module.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages import tier5_governed_entry
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.engine import _valid

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def stage_options(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Resolve from this attr's eligible option set."""
    if state.done:
        return
    if not state.value and attr.options:
        state.allowed_for_attr = (
            set(scope.constrained_opts.get(attr.entity_id, []))
            if scope.constrained_opts else None
        )
        if state.allowed_for_attr is not None:
            # A constraint is a source of truth for VALIDITY, not
            # catalog spelling. If it names a legal value with no
            # literal item_value match in the real catalog (live-
            # confirmed: productSelectionProduct_all's constraint
            # returns 'APX NEXT XE 4G LTE PLUS 5G', which no real
            # option equals), keeping the phantom value in the
            # allowed set is harmless (nothing matches it anyway)
            # but discarding the WHOLE set back to unconstrained
            # over one bad value throws away the legitimate,
            # real-matching values too (live-confirmed regression:
            # Product went from a flip-flopping 1-2 option menu to
            # showing all 325 raw options). Drop only the phantom
            # entries -- keep whichever real values the constraint
            # did correctly narrow to. Falls back to fully
            # unconstrained only if EVERY value was phantom (an
            # empty allowed set would otherwise wrongly zero out
            # valid_opts entirely).
            real_item_values = {o.item_value for o in attr.options}
            narrowed = state.allowed_for_attr & real_item_values
            state.allowed_for_attr = narrowed or None
        state.valid_opts = [
            o for o in attr.options
            if _valid(o.item_value)
            and (state.allowed_for_attr is None or o.item_value in state.allowed_for_attr)
        ]
        if (
            len(state.valid_opts) == 1 and not state.is_decision_attr
            and attr.entity_id not in ctx.user_answered_dropped_ids
        ):
            # Exactly one choice — auto-fill, no user decision needed.
            #
            # EXCLUDED for is_decision_attr (2026-08-17, live-
            # confirmed): a constraint script can resolve a legal
            # value that has NO literal match in attr.options at
            # all (confirmed live: productSelectionProduct_all's
            # "Restrict APX Next Product Selection based on HW
            # Version" constraint correctly returned 2 legal
            # values, {'APX NEXT ENHANCED', 'APX NEXT XE 4G LTE
            # PLUS 5G'}, but the real catalog menu has no option
            # whose item_value literally equals the second string
            # at all -- only 'APX NEXT XE MULTI'/'APX NEXT XE
            # SINGLE BAND' exist). Intersecting against the real
            # menu then silently drops the phantom entry, leaving
            # "exactly 1" as a false positive from a script/
            # catalog mismatch, not a genuine single-choice
            # situation -- and Product got auto-filled without
            # ever asking. Depends on Tier-2 LLM evaluation timing
            # (whether the constraint script gets a slot before
            # the per-turn cap), so it doesn't reproduce every
            # turn -- non-decision attrs keep the original
            # shortcut; decision-required ones (Country/Region/
            # Hardware Version/Product) never take it, same
            # protection this whole function already gives them
            # everywhere else.
            #
            # EXCLUDED when this attr's only-one-option state exists
            # because a constraint just rejected the CUSTOMER'S OWN
            # explicit answer this same turn (live-verified bug,
            # 2026-07-23: changing Billing Option to "Annual" got
            # silently replaced with "Immediate" — the drop was
            # correctly detected and noted, but this branch — a
            # DIFFERENT, earlier branch than the blind first-by-order
            # fallback the existing user_answered_dropped_ids guard
            # protects a few lines below — filled the one remaining
            # option unconditionally, with no awareness that "only
            # one option remains" was true BECAUSE it just excluded
            # what the customer picked). Falls through to `pending`
            # instead, same "a real decision deserves to be re-asked,
            # not silently re-guessed" principle as the sibling fix
            # (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 4) — the
            # resume prompt shown for `pending` already tells the
            # customer the one remaining valid option.
            state.value = state.valid_opts[0].item_value
            state.display = state.valid_opts[0].display_name
        else:
            tier5_governed_entry.governed_entry(engine, attr, ctx, scope, state)
