"""CPQ intent-gateway (LLM-first turn classification) package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "AskRouteDecision": "intent_gateway",
    "AttrCandidateBundle": "intent_gateway_candidates",
    "GatewayDecision": "intent_gateway",
    "ValueCandidate": "intent_gateway_candidates",
    "_cache_key": "intent_gateway_cache",
    "_deterministic_mutating_signals": "intent_gateway_agreement",
    "_format_candidates_for_prompt": "intent_gateway_candidates",
    "_llm_classify_once": "intent_gateway",
    "_mutating_agrees": "intent_gateway_agreement",
    "_normalize_question": "intent_gateway_cache",
    "_parse_json_object": "intent_gateway",
    "_parse_route": "intent_gateway",
    "_pinned_chat": "intent_gateway",
    "_rank_value_candidates_by_relevance": "intent_gateway_candidates",
    "_store_cache": "intent_gateway_cache",
    "build_candidate_bundles": "intent_gateway_candidates",
    "classify_ask_route": "intent_gateway",
    "classify_intent": "intent_gateway",
    "clear_gateway_cache": "intent_gateway_cache",
    "hard_off_topic": "intent_gateway",
    "map_route_to_det_expectation": "intent_gateway",
    "mark_top_level_route_used": "intent_gateway",
    "resolve_value_from_ref": "intent_gateway_candidates",
    "session_state_hash": "intent_gateway_cache",
    "soft_quote_heuristic": "intent_gateway",
    "top_level_route_used": "intent_gateway",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.intent_gateway.{mod_name}")
    return getattr(mod, name)
