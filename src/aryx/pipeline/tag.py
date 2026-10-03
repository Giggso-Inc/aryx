"""Field tagging (stage 4): cheap-tier semantic typing of profiled fields."""
from __future__ import annotations

import json
import logging
import time

from aryx.broker import Broker
from aryx.llm import complete_json
from aryx.models import FieldProfile, FieldTag
from aryx.raven_log import current_run_id, raven_log

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You label data fields with a concise semantic type and flag PII. "
    "Use lowercase snake_case types such as email, person_name, country_code, "
    "phone, address, date, identifier, foreign_key, amount, free_text."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "semantic_type": {"type": "string"},
                    "is_pii": {"type": "boolean"},
                },
                "required": ["field", "semantic_type", "is_pii"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tags"],
    "additionalProperties": False,
}


def tag_fields(profiles: list[FieldProfile], broker: Broker) -> list[FieldTag]:
    """Assign a semantic type + PII flag to each profiled field (cheap tier).

    Args:
        profiles: Field profiles from the profile stage.
        broker: Model broker; tagging runs on the cheap tier.

    Returns:
        One FieldTag per field the model labelled.
    """
    if not profiles:
        raven_log("DEBUG", "P4", "ingest.tag.skipped no profiles to tag",
                  context={"selected_option": "skip", "available_options": ["skip", "tag"],
                           "reason_code": "NO_PROFILES", "policy_version": "tag_fields_v1",
                           "fields_in": 0})
        return []
    user = json.dumps(
        [{"field": p.field, "samples": p.samples, "distinct": p.distinct} for p in profiles]
    )
    started = time.monotonic()
    try:
        result = complete_json(broker, "cheap", _SYSTEM, user, _SCHEMA)
    except Exception as exc:
        raven_log("ERROR", "P2", "ingest.tag.failed field tagging LLM call failed",
                  error_code="ARYX_ING_TAG_FAILED",
                  context={"dependency_name": "llm", "operation": "tag_fields",
                           "duration_ms": int((time.monotonic() - started) * 1000),
                           "result": "error", "error_class": type(exc).__name__, "attempt": 1,
                           "trace_id": current_run_id(), "fields_in": len(profiles)})
        raise
    tags = [FieldTag(**t) for t in result.get("tags", [])]
    logger.info("tagged fields count=%d", len(tags))
    untagged = len(profiles) - len(tags)
    duration_ms = int((time.monotonic() - started) * 1000)
    ctx = {"dependency_name": "llm", "operation": "tag_fields", "duration_ms": duration_ms,
           "result": "partial" if untagged > 0 else "ok", "error_class": None, "attempt": 1,
           "trace_id": current_run_id(), "fields_in": len(profiles), "tags_out": len(tags),
           "untagged": max(untagged, 0), "pii_fields": sum(1 for t in tags if t.is_pii)}
    if untagged > 0:
        raven_log("WARN", "P3", "ingest.tag.incomplete the model labelled fewer fields than given",
                  error_code="ARYX_ING_TAG_INCOMPLETE", context=ctx)
    else:
        raven_log("DEBUG", "P4", "ingest.tag.completed", context=ctx)
    return tags
