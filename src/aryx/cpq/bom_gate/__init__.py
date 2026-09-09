"""CPQ BOM (bill-of-materials) validation gate package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "BomGateResult": "bom_gate_types",
    "StaleConstraintViolation": "bom_gate_types",
    "_is_noise_var": "bom_gate_noise",
    "_utterance_mentions": "bom_gate_provenance",
    "_value_in_options": "bom_gate_provenance",
    "check_provenance": "bom_gate_provenance",
    "find_missing_required_fields": "bom_gate_required",
    "recheck_constraints": "bom_gate_constraints",
    "validate_before_payload": "bom_gate",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.bom_gate.{mod_name}")
    return getattr(mod, name)
