"""Tier 5 (multi-select) -- a governed multi-select attr: only ever
auto-selects when a real constraint or Data Table narrows it to
exactly one value.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.rule_trace import rule_trace
from aryx.cpq.auto_fill_stages.state import AttrResolution

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def governed_multi(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Fill a governed multi-select, or fall through unresolved."""
    # docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_
    # 2026_08_05.md — an active constraint narrowing to
    # exactly ONE remaining option is exactly as
    # unambiguous here as it already is for single-
    # select (the `len(valid_opts) == 1` branch above);
    # narrowing to SEVERAL remaining options is not the
    # same signal and must not be auto-selected in
    # full. Confirmed live: "Constrain Additional
    # feature Type" (condition: any product selected —
    # true for virtually every order) narrows
    # additionalSystemEnhancementFeatureType_astro to 9
    # of 11 options; that 9-item list is the catalog's
    # MENU of available choices, not a recommendation
    # to select all 9 — auto-selecting all 9
    # (including "ICE KIT") silently triggered an
    # unrelated constraint that collapsed a real
    # question (Package Type) to zero valid options.
    # allowed_for_attr is None → no active constraint
    # narrowed this attr → leave unselected, ask the
    # user (unchanged).
    if state.allowed_for_attr is not None and len(state.valid_opts) == 1:
        ctx.filled_multi[state.vn] = [o.item_value for o in state.valid_opts]
        ctx.display_filled[state.vn] = ", ".join(o.display_name for o in state.valid_opts)
        ctx.sources.setdefault(state.vn, state.governed_source)
        state.filled_multi_now = True
        if state.governed_source == "rule":
            rule_trace.record_fire(
                rule_type="auto_fill", rule_id="auto_fill:rule_governed_multi",
                attr=state.vn, outcome=f"set={ctx.filled_multi[state.vn]}",
            )
    elif state.allowed_for_attr is None:
        # No active rule-based constraint narrowed this
        # multi-select attr — the script governing it
        # either doesn't exist or failed to resolve.
        # Same real-Data-Table attempt as the
        # single-select _NEVER_GUESS_SCRIPT_GOVERNED
        # branch below, applied here too since
        # carrierSelectionMultiSelect_astro-shaped attrs
        # are multi-select (docs proof §11-§12). Only
        # ever fills confidently when exactly one real
        # value resolves.
        dt_match = engine._resolve_via_data_tables(
            state.vn, ctx.filled, state.valid_opts, scope.workspace_id, scope.catalog_prefix, ctx.dt_cache,
        )
        if dt_match:
            ctx.filled_multi[state.vn] = [dt_match.item_value]
            ctx.display_filled[state.vn] = dt_match.display_name
            ctx.sources.setdefault(state.vn, "data_table")
            state.filled_multi_now = True
        # No confident single match (2+ legal values,
        # or none): NOT handled here -- falls through
        # (filled_multi_now stays False) to the second
        # multi-select branch below, whose own
        # `is_unconstrained and candidate_opts` case
        # already correctly blind-picks the first real
        # option (tagged "default_first_available") for
        # this exact genuinely-unconstrained shape. An
        # earlier version of this fix duplicated that
        # logic here with a different tag, which broke
        # the existing re-validation contract keyed on
        # "default_first_available" (docs/CPQ_
        # MULTISELECT_GOVERNED_NO_MATCH_ASK_PLAN_2026_08_
        # 10.md) -- see that plan's real gap instead:
        # `elif display_order is not None: pass` further
        # below intercepts this case BEFORE it ever
        # reaches the working is_unconstrained logic.
