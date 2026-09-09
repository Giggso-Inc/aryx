"""Ask-turn dispatch-target API package (Phase 8a folder restructuring). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_dispatch_ambiguous": "ask_dispatch_ambiguous_and_scope",
    "_dispatch_approval": "ask_dispatch_query_approval_decline",
    "_dispatch_attr_activation": "ask_dispatch_attr_activation",
    "_dispatch_attr_clear": "ask_dispatch_attr_clear",
    "_dispatch_attr_query": "ask_dispatch_query_approval_decline",
    "_dispatch_bulk_quantity_change": "ask_dispatch_bulk_quantity",
    "_dispatch_change_request": "ask_dispatch_change_request",
    "_dispatch_change_requests_multi": "ask_dispatch_change_request",
    "_dispatch_change_target_without_value": "ask_dispatch_change_request",
    "_dispatch_country_change": "ask_dispatch_quantity_country",
    "_dispatch_decline": "ask_dispatch_query_approval_decline",
    "_dispatch_intent_result": "ask_dispatch_intent_result",
    "_dispatch_multi_select_removal": "ask_dispatch_multi_select_removal",
    "_dispatch_out_of_scope": "ask_dispatch_ambiguous_and_scope",
    "_dispatch_qa_question": "ask_dispatch_query_approval_decline",
    "_dispatch_quantity_change": "ask_dispatch_quantity_country",
    "_dispatch_response_mode_request": "ask_dispatch_query_approval_decline",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_dispatch.{mod_name}")
    return getattr(mod, name)
