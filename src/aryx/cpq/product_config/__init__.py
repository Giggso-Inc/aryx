"""CPQ product-config (menu/attrs/entity) loader package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "ArraySetLookups": "product_config_lookups",
    "_norm": "product_config_entities",
    "apply_override_redirection": "product_config_menu_override",
    "build_array_set_lookups": "product_config_lookups",
    "build_config_attrs": "product_config_attrs",
    "build_menu_by_attr": "product_config_menu_build",
    "collect_base_menu_neighbors": "product_config_menu_base",
    "compute_rule_target_ids": "product_config_lookups",
    "load_attr_entities": "product_config_entities",
    "load_product_config": "product_config_load",
    "resolve_orphan_menu_items": "product_config_menu_orphan_fk",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.product_config.{mod_name}")
    return getattr(mod, name)
