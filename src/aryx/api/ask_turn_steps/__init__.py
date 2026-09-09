"""Ask-turn step-processing API package (Phase 8a folder restructuring). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_build_change_collision_no_value_response": "ask_step678_change_collision",
    "_build_product_family_prompt_or_resolve": "ask_step1_product_family_prompt",
    "_handle_review_status_routing": "ask_step678_review_status",
    "_resolve_pending_change_collision": "ask_step678_change_collision",
    "_resolve_pending_change_no_value": "ask_step2_pending_change_no_value",
    "_resolve_pending_options_collision": "ask_step678_options_collision",
    "_resolve_pending_question_collision": "ask_step8_qa_and_collision",
    "_resolve_system_initiated_collision": "ask_step678_options_collision",
    "_step10_blocked_removal_gap": "ask_step10_blocked_removal",
    "_step10_commit_and_drain": "ask_step10_commit_and_drain",
    "_step10_enforce_siblings_and_multi_hint": "ask_step10_sibling_and_multi_hint",
    "_step10_recompute_pending": "ask_step10_recompute_pending",
    "_step10_run_rule_eval_loop": "ask_step10_rule_eval_loop",
    "_step11_build_turn_response": "ask_step11_build_response",
    "_step11_completion_response": "ask_step11_completion_responses",
    "_step11_grid_gap_response": "ask_step11_completion_responses",
    "_step11_on_request_response": "ask_step11_on_request_response",
    "_step11_stale_reask_response": "ask_step11_completion_responses",
    "_step11_turn_cap_response": "ask_step11_turn_cap_response",
    "_step1_resolve_product_anchor": "ask_step1_product_anchor",
    "_step2_catalog_hints_and_negation": "ask_step2_catalog_hints",
    "_step2_log_rule_consistency_and_array_grid": "ask_step2_rule_consistency",
    "_step2_resolve_and_load": "ask_step2_resolve_and_load",
    "_step2_resolve_product_and_gates": "ask_step2_anchor_gates",
    "_step678_json_or_approval": "ask_step678_json_and_approval",
    "_step6_activation_and_clear": "ask_step678_activation_and_clear",
    "_step6_bulk_and_removal": "ask_step678_bulk_and_removal",
    "_step6_change_collision_detect": "ask_step678_change_collision_detect",
    "_step6_change_dispatch": "ask_step678_change_dispatch",
    "_step6_llm_fallback_classify": "ask_step678_llm_fallback",
    "_step6_no_value_or_nudge": "ask_step678_no_value_and_nudge",
    "_step8_label_collision_and_query": "ask_step8_label_and_query",
    "_step8_mid_config_change": "ask_step8_mid_config_change",
    "_step8_qa_and_pending_collision": "ask_step8_qa_and_collision",
    "_step8_run_pre_step5_gates": "ask_step8_pre_step5_gates",
    "_step9_apply_pending_result": "ask_step9_apply_result",
    "_step9_decline_optional_multiselect": "ask_step9_decline_multiselect",
    "_step9_llm_fallback_match": "ask_step9_llm_fallback_match",
    "_step9_lock_pending_answer": "ask_step9_lock_pending_answer",
    "_step9_low_confidence_response": "ask_step9_miss_response",
    "_step9_match_pending_answer": "ask_step9_match_answer",
    "_step9_options_miss_response": "ask_step9_miss_response",
    "_step9_scope_and_constraint_setup": "ask_step9_scope_setup",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_turn_steps.{mod_name}")
    return getattr(mod, name)
