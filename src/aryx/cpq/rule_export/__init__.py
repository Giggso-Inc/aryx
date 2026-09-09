"""CPQ rule-export (product-tree/rule-scope JSON) package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "TreeNode": "rule_export_tree",
    "_leaf_names": "rule_export_tree",
    "_name_index": "rule_export_tree",
    "_normalize": "rule_export_tree",
    "_rule_condition_values": "rule_export_classify",
    "_rule_dict": "rule_export_classify",
    "build_product_tree": "rule_export",
    "classify_rule_scope": "rule_export_classify",
    "export_rules_json": "rule_export",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.rule_export.{mod_name}")
    return getattr(mod, name)
