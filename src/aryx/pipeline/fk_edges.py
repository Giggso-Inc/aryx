"""Deterministic FK edges: link entities by a foreign-key-style attribute.

When the ingested rows reference another entity by name (e.g. a support ticket
carries the customer_name), this stage looks up the referenced entity by
attribute equality and writes a typed Relationship. No LLM, no guesswork —
exact matches only.
"""
from __future__ import annotations

import logging

from aryx.models import Relationship
from aryx.store.entity_store import EntityStore

logger = logging.getLogger(__name__)


def _attr(payload: object, key: str) -> str | None:
    """Best-effort string extract from a resolved-entity attributes payload."""
    if isinstance(payload, dict):
        val = payload.get(key)
        return str(val).strip() if val is not None else None
    return None


def link_by_attribute(
    estore: EntityStore, source_type: str, source_attr: str,
    target_type: str, target_attr: str, name: str,
) -> int:
    """Create edges where source_type.source_attr == target_type.target_attr.

    Args:
        estore: Open EntityStore.
        source_type: Ontology type of the row-side entities (e.g. SupportTicket).
        source_attr: Attribute on the source carrying the lookup value.
        target_type: Ontology type of the referent (e.g. Customer).
        target_attr: Attribute on the target whose value must match.
        name: Edge label written into the graph (e.g. HAS_TICKET).

    Returns:
        Number of relationships saved (existing edges are not deduped here).
    """
    entities = list(estore.list_entities())
    target_ids: set[int] = set()
    targets: dict[str, list[int]] = {}
    for tid, ttype, payload in entities:
        if ttype != target_type:
            continue
        target_ids.add(tid)
        key = _attr(payload, target_attr)
        if key:
            targets.setdefault(key.lower(), []).append(tid)

    # Survivorship merge can discard the exact target_attr value another
    # record's FK depends on (one winner is kept, the rest become
    # aryx_attribute_conflict.losing_values). Alias those historical values
    # back to the entity that absorbed them so a merge never silently
    # orphans a relationship someone else points to.
    for value, tid in estore.conflict_aliases(target_attr).items():
        if tid in target_ids and tid not in targets.get(value, []):
            targets.setdefault(value, []).append(tid)

    rels: list[Relationship] = []
    for sid, stype, payload in entities:
        if stype != source_type:
            continue
        ref = _attr(payload, source_attr)
        if not ref:
            continue
        for tid in targets.get(ref.lower(), []):
            if tid != sid:
                rels.append(Relationship(
                    source_entity_id=tid, target_entity_id=sid,
                    name=name, confidence=1.0,
                ))
    if rels:
        estore.save_relationships(rels)
    logger.info("fk-edges %s.%s -> %s.%s name=%s saved=%d",
                source_type, source_attr, target_type, target_attr, name, len(rels))
    return len(rels)
