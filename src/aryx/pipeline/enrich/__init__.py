"""Entity-enrichment pipeline package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_build_type_ancestors": "enrich",
    "_drain_with_timeout": "enrich_drain",
    "_infer_schema_fk_links": "enrich_schema_fk",
    "_relate": "enrich_relate",
    "_relate_isolated": "enrich_relate_isolated",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.pipeline.enrich.{mod_name}")
    return getattr(mod, name)
