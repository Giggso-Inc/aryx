"""CPQ data-table (external catalog governance/resolution) package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_attr_op_val_triples": "data_table_shapes",
    "_attr_val_col_pairs": "data_table_shapes",
    "_cache_write_if_marker_unchanged": "data_table_cache",
    "_clear_invalidation_marker_poll_cache": "data_table_cache",
    "_clear_tables_cache": "data_table_loader",
    "_current_invalidation_marker": "data_table_cache",
    "_detect_shape": "data_table_shapes",
    "_fetch_invalidation_marker_from_db": "data_table_cache",
    "_invalidate_on_marker_change": "data_table_cache",
    "_is_constraint_shaped": "data_table_shapes",
    "_is_hierarchy_shaped": "data_table_shapes",
    "_is_region_rule_shaped": "data_table_shapes",
    "_is_sequence_shaped": "data_table_shapes",
    "_is_series_mapping_shaped": "data_table_shapes",
    "_is_stale_cpq_model": "data_table_stale_models",
    "_load_all_tables": "data_table_loader",
    "_normalize_label": "data_table_shapes",
    "_row_conditions_match": "data_table_whitelist",
    "attr_ever_governed_for_cpq_model": "data_table_governance",
    "attribute_applies": "data_table_governance",
    "discover_cpq_models_for_base_model": "data_table_consistency",
    "find_inconsistent_filled_pairs": "data_table_consistency",
    "find_inconsistent_filled_pairs_detailed": "data_table_consistency",
    "governed_attr_names_for_base_model": "data_table_governance",
    "governed_required_attr_names_for_base_model": "data_table_governance",
    "list_attribute_role_labels": "data_table_product",
    "resolve_invalid_product_variant": "data_table_variant",
    "resolve_product_cpq_model_family": "data_table_product",
    "resolve_product_cpq_models_from_rows": "data_table_product",
    "resolve_region_allow_value": "data_table_product",
    "derive_base_model_from_known_attrs": "data_table_derive_base_model",
    "infer_implied_legal_values": "data_table_inference",
    "resolve_defaultinattr_value": "data_table_defaultinattr",
    "resolve_whitelist_values": "data_table_whitelist",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.data_table.{mod_name}")
    return getattr(mod, name)
