"""`load_product_config`'s Step 4 (Phase 4, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md): builds the final `ConfigAttr` list from the fetched
entities/PostgreSQL rows/menu options/array-set lookups. Logic unchanged
from the original inline block.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.engine import (
    ConfigAttr,
    MenuOption,
    _catalog_prefix,
    _NOISE_VAR_FRAGMENTS,
    classify_select_type,
    logger,
)
from aryx.cpq.product_config.product_config_lookups import ArraySetLookups


def build_config_attrs(
    engine: Any, attr_ents: list[dict], attr_pg: dict[int, dict],
    menu_by_attr: dict[int, list["MenuOption"]], array_sets: ArraySetLookups,
    rule_target_ids: set[int], listed_attr_names: frozenset[str] = frozenset(),
) -> list["ConfigAttr"]:
    config_attrs: list[ConfigAttr] = []
    for ent in attr_ents:
        eid = ent["id"]
        pg = attr_pg.get(eid, {})

        var_name = str(
            pg.get("variable_name") or pg.get("name") or ent.get("name") or ""
        ).strip()
        if not var_name:
            continue

        # Patch C: skip noise attrs (TestPager, Error, dummy_* etc.)
        vn_lo = var_name.lower()
        if any(f in vn_lo for f in _NOISE_VAR_FRAGMENTS) and var_name not in listed_attr_names:
            logger.debug("cpq: skipping noise attr %r", var_name)
            continue

        # docs/CPQ_CONFIG_ATTR_STATUS_FILTERING_ROOT_CAUSE_AND_FIX_
        # PLAN_2026-08-14.md — BmConfigAttr rows carry the same
        # status=1 (active) / status=3 (inactive) convention already
        # relied on for BmConfigRule (see fetch_rules/fetch_value_
        # rules' active_only). Confirmed live: 15 real status=3
        # attribute rows exist (workspace 19) and were loaded
        # unconditionally — a deactivated/deleted attribute could
        # still be shown/asked to the customer. status is present on
        # every real BmConfigAttr row across both real workspaces
        # (verified — no attr lacks the field), so this never
        # accidentally excludes a legitimately-untracked attr.
        if str(pg.get("status", "")).strip() == "3":
            logger.debug("cpq: skipping inactive (status=3) attr %r", var_name)
            continue

        display = str(pg.get("name") or ent.get("name") or var_name).strip()
        required_raw = str(pg.get("required") or "0").strip().lower()
        required = required_raw in ("1", "true", "yes")
        default_val = str(pg.get("default_value") or "").strip()
        order = int(pg.get("order_number") or pg.get("order") or 999)

        hidden_raw = str(pg.get("hidden") or "0").strip().lower()
        is_hidden = hidden_raw in ("1", "true", "yes")
        array_control_raw = str(pg.get("is_array_control_attr") or "0").strip().lower()
        is_array_control = array_control_raw in ("1", "true", "yes")
        # "quantity" name fragment — candidate grid-quantity target attr
        # (e.g. mountingTypeShirtMagneticMountQuantity_viSoln). Kept
        # despite hidden+no-default so resolve_array_grid_links() can
        # name-match it against a visible selector's menu options (§5
        # Change B, docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_GRID_PLAN.md).
        is_grid_qty_candidate = "quantity" in vn_lo
        src_id_raw = pg.get("id") or pg.get("attribute_id") or pg.get("bm_config_rule_id")
        is_rule_target = eid in rule_target_ids or (
            src_id_raw is not None
            and str(src_id_raw).strip().isdigit()
            and int(src_id_raw) in rule_target_ids
        )
        if (is_hidden and not default_val
                and not (is_array_control or is_grid_qty_candidate or is_rule_target)):
            # Hidden with nothing to contribute — never shown/asked, and
            # no static default to feed BML scripts — dropped, UNLESS
            # it's a rule action's target (Amendment 13): those attrs
            # are dynamically populated by a recommendation/constraint
            # rule at apply time, not a static default, and dropping
            # them here means they can never be filled at all.
            continue

        hide_in_trans_raw = str(pg.get("hide_in_trans") or "0").strip().lower()
        is_hide_in_trans = hide_in_trans_raw in ("1", "true", "yes")
        auto_lock_raw = str(pg.get("auto_lock") or "0").strip().lower()
        is_auto_lock = auto_lock_raw in ("1", "true", "yes")

        # Exclude layout/UI-noise nodes by checking attribute content
        if engine._is_layout_noise(ent.get("type") or ""):
            continue

        # ID bridge: rules reference attributes by the BM-native id from
        # the source system, not by the aryx entity id. Keep both.
        source_id: int | None = None
        for id_key in ("id", "attribute_id", "bm_config_attr_id"):
            raw_sid = pg.get(id_key)
            if raw_sid is not None:
                try:
                    source_id = int(str(raw_sid).strip())
                    break
                except (TypeError, ValueError):
                    continue

        config_attrs.append(ConfigAttr(
            entity_id=eid,
            variable_name=var_name,
            display_label=display,
            required=required,
            default_value=default_val,
            options=menu_by_attr.get(eid, []),
            order=order,
            source_id=source_id,
            select_type=classify_select_type(pg),
            catalog_prefix=_catalog_prefix(ent.get("type") or ""),
            hidden=is_hidden,
            is_value_rule_target=is_rule_target,
            hide_in_trans=is_hide_in_trans,
            set_type=str(pg.get("set_type") or "").strip(),
            is_array_control=is_array_control,
            auto_lock=is_auto_lock,
            array_set_id=(array_sets.array_set_id_by_attr_id.get(source_id) if source_id else None),
            array_set_role=(array_sets.role_by_attr_id.get(source_id, "") if source_id else ""),
            array_col_order=(array_sets.order_by_attr_id.get(source_id, 999) if source_id else 999),
            array_set_wrapper_key=(
                array_sets.wrapper_key_by_attr_id.get(source_id, "") if source_id else ""
            ),
        ))
    return config_attrs
