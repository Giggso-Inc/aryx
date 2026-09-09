"""Ask-turn attribute-cascade recompute API package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_apply_cascade_multi_changes": "ask_cascade_multi_apply",
    "_apply_cascade_new_value": "ask_cascade_apply_value",
    "_build_attr_options_text": "ask_attr_text_helpers",
    "_build_attr_query_response": "ask_attr_query_and_classify_usage",
    "_build_cascade_multi_note": "ask_cascade_multi_note",
    "_build_cascade_multi_response": "ask_cascade_multi_response",
    "_build_cascade_note": "ask_cascade_note",
    "_build_cascade_response": "ask_cascade_response",
    "_build_current_quote_attribute_listing_text": "ask_attr_text_helpers",
    "_drop_related_quantity_attrs": "ask_multi_select_removal_qty_drop",
    "_invalidate_cascade_dependents": "ask_cascade_invalidate_dependents",
    "_recompute_after_attr_activation": "ask_attr_activation_recompute",
    "_recompute_after_attr_clear": "ask_attr_clear_recompute",
    "_recompute_after_bulk_quantity_change": "ask_bulk_quantity_recompute",
    "_recompute_after_cascade": "ask_cascade_recompute",
    "_recompute_after_cascade_multi": "ask_cascade_multi_recompute",
    "_recompute_after_multi_select_removal": "ask_multi_select_removal_recompute",
    "_resolve_split_change_text": "ask_attr_text_helpers",
    "_revert_overridden_multi_singles": "ask_cascade_multi_note",
    "_revert_overridden_user_value": "ask_cascade_user_value_precedence",
    "_with_classify_usage": "ask_attr_query_and_classify_usage",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_attr_recompute.{mod_name}")
    return getattr(mod, name)
