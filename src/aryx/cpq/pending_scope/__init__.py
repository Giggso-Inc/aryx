"""CPQ pending-scope (candidate reply matching) package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "ScopeKind": "pending_scope_state",
    "ScopeResolve": "pending_scope_resolve",
    "_norm": "pending_scope_resolve",
    "_score": "pending_scope_resolve",
    "candidates_from_attr_options": "pending_scope_state",
    "clear_pending_scope": "pending_scope_state",
    "format_did_you_mean": "pending_scope_messages",
    "is_confident_scope_suggestion": "pending_scope_resolve",
    "log_scope_lost": "pending_scope_messages",
    "log_scope_retained": "pending_scope_messages",
    "resolve_against_scope": "pending_scope_resolve",
    "scope_loop_exit_threshold": "pending_scope_resolve",
    "set_pending_scope": "pending_scope_state",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.pending_scope.{mod_name}")
    return getattr(mod, name)
