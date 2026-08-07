"""Post-resolution enrichment helpers: type ancestors + relate stage."""
from __future__ import annotations

import logging

from aryx.broker import Broker
from aryx.models import Relationship
from aryx.relationships import infer_relationship
from aryx.store.entity_store import EntityStore
from aryx.store.ontology_store import OntologyStore

logger = logging.getLogger(__name__)


def _build_type_ancestors(dsn: str, workspace_id: int = 1) -> dict[str, list[str]]:
    """Resolve ancestor chains for every declared type via OntologyStore."""
    ostore = OntologyStore(dsn, workspace_id)
    try:
        types = ostore.list_types()
        out: dict[str, list[str]] = {}
        for t in types:
            if t.parent_type:
                out[t.name] = ostore.ancestors(t.name)
        return out
    except Exception as exc:  # noqa: BLE001 — hierarchy is additive, never block projection
        logger.warning("type ancestors lookup failed; projecting without labels: %s", exc)
        return {}
    finally:
        ostore.close()


def _relate(store: EntityStore, broker: Broker, max_pairs: int) -> int:
    """Infer relationships over candidate entity pairs (frontier tier).

    A naive all-pairs candidate strategy capped at max_pairs; deterministic
    FK/co-occurrence pair selection is a later increment.
    """
    entities = store.list_entities()
    rels: list[Relationship] = []
    pairs = 0
    for i in range(len(entities)):
        for j in range(i + 1, len(entities)):
            if pairs >= max_pairs:
                break
            left, right = entities[i], entities[j]
            name, conf = infer_relationship(left[2], right[2], broker)
            if name:
                rels.append(Relationship(
                    source_entity_id=left[0], target_entity_id=right[0],
                    name=name, confidence=conf))
            pairs += 1
    store.save_relationships(rels)
    return len(rels)


_FLUSH_EVERY = 20


def _relate_isolated(store: EntityStore, broker: Broker,
                     max_candidates: int = 3) -> int:
    """Guarantee every entity in the workspace has at least one relationship.

    Runs as a final, unconditional pass after the best-effort ``_relate()``
    and any FK-linking — those can legitimately find nothing (small local
    model, no declared FK, unrelated types), which otherwise leaves entities
    with zero edges. For each entity still isolated, tries the LLM against a
    few of the most-connected other entities in the workspace; if none of
    them yield a relationship, falls back to a generic ``related_to`` edge
    against the best candidate so no entity is ever left disconnected.

    Persists in batches of ``_FLUSH_EVERY`` as it goes, rather than one
    ``save_relationships`` call after the whole loop. A large document
    ingest (hundreds of isolated entities) means hundreds of sequential LLM
    calls here; any interruption partway through (a job timeout, a transient
    API error, an exception in whatever runs right after this call in the
    caller's pipeline) used to discard every relationship already computed,
    silently degrading a partially-successful run into "0 relationships" —
    exactly the isolated-node symptom this function exists to prevent.
    """
    entities = store.list_entities()
    if len(entities) < 2:
        return 0
    rel_rows = store.list_relationships()
    connected: set[int] = set()
    degree: dict[int, int] = {}
    for s, t, _ in rel_rows:
        connected.add(s)
        connected.add(t)
        degree[s] = degree.get(s, 0) + 1
        degree[t] = degree.get(t, 0) + 1
    isolated = [e for e in entities if e[0] not in connected]
    if not isolated:
        return 0
    logger.info("isolated-node safety net: %d entit(ies) with no relationships",
                len(isolated))
    # Most-connected entities first, so an isolated entity preferentially
    # links into the existing graph rather than to another orphan.
    ranked = sorted(entities, key=lambda e: -degree.get(e[0], 0))
    newly_connected: set[int] = set()
    pending: list[Relationship] = []
    total_saved = 0
    for eid, _etype, payload in isolated:
        if eid in connected or eid in newly_connected:
            continue  # already picked up as someone else's anchor this pass
        candidates = [c for c in ranked if c[0] != eid][:max_candidates]
        if not candidates:
            continue
        linked = False
        for cid, _ctype, cpayload in candidates:
            try:
                name, conf = infer_relationship(payload, cpayload, broker)
            except Exception as exc:  # noqa: BLE001 — a broker/network failure
                # must not sink the whole ingest job; fall through to the
                # next candidate, and ultimately to the generic fallback.
                logger.warning("relate_isolated: infer_relationship failed "
                               "for entity=%s: %s", eid, exc)
                continue
            if name:
                pending.append(Relationship(source_entity_id=eid, target_entity_id=cid,
                                            name=name, confidence=conf))
                linked = True
                newly_connected.add(eid)
                newly_connected.add(cid)
                break
        if not linked:
            cid = candidates[0][0]
            pending.append(Relationship(source_entity_id=eid, target_entity_id=cid,
                                        name="related_to", confidence=0.1))
            newly_connected.add(eid)
            newly_connected.add(cid)
        if len(pending) >= _FLUSH_EVERY:
            store.save_relationships(pending)
            total_saved += len(pending)
            pending = []
    if pending:
        store.save_relationships(pending)
        total_saved += len(pending)
    return total_saved
