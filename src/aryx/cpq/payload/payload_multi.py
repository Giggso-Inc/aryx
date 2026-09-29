"""`build_payload`'s multi-select (`filled_multi`) serialization stage
(Phase 4, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic
unchanged from the original inline loop.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.payload.payload_display import display_for
from aryx.cpq.payload.payload_state import PayloadContext


def serialize_multi_attrs(
    engine: Any, ctx: PayloadContext, filled_multi: dict[str, list[str]] | None,
    scope_required_and_edited: bool,
) -> None:
    # Array-set members (docs/CPQ_ARRAY_SET_PAYLOAD_PLAN.md — BigMachines'
    # composite "array set": a driver/control attr + ordered member
    # columns, e.g. Mounting Type's selector + its own per-row quantity)
    # are accumulated separately here and grouped into _index-keyed rows
    # AFTER this loop, instead of each member becoming its own flat
    # top-level key.
    out = ctx.out
    for k, vals in (filled_multi or {}).items():
        if k in ctx.hidden or not vals or engine._is_noise_var(k):
            continue
        attr = ctx.attr_by_vn.get(k)
        if scope_required_and_edited and not engine._is_mandatory_input_attr(
            k, attr, ctx.sources.get(k), active_sources=engine._CONFIG_DATA_ACTIVE_SOURCES,
            exclude_anchor_vns=ctx.exclude_anchor_vns,
            gate_attrseq_confirmed_to_active_source=True,
            rule_forced_active_vns=ctx.rule_forced_active_vns,
            data_table_forced_vns=ctx.data_table_forced_vns,
            hint_text=ctx.product_anchor_hint, workspace_id=ctx.workspace_id,
            catalog_prefix=ctx.catalog_prefix, _dt_cache=ctx.dt_cache,
        ):
            continue
        if attr is not None and attr.hide_in_trans:
            continue
        if (attr is not None and attr.array_set_id is not None
                and attr.array_set_role == "member"):
            # Array-set membership takes precedence over the generic
            # set_type=="2" exclusion below — confirmed live (APX NEXT/
            # DM4400, re-ingested workspace 25): quantityVX650ItemType_
            # astro (a REAL array-set member, needed in every row) is
            # itself flagged set_type=="2", which would otherwise drop
            # it entirely before it ever reaches the grouping pass. The
            # set_type=="2" exclusion's own evidence (workspace 14) was
            # about standalone transient UI attrs, never array-set rows.
            ctx.array_set_rows.setdefault(attr.array_set_id, {})[k] = list(vals)
            continue
        if attr is not None and attr.set_type == "2":
            continue  # transient layer — same exclusion as above
        if attr is not None:
            out[k] = {"items": [
                {"value": val, "displayValue": display_for(attr, val)}
                for val in vals
            ]}
        else:
            out[k] = {"value": list(vals)}
