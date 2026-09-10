"""Ask-turn gateway API package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_gateway_to_intent_result": "ask_gateway_to_intent_result",
    "_resolve_or_reask_ambiguous": "ask_gateway_resolve_or_reask",
    "_should_defer_gateway_to_pending_answer": "ask_gateway_defer_check",
    "_try_compound_split_on_clarify": "ask_gateway_compound_split",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_gateway.{mod_name}")
    return getattr(mod, name)
