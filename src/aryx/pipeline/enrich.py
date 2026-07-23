"""Post-resolution enrichment helpers: type ancestors + relate stage."""
from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any, Iterator

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.models import Relationship
from aryx.relationships import infer_fk_links, infer_relationship
from aryx.store.entity_store import EntityStore
from aryx.store.ontology_store import OntologyStore

logger = logging.getLogger(__name__)


def _drain_with_timeout(
    futures: dict[Future, Any], idle_timeout: float, label: str,
) -> Iterator[tuple[Future, Any]]:
    """Yield (future, key) pairs as they complete; abandon the rest if none
    completes within idle_timeout seconds instead of blocking indefinitely.

    Relate is best-effort enrichment — _relate_isolated() (or a later
    ingest run) still connects anything left isolated — so a single stuck
    LLM call must never hang the whole ingest for the full ARYX_LLM_TIMEOUT.
    Abandoned futures keep running in their worker thread in the background;
    their eventual result is simply discarded (caller must NOT use the
    ThreadPoolExecutor as a `with` block, which would block on exit waiting
    for them — shut it down via `pool.shutdown(wait=False, cancel_futures=True)`).
    """
    pending = set(futures)
    while pending:
        done, pending = wait(pending, timeout=idle_timeout, return_when=FIRST_COMPLETED)
        if not done:
            logger.warning(
                "%s: %d pair(s) still running after %.0fs with no completion — "
                "abandoning the rest of this stage (a later safety net can "
                "still connect them)", label, len(pending), idle_timeout,
            )
            return
        for fut in done:
            yield fut, futures[fut]


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


def _infer_schema_fk_links(store: EntityStore, broker: Broker) -> list[dict[str, Any]]:
    """Identify FK joins across entity type schemas via batched LLM calls.

    Samples one entity per type to get actual column names, then asks the LLM
    which attributes form FK relationships between types.  The caller applies
    the result via link_by_attribute which creates edges for ALL matching
    entities — not just the handful sampled for _relate.

    When there are more than _BATCH_SIZE types, the schemas are split into
    overlapping batches so each LLM call stays within the token budget.
    Each batch always contains the "anchor" type (the one with the most FK-like
    attributes) so cross-batch FK links involving the anchor are discovered.
    """
    try:
        sample = store.list_entities_typed_sample(1)
    except Exception:  # noqa: BLE001 — schema FK inference is best-effort
        logger.exception("_infer_schema_fk_links: typed sample query failed — skipping")
        return []
    if len(sample) < 2:
        return []

    _MAX_SCHEMA_ATTRS = 8   # reduced per-type to fit more types per call
    _BATCH_SIZE = 8          # max types per LLM call — keeps output under 768 tok
    _SNAKE_FK = ("_id", "_code", "_key", "_ref", "_type", "_no", "_num")
    _CAMEL_FK = ("Id", "Code", "Key", "Ref", "Type", "No", "Num")

    type_schemas: dict[str, dict] = {}
    for _eid, etype, attrs in sample:
        public_attrs = [k for k in attrs if not k.startswith("_")]
        fk_first = [
            k for k in public_attrs
            if k.lower().endswith(_SNAKE_FK) or k.endswith(_CAMEL_FK)
        ]
        other_attrs = [k for k in public_attrs if k not in set(fk_first)]
        schema_attrs = (fk_first + other_attrs)[:_MAX_SCHEMA_ATTRS]
        type_schemas[etype] = {
            "attrs": schema_attrs,
            "match_keys": [],
            "_fk_count": len(fk_first),
        }

    # Anchor = type with most FK-like columns; always included in each batch
    # so that cross-batch FK links involving the anchor are detected.
    anchor_type = max(type_schemas, key=lambda t: type_schemas[t]["_fk_count"])
    non_anchor = [t for t in type_schemas if t != anchor_type]

    # Clean up internal key before sending to LLM.
    for t in type_schemas:
        type_schemas[t].pop("_fk_count", None)

    all_links: list[dict[str, Any]] = []
    seen: set[tuple] = set()

    # Build batches: anchor + up to (_BATCH_SIZE - 1) other types.
    batch_size = _BATCH_SIZE - 1
    batches = [
        non_anchor[i: i + batch_size]
        for i in range(0, max(1, len(non_anchor)), batch_size)
    ] or [[]]

    for batch_types in batches:
        batch_keys = [anchor_type] + batch_types
        batch_schemas = {t: type_schemas[t] for t in batch_keys if t in type_schemas}
        try:
            links = infer_fk_links(batch_schemas, broker)
        except Exception:  # noqa: BLE001 — schema inference is best-effort
            logger.exception("schema FK inference failed for batch %s — skipping", batch_keys)
            continue
        for lnk in links:
            key = (lnk.get("source_type"), lnk.get("source_attr"),
                   lnk.get("target_type"), lnk.get("target_attr"))
            if key not in seen:
                seen.add(key)
                all_links.append(lnk)

    if all_links:
        logger.info(
            "schema FK inference found %d link(s) across %d batch(es): %s",
            len(all_links), len(batches), all_links,
        )
    return all_links


