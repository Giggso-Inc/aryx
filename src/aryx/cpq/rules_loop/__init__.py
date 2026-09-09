"""CPQ rules-evaluation-loop package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "LoopScope": "rules_loop_state",
    "LoopState": "rules_loop_state",
    "evaluate_rules_loop": "rules_loop",
    "run_autofill_step": "rules_loop_pass_autofill",
    "run_early_pass": "rules_loop_pass_early",
    "run_late_pass": "rules_loop_pass_late",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.rules_loop.{mod_name}")
    return getattr(mod, name)
