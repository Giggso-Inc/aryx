"""The final ask/blind-pick/skip decision -- forced-ask anchors here,
everything else delegated in the original branch order.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.

The inner ``elif`` chain became sequential ``try_*`` calls that each
return True when they matched; the caller returns at the first one, so
first-match-wins is preserved.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages import ask_data_gap
from aryx.cpq.auto_fill_stages import ask_rule_governed_blind
from aryx.cpq.auto_fill_stages import ask_final_pending
from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.auto_fill_stages.state import AttrResolution

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def resolve_ask_or_pending(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> bool:
    """Ask, blind-pick, or skip this still-unresolved attr."""
    if (
        (attr.options or state.is_decision_attr
         or engine.should_ask_free_text_attr(attr, scope.validation_rules, scope.bml_eval))
        and not engine._is_noise_var(state.vn)
        # skip_always_ask means the native UI never shows a question
        # for this attr in this catalog — it must be excluded from
        # `pending` too, not just from is_decision_attr's always-ask
        # override above. `attr.options` alone would otherwise put it
        # right back into pending (confirmed live: SVX asked
        # productSelectionProduct_all again once the first-by-order
        # auto-fill leak above was fixed, because this branch never
        # consulted skip_always_ask on its own).
        # Same carve-out extended to "selectmodel"-named attrs,
        # matching is_decision_attr's own dormant-but-structural
        # skip_always_ask exception above -- an ungoverned
        # "selectmodel" attr (is_governed False, so the governed
        # blind-fallback elif never fires) falls straight through to
        # this branch on `attr.options` alone regardless of
        # is_decision_attr, so it needs this same exclusion too.
        and not (
            state.vn in (scope.skip_always_ask or ())
            and (state.vn == "productSelectionProduct_all" or "selectmodel" in state.vn_flat)
        )
    ):
        # Attrs with a meaningful choice set OR decision-required free-text
        # attrs (region/country) go to pending for user input.
        # Free-text CRM/system fields with no options and no decision
        # requirement are skipped — they are filled by integration.
        # `not _is_noise_var`: integration fields must NEVER be asked
        # even when a decision-key fragment matches their name —
        # confirmed live (Issue 9, docs/CPQ_PRODUCT_SWITCH_ISSUE.md):
        # CRM_BILL_COUNTRY ("Bill Country") got decision-promoted via
        # its "country" fragment and asked first after a product
        # switch, while build_payload drops it unconditionally — the
        # answer was collected then silently discarded. Same predicate
        # the payload exclusion trusts; zero rule impact (no BML
        # script in either catalog reads CRM_BILL_*/CRM_SHIP_*).
        #
        # §2c (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md): when a
        # layout map is loaded, only the anchors (is_decision_attr —
        # Country/Region/Hardware Version/Product) and grid-linked
        # selectors (never auto-fillable, explicit product decision)
        # actually get asked. Everything else that reaches this
        # branch has nothing resolving it via hint/recommendation/
        # default — skip it (leave unfilled, not defaulted-empty)
        # rather than asking, per your explicit call. Sibling-forced
        # re-asks (enforce_exclusive_sibling_families) are a
        # separate code path, unaffected either way. No layout map
        # loaded → today's unchanged "ask everything with options".
        #
        # EXPLICIT INSTRUCTION (2026-08-10, HITL-confirmed): for an
        # attr confirmed real-Data-Table-governed for THIS base
        # model (vn in _dt_governed_vns) but with no rule/Data
        # Table VALUE resolving it and no narrowing signal anywhere
        # (confirmed exhaustively for several such attrs this
        # session -- Additional Frequency Bands, Extend Range,
        # spare-radio pair, System Key, Configuration Type, battery
        # type, keypad type), blind-pick the first real catalog
        # option instead of asking -- same first-by-order fallback
        # §2f already uses for ungoverned attrs, extended here to
        # this confirmed-governed case by explicit user choice.
        # User accepted the tradeoff in full: this maximizes for
        # turn count (≤3 turns), not per-attribute correctness --
        # unlike default_first_available's re-validation (auto_fill
        # re-opens it once real narrowing data appears), there is
        # NO narrowing data to re-check against here, so this can
        # never self-correct on a later pass. `_dt_never_governed_
        # anywhere` is untouched -- that's a different, unrelated
        # safety net (never silently drop an attr no table ever
        # mentions) and still forces `pending` as before.
        #
        # docs/CPQ_DATA_TABLE_GOVERNED_LAYOUT_VISIBILITY_GAP_PLAN_
        # 2026_08_10.md: `and (display_order is None or vn in
        # display_order)` added below -- confirmed live an
        # attrSequence-governed attr the LAYOUT explicitly hides
        # (hide:true) was still reaching this branch and landing in
        # `pending` when it had no blind-pickable option, bypassing
        # the layout-visibility baseline the sibling `elif` right
        # below already enforces. No behavior change when no layout
        # map is loaded, or for any attr the layout actually allows
        # -- only a layout-hidden attr's outcome changes, falling
        # through to the sibling `elif` instead (which correctly
        # skips it, matching every other layout-hidden attr).
        if state.is_decision_attr or state.vn in scope.grid_selector_vns:
            # Forced-ask anchors (Country/Region/Hardware Version/
            # Product) and grid-linked selectors are never auto-
            # fillable -- always ask regardless of rule governance
            # or data gaps below. Unchanged from before this fix.
            # Checked FIRST, ahead of _dt_governed_vns below, same
            # priority order the pre-existing final `elif` used to
            # enforce before this restructuring.
            ctx.pending.append(attr)
            fill_log.log_decision(state.vn, "ask_or_pending", "pending", "FORCED_ASK_ANCHOR",
                                  is_decision_attr=state.is_decision_attr)
        else:
            if ask_data_gap.try_missing_data_skip(engine, attr, ctx, scope, state):
                return True
            if ask_data_gap.try_dt_governed_blind(engine, attr, ctx, scope, state):
                return True
            if ask_rule_governed_blind.try_rule_governed_blind(engine, attr, ctx, scope, state):
                return True
            ask_final_pending.try_final_pending(engine, attr, ctx, scope, state)
        return True
    fill_log.log_decision(state.vn, "ask_or_pending", "not_asked", "NO_OPTIONS_OR_NOISE_OR_SKIP_ALWAYS_ASK")
    return False
