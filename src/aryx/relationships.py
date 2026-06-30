"""Relationship inference (stage 8): name the edge between two entities.

Callable, like the mapping agent. Deterministic FK/co-occurrence-driven pair
selection is a follow-on (it needs FK hints captured at ingestion); this
provides the frontier-tier judgement for a given candidate pair.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from aryx.broker import Broker
from aryx.llm import complete_json

_FK_INFER_SYSTEM = (
    "You are a data-schema analyst. Given a list of entity types and their "
    "attribute names, identify foreign-key relationships that exist between them. "
    "A FK relationship exists when one entity type holds an attribute whose VALUE "
    "will exactly match another entity type's primary identifier (match key). "
    "For each FK relationship return: source_type, source_attr, target_type, "
    "target_attr, and a semantic relationship name in SCREAMING_SNAKE_CASE "
    "(e.g. IDENTIFIED_BY, CANCELS, STANDARDIZES, HAS_SUPPLIER, BELONGS_TO_CLASS). "
    "The name should read as 'source IS [name] target'. "
    "Only return confident FK joins — skip vague or ambiguous attribute overlaps."
)

_FK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_type": {"type": "string"},
                    "source_attr": {"type": "string"},
                    "target_type": {"type": "string"},
                    "target_attr": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["source_type", "source_attr",
                             "target_type", "target_attr", "name"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["links"],
    "additionalProperties": False,
}

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You decide whether two entities are related and, if so, name the directed "
    "relationship from A to B in lowercase snake_case "
    "(e.g. contains, part_of, belongs_to, connected_to, has_component, references, "
    "has_status, replaces, has_parent). "
    "Use '_ontology_type' and '_element_type' fields to understand each entity's domain. "
    "STRUCTURAL RULES — return related=true with confidence >= 0.9 when: "
    "(1) entity B has an attribute like '{TypeA}_id' whose value matches entity A's 'id'; "
    "(2) both entities share a common code/key attribute with the same value "
    "— they describe the same real-world object from different angles; "
    "(3) entity A has a reference column whose value matches entity B's primary "
    "code attribute. "
    "Set related=false only when the entities are clearly from unrelated domains."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "related": {"type": "boolean"},
        "name": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["related", "name", "confidence"],
    "additionalProperties": False,
}


def infer_relationship(
    left: dict[str, Any], right: dict[str, Any], broker: Broker
) -> tuple[str | None, float]:
    """Ask the frontier model what relationship links A to B, if any.

    Args:
        left: Attributes of entity A (the source).
        right: Attributes of entity B (the target).
        broker: Model broker; inference runs on the frontier tier.

    Returns:
        (relationship_name, confidence), or (None, 0.0) if unrelated.
    """
    user = json.dumps({"a": left, "b": right})
    result = complete_json(broker, "frontier", _SYSTEM, user, _SCHEMA)
    if not result.get("related"):
        return None, 0.0
    name = str(result["name"])
    confidence = float(result.get("confidence", 0.0))
    logger.info("relationship inferred name=%s conf=%.2f", name, confidence)
    return name, confidence


def infer_fk_links(
    type_schemas: dict[str, dict[str, Any]],
    broker: Broker,
) -> list[dict[str, Any]]:
    """Ask the LLM to identify FK relationships across multiple entity type schemas.

    Args:
        type_schemas: Mapping of {type_name: {"attrs": [col, ...], "match_keys": [col, ...]}}
        broker: Model broker; inference runs on the frontier tier.

    Returns:
        List of FK link specs: [{source_type, source_attr, target_type, target_attr, name}]
    """
    user = json.dumps({"types": type_schemas})
    try:
        result = complete_json(broker, "frontier", _FK_INFER_SYSTEM, user, _FK_SCHEMA)
    except Exception:  # noqa: BLE001
        logger.exception("FK schema inference failed — returning empty list")
        return []
    links = result.get("links") or []
    logger.info("FK schema inference found %d link(s): %s", len(links), links)
    return [lnk for lnk in links if isinstance(lnk, dict)]
