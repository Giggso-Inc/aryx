"""Ask-turn change-handler API package (Phase 8a folder restructuring). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_handle_approval": "ask_handle_approval",
    "_handle_attr_activation": "ask_handle_attr_activation",
    "_handle_attr_clear": "ask_handle_attr_clear",
    "_handle_bulk_quantity_change": "ask_handle_bulk_quantity_change",
    "_handle_cascade": "ask_handle_cascade",
    "_handle_cascade_multi": "ask_handle_cascade_multi",
    "_handle_cpq_qa": "ask_handle_cpq_qa",
    "_handle_multi_select_removal": "ask_handle_multi_select_removal",
    "_llm_first_gateway_turn": "ask_handle_llm_first_gateway_turn",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_handle.{mod_name}")
    return getattr(mod, name)
