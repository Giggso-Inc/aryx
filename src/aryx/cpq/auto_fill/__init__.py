"""CPQ auto-fill orchestration package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "DataTableSetupResult": "auto_fill_data_table_setup",
    "build_fill_context_and_scope": "auto_fill_setup",
    "build_rec_by_target": "auto_fill_recommendation_check",
    "cascade_fill_pending": "auto_fill_postpass",
    "compute_conflicted_optional_ids": "auto_fill_conflict_detection",
    "compute_data_table_setup": "auto_fill_data_table_setup",
    "is_hardware_version_attr": "auto_fill_hw_order",
    "is_product_line_selector": "auto_fill_hw_order",
    "is_svx_mounting_array_quantity_attr": "auto_fill_hw_order",
    "make_satisfied_recommendation": "auto_fill_recommendation_check",
    "order_pending_hardware_before_product": "auto_fill_hw_order",
    "resolve_pointer_defaults": "auto_fill_postpass",
    "run_auto_fill": "auto_fill_run",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.auto_fill.{mod_name}")
    return getattr(mod, name)
