"""Ask-turn product/country switch API package (Phase 8a folder restructuring). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_build_switch_redetect_prompt": "ask_turn_switch_redetect_prompt",
    "_check_mid_turn_switch_redetection": "ask_turn_switch_redetect",
    "_complete_model_switch": "ask_turn_model_switch_complete",
    "_complete_product_switch": "ask_turn_product_switch_complete",
    "_handle_confirm_model_switch_anchor": "ask_turn_model_switch",
    "_offer_model_switch": "ask_turn_model_switch",
    "_offer_model_switch_from_hint": "ask_turn_model_switch_hint",
    "_handle_confirm_switch_anchor": "ask_turn_confirm_switch_anchor",
    "_handle_confirm_switch_decline": "ask_turn_confirm_switch_decline",
    "_handle_product_switch_pending_anchor": "ask_turn_product_switch_anchor",
    "_handle_suggest_switch_anchor": "ask_turn_suggest_switch_anchor",
    "_handle_switch_country_anchor": "ask_turn_switch_country_anchor",
    "_is_answer_to_pending_over_switch": "ask_turn_switch_answer_guard",
    "_log_turn_intent_diagnostics": "ask_turn_intent_diagnostics",
    "_seed_product_select_from_anchor": "ask_turn_seed_product_anchor",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_turn_switch.{mod_name}")
    return getattr(mod, name)
