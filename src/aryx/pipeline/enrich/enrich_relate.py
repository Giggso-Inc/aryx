"""Best-effort pairwise relationship inference over a type-aware sample of
entities — the frontier-tier relate stage.

Split out of `pipeline/enrich.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.models import Relationship
from aryx.pipeline.enrich.enrich_drain import _drain_with_timeout
from aryx.relationships import infer_relationship
from aryx.store.entity_store import EntityStore

logger = logging.getLogger(__name__)


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

    # max_pairs is a true hard cap — schema_fk covers type-level FK discovery
    # via a single LLM call across all schemas, so _relate pairs only need to
    # sample representative cross-type combinations, not exhaust every combo.
    # With 19 types the old formula inflated to 171 pairs regardless of the
    # setting, making ARYX_MAX_RELATE_PAIRS ineffective for large ontologies.
    n_cross_combos = n_types * (n_types - 1) // 2
    effective_pairs = min(max_pairs, n_cross_combos)
    logger.info(
        "_relate: %d type(s), %d cross-type combos, effective_pairs=%d (cap=%d)",
        n_types, n_cross_combos, effective_pairs, max_pairs,
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

    # Coverage guarantee: ensure every entity type appears in at least one
    # candidate pair.  The round-robin stops at effective_pairs so tail types
    # (high index) can be represented only once — and if that one LLM call
    # returns related=false the type stays isolated forever.  We force one
    # extra pair per uncovered type against the richest-sampled type.
    # These extra pairs are outside the original budget but bounded by n_types
    # so the wall-clock cost is at most one extra LLM-worker batch.
    covered: set[str] = set()
    for left, right in candidates:
        covered.add(left[1])
        covered.add(right[1])
    uncovered = [t for t in types if t not in covered]
    if uncovered:
        # Pick the type with the most sampled entities as the coverage anchor.
        anchor = max(types, key=lambda t: len(by_type[t]))
        for t in uncovered:
            if t == anchor:
                continue  # single-type workspace — no cross-type pair possible
            anchor_list = by_type[anchor]
            t_list = by_type[t]
            if anchor_list and t_list:
                candidates.append((anchor_list[0], t_list[0]))
                logger.info(
                    "_relate: coverage pair added for type %s (anchor=%s)",
                    t, anchor,
                )

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
    infer_failures = 0
    pool = ThreadPoolExecutor(max_workers=relate_workers)
    try:
        futures = {
            pool.submit(_infer, left, right): (left[0], right[0])
            for left, right in candidates
        }
        for fut, pair in _drain_with_timeout(futures, cfg.relate_pair_timeout, "_relate"):
            try:
                src_id, tgt_id, name, conf = fut.result()
            except Exception as exc:  # noqa: BLE001 — one flaky LLM reply must not
                # kill the run: FK-link and graph projection execute AFTER relate,
                # so an uncaught error here silently destroys the whole ingest.
                infer_failures += 1
                logger.warning("_relate pair=%s inference failed, skipping: %s",
                               pair, exc)
                continue
            if name:
                rels.append(Relationship(
                    source_entity_id=src_id, target_entity_id=tgt_id,
                    name=name, confidence=conf))
    finally:
        # wait=False: don't block on any pair abandoned by _drain_with_timeout —
        # they finish in the background and their result is simply discarded.
        pool.shutdown(wait=False, cancel_futures=True)
    if infer_failures:
        logger.warning("_relate %d/%d pair inference(s) failed and were skipped",
                       infer_failures, len(candidates))
    store.save_relationships(rels)
    logger.info(
        "_relate evaluated %d pair(s) across %d type(s), found %d relationship(s) "
        "(budget=%d, coverage_extras=%d)",
        len(candidates), n_types, len(rels),
        effective_pairs, max(0, len(candidates) - effective_pairs),
    )
    return len(rels)
