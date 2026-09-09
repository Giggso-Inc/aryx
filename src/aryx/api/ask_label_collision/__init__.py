"""Ask-turn label-collision API package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_compose_disambiguation_question": "ask_label_collision_detect_and_compose",
    "_is_decline_reply": "ask_decline_reply_and_label_collision_llm",
    "_label_collision_for": "ask_label_collision_detect_and_compose",
    "_label_collision_prompt": "ask_label_collision_prompt_and_narrow",
    "_llm_resolve_label_collision": "ask_decline_reply_and_label_collision_llm",
    "_narrow_label_collision": "ask_label_collision_prompt_and_narrow",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_label_collision.{mod_name}")
    return getattr(mod, name)
