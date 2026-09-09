"""CPQ intent-schema package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "ChangeTarget": "intent_schema_result",
    "Confidence": "intent_schema_enums",
    "GATEWAY_INTENT_JSON_SCHEMA": "intent_schema_gateway",
    "GatewayIntentResult": "intent_schema_gateway",
    "INTENT_RESULT_JSON_SCHEMA": "intent_schema_result",
    "IntentCategory": "intent_schema_enums",
    "IntentResult": "intent_schema_result",
    "_GATEWAY_NO_TARGET_CATEGORIES": "intent_schema_gateway",
    "_is_signed_digit_quantity_text": "intent_schema_gateway",
    "parse_gateway_intent": "intent_schema_gateway",
    "parse_intent_result": "intent_schema_result",
    "validate_gateway_quarantine": "intent_schema_gateway",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.intent_schema.{mod_name}")
    return getattr(mod, name)