def _relate_isolated(store: EntityStore, broker: Broker) -> int:
    """Connect isolated entity types via a few LLM calls per type, not per entity.

    Runs after _relate, schema_fk, and link_by_attribute. Operates type-aware:
    tries up to relate_isolated_max_anchors LLM inference calls per isolated
    type — one per candidate anchor type, stopping at the first confirmed
    relationship — then if related=true creates one edge per isolated entity
    of that type to the confirmed anchor entity. This is O(isolated_types ×
    max_anchors), not O(isolated_entities), keeping the cost bounded even for
    large XML files with thousands of entities.

    For the small-file CSV case (a handful of unreferenced supplier rows), the
    cost is trivially low. For large XML files with 20+ types, at most ~20 LLM
    calls are made regardless of how many individual entities are isolated.
    """
    cfg = get_settings()

    # Single anti-join query: entities with no relationship edge (W1 fix).
    isolated_rows = store.list_isolated_entities()

    # Sample one anchor entity per type — used as the inference partner when
    # an isolated type needs an LLM call.
    anchors_sample = store.list_entities_typed_sample(1)
    anchors: dict[str, tuple[int, str, dict]] = {
        etype: (eid, etype, attrs)
        for eid, etype, attrs in anchors_sample
    }
    if len(anchors) < 2:
        return 0  # need at least two types for cross-type inference

    # Group isolated entities by type using the anti-join result directly.
    isolated_by_type: dict[str, list[tuple[int, str, dict]]] = defaultdict(list)
    for eid, etype, attrs in isolated_rows:
        isolated_by_type[etype].append((eid, etype, attrs))

    if not isolated_by_type:
        logger.debug("_relate_isolated: no isolated entities — skipping")
        return 0

    total_isolated = sum(len(v) for v in isolated_by_type.values())
    logger.info(
        "_relate_isolated: %d isolated entity(ies) across %d type(s)",
        total_isolated, len(isolated_by_type),
    )

    max_attrs = cfg.relate_max_attrs

    def _trim(attrs: dict, ontology_type: str) -> dict:
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

    def _anchor_candidates(iso_type: str) -> list[tuple[int, str, dict]]:
        """Return up to relate_isolated_max_anchors anchor entities from
        OTHER types, to try in turn. Previously only the first non-matching
        type in dict order was ever tried — a genuine relationship to a
        DIFFERENT type was permanently missed whenever that one pairing
        came back unrelated (a real incident: a poorly-keyed 300K-row sheet
        stayed isolated across an entire dataset because its one fixed
        anchor happened to be a poor match, even after the LLM call itself
        started working correctly)."""
        candidates = [anchor for t, anchor in anchors.items() if t != iso_type]
        return candidates[:cfg.relate_isolated_max_anchors]

    def _infer_type(iso_type: str, sample_entity: tuple[int, str, dict]) -> tuple[str, int, str | None, float]:
        """Try each candidate anchor in turn, stopping at the first confirmed
        relationship. Bounded by relate_isolated_max_anchors, not by how many
        entities are isolated.

        One candidate's call raising (e.g. the model returning empty or
        malformed JSON — observed in production) must not abort every
        remaining candidate for this type: that would silently collapse the
        multi-anchor retry back into the original single-shot behavior
        whenever the FIRST candidate happened to error rather than cleanly
        answer "unrelated". Each candidate is tried independently; the type
        is only given up on after every candidate has either errored or
        come back unrelated.
        """
        _, iso_type_, iso_attrs = sample_entity
        left = _trim(iso_attrs, iso_type_)
        last_result: tuple[str, int, str | None, float] = (iso_type, -1, None, 0.0)
        for a_id, a_type, a_attrs in _anchor_candidates(iso_type):
            try:
                name, conf = infer_relationship(left, _trim(a_attrs, a_type), broker)
            except Exception as exc:  # noqa: BLE001 — try the next candidate, don't abort the type
                logger.warning(
                    "_relate_isolated type=%s anchor_type=%s inference failed, "
                    "trying next candidate: %s", iso_type, a_type, exc,
                )
                last_result = (iso_type, -1, None, 0.0)
                continue
            if name:
                return iso_type, a_id, name, conf
            last_result = (iso_type, a_id, name, conf)
        return last_result

    # ONE LLM call per isolated type (not per entity).
    rels: list[Relationship] = []
    pool = ThreadPoolExecutor(max_workers=cfg.relate_workers)
    try:
        futures = {
            pool.submit(_infer_type, iso_type, entities[0]): iso_type
            for iso_type, entities in isolated_by_type.items()
        }
        # This IS the safety net (runs regardless of the best-effort _relate()
        # stage), so it must be at least as resilient as _relate() itself: one
        # flaky/stuck type must not stop the rest of the isolated types from
        # being connected, or block the run indefinitely.
        for fut, iso_type in _drain_with_timeout(futures, cfg.relate_pair_timeout, "_relate_isolated"):
            try:
                iso_type, anchor_id, name, conf = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("_relate_isolated type=%s inference failed, skipping: %s",
                               iso_type, exc)
                continue
            if name and anchor_id != -1:
                # Create one edge per isolated entity of this type → anchor.
                for iso_id, _, _ in isolated_by_type[iso_type]:
                    rels.append(Relationship(
                        source_entity_id=iso_id,
                        target_entity_id=anchor_id,
                        name=name,
                        confidence=conf,
                    ))
                logger.info(
                    "_relate_isolated: type=%s linked %d entity(ies) via '%s'",
                    iso_type, len(isolated_by_type[iso_type]), name,
                )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if rels:
        store.save_relationships(rels)
    logger.info(
        "_relate_isolated: linked %d / %d isolated entity(ies) (%d type(s) confirmed)",
        len(rels), total_isolated,
        sum(1 for iso_type in isolated_by_type if any(
            r.source_entity_id == isolated_by_type[iso_type][0][0] for r in rels
        )),
    )
    return len(rels)
