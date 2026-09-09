"""`build_payload`'s scalar (`filled`) serialization stage (Phase 4,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the
original inline loop.
"""

from __future__ import annotations

import re
from typing import Any

from aryx.cpq.engine import _valid
from aryx.cpq.payload.payload_display import display_for
from aryx.cpq.payload.payload_state import PayloadContext


def serialize_scalar_attrs(
    engine: Any, ctx: PayloadContext, filled: dict[str, str],
    scope_required_and_edited: bool,
) -> None:
    out = ctx.out
    for k, v in filled.items():
        if k in ctx.hidden:
            continue
        if not v or engine._is_html_value(v) or engine._is_noise_var(k):
            continue
        if k in ctx.consumed_by_array_set:
            # Folded into its array-set row under the qty member's own
            # key name instead (see array_set_qty_source above) — must
            # not ALSO ship as a separate flat top-level key.
            continue
        attr = ctx.attr_by_vn.get(k)
        if scope_required_and_edited and _scope_excluded(engine, ctx, k, attr):
            continue
        if attr is not None and engine._attr_hidden_from_submission(attr):
            continue
        if attr is not None and attr.is_array_control:
            # Bare int = row count when unambiguous (see derivation
            # above); otherwise abstain rather than ship the
            # disconnected, coincidental raw value that caused the
            # original 5-vs-7 mismatch this exclusion was meant to fix.
            if ctx.array_control_count is not None:
                out[k] = ctx.array_control_count
            continue
        if attr is not None and engine._attr_is_transient_set_type(attr):
            # Transient UI/action-layer attr (see ConfigAttr.set_type) —
            # confirmed live: the real CPQ API rejects every one of
            # these with "has an invalid payload" (APX catalog's own
            # population: _price_book_var_name/mergePackage/update/
            # clearPackageJson/testPager2...), same treatment as
            # hide_in_trans. They still drive rules and conversation —
            # only the POST excludes them.
            #
            # auto_lock=1 is the exception (docs/CPQ_SESSION_2_OPEN_
            # ISSUES.md, auto_lock double-wrap finding): a set_type=="2"
            # attr with auto_lock=1 (e.g. archeType_viSoln,
            # modelSelectionSelectModel_viSoln, serviceType_viSoln — the
            # SAME attrs an earlier pass wrongly assumed were always
            # transient) is a real, includable value — falls through to
            # normal serialization below, then gets double-wrapped.
            continue
        if (attr is not None and not attr.options
                and v == attr.default_value
                and v in ctx.attr_by_vn and v != k):
            # Unresolved pointer token (Issue 11): the value still
            # equals the attr's own pointer default — another attr's
            # variable name, not data. Fill-time guards prevent new
            # fills, but a session filled on an older build carries the
            # token in its saved state; scrub it here so a stale
            # session can never ship '"modelname_all":
            # "_bm_model_variable_name"'.
            continue
        if not (_valid(v) or ctx.sources.get(k) in engine._CONFIRMED_SOURCES):
            continue
        if attr is None:
            out[k] = {"value": v}
            continue
        select_type = attr.select_type
        if select_type == "boolean":
            out[k] = v.strip().lower() in ("true", "yes")
        elif select_type == "currency":
            try:
                amount: float | str = float(v)
            except ValueError:
                amount = v  # not numeric — pass through rather than guess
            out[k] = {
                "value": amount,
                "currency": filled.get("_BM_USER_CURRENCY", "USD"),
            }
        elif select_type in ("integer", "float") and attr.options:
            # A MENU-backed numeric (e.g. bWCNumberOfRefreshes_viSoln:
            # data_type=3 but real menu items "1"/"2"/"3") is a menu to
            # the API — bare numeric was rejected live ("has an invalid
            # payload"); the menu shape below is what its siblings with
            # identical menus use. Menu presence wins over data_type.
            out[k] = {"value": v, "displayValue": display_for(attr, v)}
        elif select_type == "integer":
            out[k] = int(v) if re.fullmatch(r"-?\d+", v) else v
        elif select_type == "float":
            try:
                out[k] = float(v)
            except ValueError:
                out[k] = v
        elif select_type == "date":
            out[k] = v
        elif attr.options:
            out[k] = {"value": v, "displayValue": display_for(attr, v)}
        else:
            out[k] = v
        if attr.set_type == "2" and attr.auto_lock and k in out:
            # Confirmed live (archeType_viSoln, modelSelectionSelectModel_
            # viSoln — both set_type=="2"/auto_lock=1, data_type=1/
            # menu_type=1, i.e. ordinary single-select) — the real API
            # wraps this class of attr ONE level deeper than every other
            # menu attr: {"value": {"value":..,"displayValue":..}}. Wraps
            # whatever shape was just built above, generic over
            # select_type — not special-cased to the single-select
            # branch, since no other select_type + auto_lock=1
            # combination has been observed yet either way.
            out[k] = {"value": out[k]}


def _scope_excluded(engine: Any, ctx: PayloadContext, k: str, attr: Any) -> bool:
    return not engine._is_mandatory_input_attr(
        k, attr, ctx.sources.get(k), active_sources=engine._CONFIG_DATA_ACTIVE_SOURCES,
        exclude_anchor_vns=ctx.exclude_anchor_vns,
        gate_attrseq_confirmed_to_active_source=True,
        rule_forced_active_vns=ctx.rule_forced_active_vns,
        data_table_forced_vns=ctx.data_table_forced_vns,
    )
