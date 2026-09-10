"""Ask-turn stale-constraint API package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_BASE_MODEL_VN": "ask_invalidate_stale_base_model",
    "_invalidate_stale_base_model": "ask_invalidate_stale_base_model",
    "_reask_stale_constraint_violations": "ask_stale_constraint_reask",
    "build_stale_reask_prompt": "ask_stale_constraint_prompt",
    "handle_conflicted_violations": "ask_stale_constraint_conflicted",
    "silently_reresolve_hard_excluded": "ask_stale_constraint_silent_resolve",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_stale_constraint.{mod_name}")
    return getattr(mod, name)
