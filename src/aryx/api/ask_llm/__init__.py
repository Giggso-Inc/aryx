"""Ask-turn LLM classification/extraction API package (Phase 8a folder restructuring). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_apply_real_llm_usage": "ask_llm_usage_and_new_request_detect",
    "_build_llm_call_failed_response": "ask_llm_confirm_extract_quantity",
    "_build_pending_state_block": "ask_llm_intent_universal_pending",
    "_llm_classify_change_intent": "ask_llm_classify_change_intent",
    "_llm_classify_intent_core": "ask_llm_intent_core",
    "_llm_classify_intent_universal": "ask_llm_classify_intent_universal",
    "_llm_classify_is_ask_in_scope": "ask_llm_classify_is_ask_in_scope",
    "_llm_classify_is_cpq_question": "ask_llm_classify_is_cpq_question",
    "_llm_classify_scope_reply": "ask_llm_classify_scope_reply",
    "_llm_classify_switch_reply": "ask_llm_switch_reply_and_compound_split",
    "_llm_confirm_and_extract_country": "ask_llm_confirm_extract_country",
    "_llm_confirm_and_extract_quantity": "ask_llm_confirm_extract_quantity",
    "_llm_detect_catalog_enumeration_query": "ask_llm_catalog_enumeration",
    "_llm_detect_change_decline": "ask_llm_topic_switch_and_change_decline",
    "_llm_detect_pending_topic_switch": "ask_llm_topic_switch_and_change_decline",
    "_llm_extract_multi_attr_hints": "ask_llm_extract_multi_attr_hints",
    "_llm_extract_quantity": "ask_llm_extract_quantity_and_country_reply",
    "_llm_resolve_bare_country_reply": "ask_llm_extract_quantity_and_country_reply",
    "_llm_resolve_pending_answer": "ask_llm_resolve_pending_answer",
    "_llm_resolve_quantity_target": "ask_llm_resolve_quantity_target",
    "_llm_split_compound_change_and_question": "ask_llm_switch_reply_and_compound_split",
    "_llm_split_multi_attr_change_request": "ask_llm_split_multi_attr_change",
    "_llm_split_multi_attr_options_query": "ask_llm_split_multi_attr_options",
    "_pending_reply_is_topic_switch": "ask_llm_topic_switch_and_change_decline",
    "_pending_reply_looks_like_new_request": "ask_llm_usage_and_new_request_detect",
    "_quantity_message_might_name_candidate": "ask_llm_resolve_quantity_target",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_llm.{mod_name}")
    return getattr(mod, name)
