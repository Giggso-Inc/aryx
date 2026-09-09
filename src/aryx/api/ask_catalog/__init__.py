"""Ask-turn catalog-listing API package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_build_catalog_attribute_listing_text": "ask_catalog_listing_text",
    "_looks_like_raw_variable_name": "ask_catalog_listing_scope",
    "_normalize": "ask_catalog_listing_reconcile",
    "_reaches_json_payload": "ask_catalog_listing_scope",
    "_reconcile_catalog_listing_groups": "ask_catalog_listing_reconcile",
    "_relevant_intent_candidates": "ask_relevant_intent_candidates",
    "_resolve_target_description": "ask_target_description",
    "_scope_catalog_listing_labels": "ask_catalog_listing_scope",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_catalog.{mod_name}")
    return getattr(mod, name)
