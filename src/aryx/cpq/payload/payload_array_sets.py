"""`build_payload`'s array-set row-grouping stage (Phase 4, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md): folds the per-member values
accumulated by `payload_multi.serialize_multi_attrs` into `_index`-keyed
rows under each array-set driver's wrapper key. Logic unchanged from the
original inline block.
"""

from __future__ import annotations

import re
from typing import Any

from aryx.cpq.payload.payload_display import display_for
from aryx.cpq.payload.payload_state import PayloadContext


def group_array_set_rows(ctx: PayloadContext, attrs: list[Any] | None, filled: dict[str, str]) -> None:
    if not ctx.array_set_rows:
        return
    out = ctx.out
    drivers_by_set_id = {
        a.array_set_id: a for a in (attrs or [])
        if a.array_set_id is not None and a.array_set_role == "driver"
    }
    for set_id, member_vals in ctx.array_set_rows.items():
        driver = drivers_by_set_id.get(set_id)
        if driver is None or not driver.array_set_wrapper_key:
            continue
        all_members = sorted(
            (a for a in (attrs or [])
             if a.array_set_id == set_id and a.array_set_role == "member"),
            key=lambda a: a.array_col_order,
        )
        # 2026-08-25 (SVX Mounting Type array-set payload RCA, live-
        # confirmed against a real reference payload): three shape
        # errors in the original version of this block --
        # (A) `_index` was a sequential "i-th thing the customer
        #     selected" counter, but the real contract's `_index` is
        #     the selected option's own fixed position within the
        #     selector's catalog option order (the native UI's
        #     fixed per-option row grid -- picking option #3 first
        #     must still emit `_index: 2`, not `_index: 0`).
        # (B) the selector's own value/displayValue was written
        #     into the row; the real payload never repeats it --
        #     `_index` alone already identifies which option.
        # (C) hidden members (e.g. MountingQuantityDummyArrayAttribute_
        #     viSoln) were unconditionally excluded from every row;
        #     the real payload includes a hidden member that was
        #     never independently answered as a structural `true`
        #     marker on every populated row. A hidden member that
        #     DOES carry real per-row values (an ordinary hidden qty
        #     column) is unaffected -- it's still written normally.
        selector = next((a for a in all_members if a.options), None)
        if selector is None or selector.variable_name not in member_vals:
            continue
        selected_values = member_vals[selector.variable_name]
        catalog_positions = {
            o.item_value: i for i, o in enumerate(selector.options)
        }
        other_members = [
            a for a in all_members
            if a is not selector and a.variable_name in member_vals
        ]
        hidden_flag_members = [
            a for a in all_members
            if a.hidden and a is not selector and a.variable_name not in member_vals
        ]
        # Quantity fallback: a qty-type member (no options) that has
        # no filled_multi entry of its own — the real conversation
        # flow instead filled a per-option NAMED attr for it (see
        # array_set_qty_source above). Sourced per-row from the
        # selector's own selected value at that index.
        qty_fallback_members = [
            a for a in (attrs or [])
            if a.array_set_id == set_id and a.array_set_role == "member"
            and not a.hidden and not a.options
            and a.variable_name not in member_vals
        ]
        item_map = ctx.grid_links.get(selector.variable_name, {}) if selector else {}
        rows: list[dict[str, Any]] = []
        for i, sel_val in enumerate(selected_values):
            position = catalog_positions.get(sel_val)
            if position is None:
                continue  # unrecognized value -- never guess a row for it
            row: dict[str, Any] = {"_index": position}
            for a in other_members:
                vlist = member_vals[a.variable_name]
                if i >= len(vlist):
                    continue
                val = vlist[i]
                if a.options:
                    row[a.variable_name] = {
                        "value": val, "displayValue": display_for(a, val),
                    }
                elif re.fullmatch(r"-?\d+", val):
                    row[a.variable_name] = int(val)
                else:
                    row[a.variable_name] = val
            for a in hidden_flag_members:
                row[a.variable_name] = True
            if qty_fallback_members and sel_val:
                real_qty_vn = item_map.get(sel_val.strip().lower())
                if real_qty_vn and real_qty_vn in filled:
                    raw = filled[real_qty_vn]
                    for qty_member in qty_fallback_members:
                        row[qty_member.variable_name] = (
                            int(raw) if re.fullmatch(r"-?\d+", raw) else raw
                        )
            rows.append(row)
        out[driver.array_set_wrapper_key] = {"items": rows}
        # The driver's own value ships as a SIBLING bare int (row
        # count), NOT nested inside the wrapper — confirmed by a
        # real reference payload. Supersedes the narrower
        # is_array_control heuristic above (single control + single
        # multi-select) whenever a real array-set link exists.
        out[driver.variable_name] = len(rows)
