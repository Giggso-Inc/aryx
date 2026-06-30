"""Entity resolution funnel (stage 7): block -> score -> adjudicate -> cluster.

Thresholds (env-tunable, defaults from the G9 sweep — see DECISIONS.md):
  ARYX_ER_AUTO_MERGE   >= this -> auto-merge                  (default 0.92)
  ARYX_ER_ADJUDICATE   [this, AUTO_MERGE) -> LLM adjudicates  (default 0.90)
  ARYX_ER_REVIEW       [this, ADJUDICATE) -> human queue      (default 0.75)
  below REVIEW -> auto-reject (never merged, never queued)

Pairs routed to the human queue are treated as NON-merge for the current run
(conservative: a wrong merge is worse than a missed merge in audited domains).
A later human approval unions the entities via apply_decision (G10).
"""
from __future__ import annotations

import logging

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.models import EntityMember, ResolutionRecord, ResolvedEntity
from aryx.resolution.adjudicate import adjudicate
from aryx.resolution.classical import block, score_pair
from aryx.resolution.cluster import UnionFind, golden_record_weighted
from aryx.resolution.confidence import cluster_confidence, cluster_edges
from aryx.resolution.golden import golden_record_with_policy
from aryx.resolution.review_queue import ReviewSink
from aryx.resolution.survivorship import SurvivorshipPolicy

logger = logging.getLogger(__name__)


def _block_embeddings(
    records: list[ResolutionRecord], broker: Broker
) -> dict[int, list[float]]:
    """Embed a block's texts in small batches; empty dict if unavailable.

    Short-circuits when both auto-merge and adjudicate thresholds are 1.0 —
    in that mode only exact duplicates can merge, and string scoring detects
    those without needing vectors.
    """
    cfg = get_settings()
    if cfg.er_auto_merge >= 1.0 and cfg.er_adjudicate >= 1.0:
        return {}
    out: dict[int, list[float]] = {}
    for start in range(0, len(records), cfg.embed_batch_size):
        batch = records[start : start + cfg.embed_batch_size]
        try:
            vectors = broker.embed([r.text for r in batch])
            if vectors:
                for r, v in zip(batch, vectors):
                    out[r.record_id] = v
        except Exception:  # noqa: BLE001
            pass  # fall back to string-only for this batch
    return out


def _route_pair(left: ResolutionRecord, right: ResolutionRecord, score: float,
                broker: Broker, union: UnionFind,
                review: ReviewSink | None) -> None:
    """Apply the four-way threshold routing to one scored pair."""
    cfg = get_settings()
    auto = cfg.er_auto_merge
    adj = cfg.er_adjudicate
    rev = cfg.er_review
    if score >= auto:
        union.union(left.record_id, right.record_id)
        return
    if score >= adj:
        try:
            same = adjudicate(left, right, broker)
            if review is not None:
                review.offer(left, right, score, llm_verdict=same,
                             llm_reason="llm adjudication", status="auto_llm")
            if same:
                union.union(left.record_id, right.record_id)
        except Exception as exc:  # noqa: BLE001 — LLM down -> human decides
            logger.warning("adjudication failed, queueing for human: %s", exc)
            if review is not None:
                review.offer(left, right, score, llm_verdict=None,
                             llm_reason=f"llm unavailable: {exc}",
                             status="pending")
        return
    if score >= rev and review is not None:
        review.offer(left, right, score, llm_verdict=None,
                     llm_reason=None, status="pending")


def _materialize(member_ids: list[int], by_id: dict[int, ResolutionRecord],
                 pair_scores: dict[tuple[int, int], float],
                 ontology_type: str,
                 policy: SurvivorshipPolicy | None) -> ResolvedEntity:
    """Build one golden-record entity from a cluster's members."""
    records_in = [by_id[mid] for mid in member_ids]
    if policy is not None:
        members = [{"payload": r.payload, "record_id": r.record_id,
                    "source_system": r.source_system,
                    "cleaned_at": r.cleaned_at} for r in records_in]
        merged, provenance, conflicts = golden_record_with_policy(members, policy)
    else:
        merged = golden_record_weighted(
            [r.payload for r in records_in], member_ids, pair_scores)
        provenance = merged.pop("_provenance", None)
        conflicts = None
    edges = cluster_edges(member_ids, pair_scores, get_settings().er_adjudicate)
    return ResolvedEntity(
        ontology_type=ontology_type, attributes=merged,
        confidence=cluster_confidence(edges, len(member_ids)),
        provenance=provenance, conflicts=conflicts or None,
    )


def resolve(
    records: list[ResolutionRecord],
    broker: Broker,
    ontology_type: str,
    policy: SurvivorshipPolicy | None = None,
    review: ReviewSink | None = None,
) -> list[tuple[ResolvedEntity, list[EntityMember]]]:
    """Resolve records into canonical entities via the funnel.

    Args:
        records: Landed records prepared for matching.
        broker: Model broker (embeddings local, adjudication frontier).
        ontology_type: Canonical type these records resolve into.
        policy: Optional survivorship policy (G3); weighted merge when None.
        review: Optional adjudication queue sink (G10); band pairs are queued.

    Returns:
        (entity, members) pairs, one per cluster.
    """
    by_id = {r.record_id: r for r in records}
    union = UnionFind()
    pair_scores: dict[tuple[int, int], float] = {}
    for record in records:
        union.add(record.record_id)

    max_pairs_per_block = get_settings().max_pairs_per_block
    # The pair loop visits records in order and stops at max_pairs_per_block.
    # Embedding records beyond what the loop can reach is pure waste: cap at
    # the number of records n where n*(n-1)/2 ≤ max_pairs_per_block.
    _embed_cap = int((2 * max_pairs_per_block) ** 0.5) + 2  # n where n*(n-1)/2 ≤ max_pairs_per_block; +2 guards rounding
    blocks = block(records)
    total_blocks = len(blocks)
    total_merged = 0
    for block_idx, group in enumerate(blocks.values()):
        if len(group) <= 1:
            # Size-1 blocks have no pairs — skip OCI embed API call entirely.
            logger.debug(
                "resolve block=%d/%d size=1 skip total_merged=%d",
                block_idx + 1, total_blocks, total_merged,
            )
            continue
        embeddings = _block_embeddings(group[:_embed_cap], broker)
        pairs_evaluated = 0
        block_merges = 0
        done = False
        for i in range(len(group)):
            if done:
                break
            for j in range(i + 1, len(group)):
                if pairs_evaluated >= max_pairs_per_block:
                    done = True
                    break
                left, right = group[i], group[j]
                left_root_before = union.find(left.record_id)
                right_root_before = union.find(right.record_id)
                score = score_pair(left.text, right.text,
                                   embeddings.get(left.record_id),
                                   embeddings.get(right.record_id))
                pair_scores[(left.record_id, right.record_id)] = score
                _route_pair(left, right, score, broker, union, review)
                if left_root_before != right_root_before and \
                        union.find(left.record_id) == union.find(right.record_id):
                    block_merges += 1
                pairs_evaluated += 1
        total_merged += block_merges
        logger.info(
            "resolve block=%d/%d size=%d pairs=%d merges=%d total_merged=%d",
            block_idx + 1, total_blocks, len(group),
            pairs_evaluated, block_merges, total_merged,
        )

    results = [
        (_materialize(member_ids, by_id, pair_scores, ontology_type, policy),
         [EntityMember(landed_record_id=mid) for mid in member_ids])
        for member_ids in union.groups().values()
    ]
    logger.info("resolved records=%d entities=%d", len(records), len(results))
    return results
