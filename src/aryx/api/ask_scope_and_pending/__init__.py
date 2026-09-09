"""Ask-turn scope-reask and pending-exclusion API package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_auto_resolve_singleton_pending": "ask_singleton_pending",
    "_build_scope_family_only_response": "ask_scope_reask_responses",
    "_build_scope_skip_response": "ask_scope_reask_responses",
    "_constrain_excluding_rejected": "ask_change_decline_and_scope_memory",
    "_extract_replacement_clause": "ask_change_decline_and_scope_memory",
    "_hard_exclude_from_pending": "ask_pending_exclusion",
    "_is_change_value_decline": "ask_change_decline_and_scope_memory",
    "_is_global_change_decline": "ask_change_decline_and_scope_memory",
    "_remember_attr_scope": "ask_change_decline_and_scope_memory",
    "_resolve_scope_reply": "ask_scope_reask_responses",
    "_scoped_reask_response": "ask_scope_reask_responses",
    "resolve_hard_excluded_attr": "ask_pending_exclusion_resolve",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_scope_and_pending.{mod_name}")
    return getattr(mod, name)
