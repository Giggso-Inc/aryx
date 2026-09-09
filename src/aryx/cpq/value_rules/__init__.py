"""CPQ value-rules (declarative script action) loader package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "RuleLoadState": "value_rules_state",
    "append_validation_rules": "value_rules_validation",
    "bucket_declarative_actions": "value_rules_bucket",
    "compute_condition_context": "value_rules_condition",
    "finalize_rule_actions": "value_rules_finalize",
    "load_value_rules": "value_rules_load",
    "process_script_backed_actions": "value_rules_script_actions",
    "process_value_rule_row": "value_rules_row",
    "resolve_ambiguous_multivalue_action": "value_rules_ambiguous",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.value_rules.{mod_name}")
    return getattr(mod, name)
