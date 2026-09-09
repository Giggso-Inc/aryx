"""Ask-turn response-building API package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_beautify_mandatory_block": "ask_mandatory_block_splice",
    "_build_country_change_response": "ask_build_country_change_response",
    "_build_no_value_response": "ask_build_no_value_response",
    "_build_product_quantity_change_response": "ask_build_product_quantity_response",
    "_build_show_summary_response": "ask_build_show_summary_response",
    "_build_summary_narration_user_prompt": "ask_cpq_summary_prompt",
    "_cpq_summary_text": "ask_cpq_summary_text",
    "_deterministic_cpq_gate": "ask_finish_cpq_result",
    "_finish_cpq_result": "ask_finish_cpq_result",
    "_labels_already_shown": "ask_mandatory_block_splice",
    "_narrate_cpq_summary": "ask_cpq_summary_narrate",
    "_route_quote": "ask_finish_cpq_result",
    "_splice_mandatory_block_into_summary": "ask_mandatory_block_splice",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_response_building.{mod_name}")
    return getattr(mod, name)
