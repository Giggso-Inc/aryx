"""Connects isolated entity types via a few LLM calls per type — the safety
net that guarantees zero isolated entities regardless of whether the
best-effort `_relate` stage ran or stalled.

Split out of `pipeline/enrich.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.models import Relationship
from aryx.pipeline.enrich.enrich_drain import _drain_with_timeout
from aryx.relationships import infer_relationship
from aryx.store.entity_store import EntityStore

logger = logging.getLogger(__name__)


def _relate_isolated(
    store: EntityStore, broker: Broker, should_stop: Callable[[], bool] | None = None,
) -> int:
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

    should_stop — optional, checked while draining the per-type inference
    futures below. Previously absent entirely: a cancelled job still ran
    every submitted type's LLM inference to completion (or its individual
    relate_pair_timeout) before this function returned, since nothing
    inside it ever read the job's cancellation state back — the same class
    of bug already fixed for the sibling dimension_link stage (see
    detect_and_link_dimensions's own should_stop docstring). Checked once
    per completed future, not per LLM call inside _infer_type, since a
    single in-flight infer_relationship call can't be interrupted mid-call
    anyway (same documented limitation as dimension_link's fix) — this
    stops picking up NEW results and lets already-running futures finish
    or hit their own timeout, rather than waiting for every type.
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

    def _sample_entities(iso_type: str) -> list[tuple[int, str, dict]]:
        """Return up to relate_isolated_max_samples_per_type isolated
        entities of this type, to try in turn. Previously only the FIRST
        isolated entity of a type was ever tried — for a type whose members
        vary a lot (a real incident: a document extractor's short,
        list-style mentions of one type, e.g. one member being "Region 1"
        and another "untapped industry verticals" — very different in
        substance despite sharing a type), the single sampled member easily
        missed a real relationship that a DIFFERENT member of the same type
        would have shown against the very same anchor.
        """
        return isolated_by_type[iso_type][:cfg.relate_isolated_max_samples_per_type]

    def _infer_type(iso_type: str) -> tuple[str, int, str | None, float]:
        """Try each sample entity of this isolated type in turn, and for
        each, each candidate anchor, stopping at the first confirmed
        relationship. Bounded by relate_isolated_max_samples_per_type x
        relate_isolated_max_anchors, not by how many entities are isolated.

        One candidate's call raising (e.g. the model returning empty or
        malformed JSON — observed in production) must not abort every
        remaining candidate for this type: that would silently collapse the
        multi-anchor retry back into the original single-shot behavior
        whenever the FIRST candidate happened to error rather than cleanly
        answer "unrelated". Each candidate is tried independently; the type
        is only given up on after every sample-entity x anchor combination
        has either errored or come back unrelated.
        """
        anchor_candidates = _anchor_candidates(iso_type)
        last_result: tuple[str, int, str | None, float] = (iso_type, -1, None, 0.0)
        for sample_entity in _sample_entities(iso_type):
            _, iso_type_, iso_attrs = sample_entity
            left = _trim(iso_attrs, iso_type_)
            for a_id, a_type, a_attrs in anchor_candidates:
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
            pool.submit(_infer_type, iso_type): iso_type
            for iso_type in isolated_by_type
        }
        # This IS the safety net (runs regardless of the best-effort _relate()
        # stage), so it must be at least as resilient as _relate() itself: one
        # flaky/stuck type must not stop the rest of the isolated types from
        # being connected, or block the run indefinitely.
        types_processed = 0
        for fut, iso_type in _drain_with_timeout(futures, cfg.relate_pair_timeout, "_relate_isolated"):
            if should_stop is not None and should_stop():
                logger.warning(
                    "_relate_isolated: job cancelled — stopping after %d/%d type(s), "
                    "%d edge(s) linked so far", types_processed, len(futures), len(rels),
                )
                break
            types_processed += 1
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
    linked_source_ids = {r.source_entity_id for r in rels}
    logger.info(
        "_relate_isolated: linked %d / %d isolated entity(ies) (%d type(s) confirmed)",
        len(rels), total_isolated,
        sum(
            1 for iso_type in isolated_by_type
            if linked_source_ids.intersection(t[0] for t in isolated_by_type[iso_type])
        ),
    )
    return len(rels)
