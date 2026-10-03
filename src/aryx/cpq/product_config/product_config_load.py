"""Orchestrator for `load_product_config` (Phase 4, one of the 8
previously-deferred oversized `CpqEngine` methods, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md). Ties together entity discovery, the
base/orphan-FK/override menu-neighbor passes, menu-option building,
array-set + rule-target lookups, and final `ConfigAttr` construction.
Logic unchanged from the original inline body.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.engine import ConfigAttr
from aryx.cpq.product_config.product_config_attrs import build_config_attrs
from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.product_config.product_config_entities import load_attr_entities
from aryx.cpq.product_config.product_config_lookups import build_array_set_lookups, compute_rule_target_ids
from aryx.cpq.product_config.product_config_menu_base import collect_base_menu_neighbors
from aryx.cpq.product_config.product_config_menu_build import build_menu_by_attr
from aryx.cpq.product_config.product_config_menu_orphan_fk import resolve_orphan_menu_items
from aryx.cpq.product_config.product_config_menu_override import apply_override_redirection


def load_product_config(
    engine: Any, reader: Any, workspace_id: int, product_hint: str,
) -> tuple[list["ConfigAttr"], str]:
    attr_ents, attr_pg, resolved_catalog_prefix, all_type_names = load_attr_entities(
        engine, reader, workspace_id, product_hint)
    if not attr_ents:
        fill_log.log_load("product_config", result="no_attr_entities", workspace_id=workspace_id,
                          empty=True, catalog_prefix=resolved_catalog_prefix)
        return [], product_hint

    neighbor_map, all_menu_ids, orphan_eids = collect_base_menu_neighbors(
        reader, attr_ents, attr_pg, resolved_catalog_prefix)

    fk_menu_pool = resolve_orphan_menu_items(
        engine, reader, workspace_id, attr_pg, orphan_eids, resolved_catalog_prefix,
        all_type_names, neighbor_map, all_menu_ids,
    )
    apply_override_redirection(
        engine, reader, workspace_id, attr_ents, attr_pg, all_type_names,
        resolved_catalog_prefix, fk_menu_pool, neighbor_map, all_menu_ids,
    )

    menu_by_attr = build_menu_by_attr(engine, workspace_id, neighbor_map, all_menu_ids)
    array_sets = build_array_set_lookups(workspace_id, resolved_catalog_prefix)
    rule_target_ids = compute_rule_target_ids(engine, workspace_id, resolved_catalog_prefix)

    config_attrs = build_config_attrs(
        engine, attr_ents, attr_pg, menu_by_attr, array_sets, rule_target_ids)

    # Dedup by variable_name (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 8):
    # a catalog accidentally re-ingested wholesale (confirmed live,
    # workspace 19's SL3500e catalog — every entity type doubled,
    # timestamps exactly one day apart) produces 2+ ConfigAttr entries
    # sharing the same variable_name, each independently landing in
    # `pending` when unfilled — surfacing as duplicate questions for the
    # SAME real attribute (confirmed live: modelSelectionCertification_
    # apcr and 5 siblings each asked twice in one turn). Keep only the
    # highest entity_id per variable_name — aryx_entity.id is a
    # monotonic insert-order sequence, so this keeps whichever ingest
    # ran LAST, the same proxy the existing "duplicate entity per real
    # id" handling already relies on elsewhere (menu-option loss fix).
    by_vn: dict[str, ConfigAttr] = {}
    for a in config_attrs:
        existing = by_vn.get(a.variable_name)
        if existing is None or a.entity_id > existing.entity_id:
            by_vn[a.variable_name] = a
    config_attrs = list(by_vn.values())

    config_attrs.sort(key=lambda a: a.order)
    fill_log.log_load("product_config", result="loaded", workspace_id=workspace_id,
                      catalog_prefix=resolved_catalog_prefix, attr_entity_count=len(attr_ents),
                      attr_count=len(config_attrs), menu_attr_count=len(menu_by_attr),
                      rule_target_count=len(rule_target_ids))
    return config_attrs, product_hint
