"""Post-resolution enrichment helpers: type ancestors + relate stage."""
from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.models import Relationship
from aryx.relationships import infer_fk_links, infer_relationship
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

    Cross-type pairs are evaluated first so the max_pairs budget is spent on
    the most informative edges; same-type pairs fill any remaining budget.

    Uses a type-aware sample (window function PARTITION BY ontology_type) so
    that every entity type in the workspace is represented even when one type
    has vastly more entities than others.
    A plain sequential islice would return only the dominant type and produce
    zero cross-type pairs — leaving all entities as isolated nodes.
    """
    cfg = get_settings()
    relate_workers = cfg.relate_workers
    max_attrs = cfg.relate_max_attrs

    # Samples per type: enough to form several representative pairs per
    # cross-type combination without loading the full entity table.
    # At least 2 (minimum for a pair), capped so we never load more than
    # max_pairs * 10 total rows across all types.
    SAMPLES_PER_TYPE = max(2, min(max_pairs, 10))
    entities = store.list_entities_typed_sample(SAMPLES_PER_TYPE)

    by_type: dict[str, list] = defaultdict(list)
    for e in entities:
        by_type[e[1]].append(e)

    types = list(by_type.keys())
    n_types = len(types)

    # Adaptive budget: cover every cross-type combination at least once so no
    # type pair is silently skipped when max_pairs < k*(k-1)/2.
    # Hard cap at max_pairs * n_types to prevent O(k²) blowup on large ontologies
    # (e.g. 50 types → 1,225 combos at 2 s/call ≈ 40 min without the cap).
    n_cross_combos = n_types * (n_types - 1) // 2
    effective_pairs = min(max(max_pairs, n_cross_combos), max_pairs * n_types)
    if effective_pairs > max_pairs:
        logger.warning(
            "_relate: effective_pairs=%d exceeds max_pairs=%d (k=%d types) — "
            "raise ARYX_MAX_RELATE_PAIRS if coverage is insufficient",
            effective_pairs, max_pairs, n_types,
        )

    candidates: list[tuple] = []

    # Cross-type pairs first — round-robin across ALL type combinations so no
    # single pair dominates the budget when there are 3+ entity types.
    _sentinel = object()
    cross_iters = [
        ((ea, eb) for ea in by_type[types[i]] for eb in by_type[types[j]])
        for i in range(n_types)
        for j in range(i + 1, n_types)
    ]
    active = list(cross_iters)
    while active and len(candidates) < effective_pairs:
        still_active = []
        for it in active:
            pair = next(it, _sentinel)
            if pair is not _sentinel:
                candidates.append(pair)
                still_active.append(it)
                if len(candidates) >= effective_pairs:
                    break
        active = still_active if len(candidates) < effective_pairs else []

    # Fill remaining budget with same-type pairs.
    if len(candidates) < effective_pairs:
        for t_entities in by_type.values():
            for i in range(len(t_entities)):
                for j in range(i + 1, len(t_entities)):
                    candidates.append((t_entities[i], t_entities[j]))
                    if len(candidates) >= effective_pairs:
                        break
                if len(candidates) >= effective_pairs:
                    break
            if len(candidates) >= effective_pairs:
                break

    def _trim(attrs: dict, ontology_type: str) -> dict:
        """Build the attribute dict shown to the LLM for one entity.

        Always injects ``_ontology_type`` (the canonical type name from the
        pipeline) so the model knows the entity domain even when the raw
        attributes contain no ``_element_type`` field (CSV-ingested entities).
        Then includes up to ``max_attrs`` attribute key-value pairs.
        """
        out: dict = {"_ontology_type": ontology_type}
        if "_element_type" in attrs:
            out["_element_type"] = attrs["_element_type"]
        for k, v in attrs.items():
            if k == "_element_type":
                continue
            out[k] = v
            if len(out) >= max_attrs:
                break
        return out

    def _infer(left: tuple, right: tuple) -> tuple[int, int, str | None, float]:
        name, conf = infer_relationship(
            _trim(left[2], left[1]), _trim(right[2], right[1]), broker
        )
        return left[0], right[0], name, conf

    rels: list[Relationship] = []
    with ThreadPoolExecutor(max_workers=relate_workers) as pool:
        futures = {
            pool.submit(_infer, left, right): (left[0], right[0])
            for left, right in candidates[:effective_pairs]
        }
        for fut in as_completed(futures):
            src_id, tgt_id, name, conf = fut.result()
            if name:
                rels.append(Relationship(
                    source_entity_id=src_id, target_entity_id=tgt_id,
                    name=name, confidence=conf))
    store.save_relationships(rels)
    logger.info(
        "_relate evaluated %d pair(s) across %d type(s), found %d relationship(s)",
        len(candidates), n_types, len(rels),
    )
    return len(rels)


def _infer_schema_fk_links(store: EntityStore, broker: Broker) -> list[dict[str, Any]]:
    """One LLM call that identifies FK joins across ALL entity type schemas.

    Samples one entity per type to get actual column names, then asks the LLM
    which attributes form FK relationships between types.  The caller applies
    the result via link_by_attribute which creates edges for ALL matching
    entities — not just the handful sampled for _relate.

    This covers the case where neither column-name patterns (_detect_fk_links)
    nor entity-pair sampling (_relate) find connections — e.g. when a shared
    code column has no recognised FK suffix.
    """
    # One representative entity per type gives us the full attribute schema
    # without loading the whole table.
    sample = store.list_entities_typed_sample(1)
    if len(sample) < 2:
        return []

    type_schemas: dict[str, dict] = {}
    for _eid, etype, attrs in sample:
        type_schemas[etype] = {
            "attrs": [k for k in attrs if not k.startswith("_")],
            "match_keys": [],
        }

    try:
        links = infer_fk_links(type_schemas, broker)
    except Exception:  # noqa: BLE001 — schema inference is best-effort
        logger.exception("schema FK inference failed — skipping")
        return []

    if links:
        logger.info("schema FK inference found %d link(s): %s", len(links), links)
    return links
