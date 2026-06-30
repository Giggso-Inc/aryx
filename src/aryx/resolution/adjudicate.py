"""LLM adjudication (frontier tier): decide the ambiguous middle band."""
from __future__ import annotations

import json
import logging

from aryx.broker import Broker
from aryx.llm import complete_json
from aryx.models import ResolutionRecord

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You decide whether two records describe the SAME real-world entity. "
    "Account for abbreviations, casing, legal suffixes, and typos. "
    "Answer strictly with the schema. Keep 'reason' under 20 words."
)

_PAYLOAD_STR_MAX = 200


def _trim_payload(payload: dict) -> dict:
    """Truncate long string values so the LLM prompt stays within token budget."""
    return {
        k: (v[:_PAYLOAD_STR_MAX] if isinstance(v, str) and len(v) > _PAYLOAD_STR_MAX else v)
        for k, v in payload.items()
    }

_SCHEMA = {
    "type": "object",
    "properties": {
        "same": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["same", "reason"],
    "additionalProperties": False,
}


def adjudicate(left: ResolutionRecord, right: ResolutionRecord, broker: Broker) -> bool:
    """Ask the frontier model whether two records are the same entity.

    Args:
        left: First candidate record.
        right: Second candidate record.
        broker: Model broker; adjudication runs on the frontier tier.

    Returns:
        True if the model judges them the same entity.
    """
    user = json.dumps({"a": _trim_payload(left.payload), "b": _trim_payload(right.payload)})
    result = complete_json(broker, "frontier", _SYSTEM, user, _SCHEMA)
    same = bool(result.get("same"))
    logger.debug("adjudicate same=%s a=%s b=%s", same, left.record_id, right.record_id)
    return same
