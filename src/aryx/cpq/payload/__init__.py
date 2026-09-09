"""CPQ output-payload assembly package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "PayloadContext": "payload_state",
    "_scope_excluded": "payload_scalar",
    "build_context": "payload_setup",
    "build_payload": "payload_build",
    "display_for": "payload_display",
    "group_array_set_rows": "payload_array_sets",
    "order_payload_keys": "payload_order",
    "serialize_multi_attrs": "payload_multi",
    "serialize_scalar_attrs": "payload_scalar",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.payload.{mod_name}")
    return getattr(mod, name)
