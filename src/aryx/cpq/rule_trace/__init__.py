"""CPQ rule-firing trace/audit package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_OpenTrace": "rule_trace_state",
    "_get_or_open": "rule_trace",
    "_store": "rule_trace",
    "_trace_dir": "rule_trace_io",
    "bind_context": "rule_trace_state",
    "bind_pass": "rule_trace_state",
    "record_fire": "rule_trace",
    "seal": "rule_trace",
    "sweep_orphans": "rule_trace",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.rule_trace.{mod_name}")
    return getattr(mod, name)
