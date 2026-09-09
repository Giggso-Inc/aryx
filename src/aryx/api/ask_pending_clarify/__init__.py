"""Ask-turn pending-clarify API package (Phase 8a folder restructuring). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_apply_pending_clarify_resolution": "ask_pending_clarify_apply",
    "_catalog_wide_naming_parts": "ask_pending_clarify_constants",
    "_clear_pending_clarify": "ask_pending_clarify_apply",
    "_ground_clarify_candidates": "ask_pending_clarify_grounding",
    "_grounded_clarify_prompt": "ask_pending_clarify_prompt",
    "_handle_pending_clarify_turn": "ask_pending_clarify_turn",
    "_llm_classify_pending_clarify_reply": "ask_pending_clarify_llm_classify",
    "_match_pending_clarify_reply": "ask_pending_clarify_match",
    "_reply_matches_attr_option": "ask_pending_clarify_match",
    "_score_clarify_candidates": "ask_pending_clarify_scoring",
    "_set_pending_clarify_and_answer": "ask_pending_clarify_answer",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_pending_clarify.{mod_name}")
    return getattr(mod, name)
