"""Ask-turn model-leaf resolution API package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_build_model_leaf_ask_prompt": "ask_model_leaf_ask_prompt",
    "_norm_leaf": "ask_model_leaf_norm",
    "_resolve_model_leaf": "ask_model_leaf_resolve",
    "_resolve_pending_model_leaf_reply": "ask_model_leaf_pending_reply",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_model_leaf.{mod_name}")
    return getattr(mod, name)
