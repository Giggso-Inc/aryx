"""CPQ constraint-rules evaluation package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "apply_constraint_rules": "constraint_rules",
    "apply_narrowing_rec_rules": "constraint_rules_narrowing",
    "apply_rules": "constraint_rules_apply",
    "intersect": "constraint_rules_intersect",
    "normalize": "constraint_rules_intersect",
    "resolve_empty_intersections": "constraint_rules_fallback",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.constraint_rules.{mod_name}")
    return getattr(mod, name)
