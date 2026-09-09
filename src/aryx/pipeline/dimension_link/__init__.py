"""Dimension-linking pipeline package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_candidate_columns": "dimension_link_columns",
    "_dimension_groups": "dimension_link_groups",
    "_find": "dimension_link_groups",
    "_is_dimension_column": "dimension_link_columns",
    "_union": "dimension_link_groups",
    "detect_and_link_dimensions": "dimension_link",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.pipeline.dimension_link.{mod_name}")
    return getattr(mod, name)
