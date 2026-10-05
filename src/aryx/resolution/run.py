"""Entity resolution funnel (stage 7): block -> score -> adjudicate -> cluster.

Thresholds (env-tunable, defaults from the G9 sweep — see DECISIONS.md):
  ARYX_ER_AUTO_MERGE   >= this -> auto-merge                  (default 0.92)
  ARYX_ER_ADJUDICATE   [this, AUTO_MERGE) -> LLM adjudicates  (default 0.90)
  ARYX_ER_REVIEW       [this, ADJUDICATE) -> human queue      (default 0.75)
  below REVIEW -> auto-reject (never merged, never queued)

Pairs routed to the human queue are treated as NON-merge for the current run
(conservative: a wrong merge is worse than a missed merge in audited domains).
A later human approval unions the entities via apply_decision (G10).

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), the
exact-id resolution path and pair-score bucketing (`_resolve_exact`,
`_partition_pair_scores` — neither calls `get_settings`/`adjudicate` nor is
itself patched) moved to `resolution/run_exact.py`. Everything else stays
here as a deliberate, documented exception: `get_settings` is called from
`_block_embeddings`, `_route_pair`, `_materialize`, AND `resolve` itself,
and `tests/test_partition_pair_scores.py`/`test_resolve_run_wiring.py`
whitebox-patch `aryx.resolution.run.get_settings` directly — moving any one
of those callers out would mean it could no longer reach the patched name
via a plain `from...import` (the same bound-at-import-time gotcha this plan
has hit before). `adjudicate` (patched by `test_adjudication.py`) is only
called from `_route_pair`, and `_materialize` is itself directly patched
by `test_partition_pair_scores.py` and called only from `resolve` — both
must stay put for the same reason.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.models import EntityMember, ResolutionRecord, ResolvedEntity
from aryx.raven_log import raven_log, submit_ctx, would_log
from aryx.resolution.stats import bump
from aryx.resolution.adjudicate import adjudicate
from aryx.resolution.classical import block, score_pair
from aryx.resolution.cluster import UnionFind, golden_record_weighted
from aryx.resolution.confidence import cluster_confidence, cluster_edges
from aryx.resolution.golden import golden_record_with_policy
from aryx.resolution.review_queue import ReviewSink
from aryx.resolution.run_exact import _partition_pair_scores, _resolve_exact
from aryx.resolution.survivorship import SurvivorshipPolicy

logger = logging.getLogger(__name__)

# How often (in blocks) to report progress back through on_block_progress.
# Blocks are cheap to iterate but each non-trivial one can cost real wall-clock
# (embedding + adjudication calls), so this needs to be frequent enough that
# a long-running resolve doesn't look stuck to the job-status UI.
_PROGRESS_EVERY = 25


def _block_embeddings(
    records: list[ResolutionRecord], broker: Broker, run_id: int | None = None
) -> dict[int, list[float]]:
    """Embed a block's texts in small batches; empty dict if unavailable.

    Short-circuits when both auto-merge and adjudicate thresholds are 1.0 —
    in that mode only exact duplicates can merge, and string scoring detects
    those without needing vectors.
    """
    cfg = get_settings()
    if cfg.er_auto_merge >= 1.0 and cfg.er_adjudicate >= 1.0:
        logger.debug("resolve run_id=%s embed skipped auto_merge=%.2f adjudicate=%.2f (both>=1.0)",
                     run_id, cfg.er_auto_merge, cfg.er_adjudicate)
        raven_log("DEBUG", "P4", "ingest.resolve.embed_skipped embeddings skipped (exact-only thresholds)",
                  context={"task_id": run_id, "selected_option": "skip_embed",
                           "available_options": ["embed", "skip_embed"], "reason_code": "THRESHOLDS_AT_1_0",
                           "auto_merge": cfg.er_auto_merge, "adjudicate": cfg.er_adjudicate,
                           "records": len(records)})
        return {}
    out: dict[int, list[float]] = {}
    for start in range(0, len(records), cfg.embed_batch_size):
        batch = records[start : start + cfg.embed_batch_size]
        # Dedupe identical text values before embedding, not after (§2,
        # 2026-10-04): two records sharing an exact text string (common --
        # e.g. duplicate names/descriptions within a block) previously each
        # paid a full embedding call. Each embedding call has fixed latency/
        # cost regardless of whether the text is "new", so deduping turns
        # O(records) calls into O(distinct texts) -- zero change to
        # resolution correctness, every original record still gets its
        # value's vector, just via a dict lookup instead of a fresh call.
        # dict.fromkeys, not a set (PR review round 7, Low): both dedupe to
        # the same distinct values, but a set's iteration order depends on
        # Python's per-process hash randomization -- the same batch could
        # send its texts to broker.embed() in a different order from one
        # run to the next. Harmless for the zip() pairing below (still
        # positionally correct either way), but needlessly non-deterministic
        # for anything inspecting what was actually sent (tests, debugging,
        # a broker-side log). First-occurrence order costs nothing extra.
        unique_texts = list(dict.fromkeys(r.text for r in batch))
        text_to_vec: dict[str, list[float]] = {}
        try:
            vectors = broker.embed(unique_texts)
            logger.debug("resolve run_id=%s embed batch start=%d size=%d unique=%d vectors=%d",
                         run_id, start, len(batch), len(unique_texts), len(vectors) if vectors else 0)
            if would_log("DEBUG"):
                raven_log("DEBUG", "P4", "ingest.resolve.embed_batch embedding batch done",
                          context={"task_id": run_id, "batch_start": start, "batch_size": len(batch),
                                   "unique_texts": len(unique_texts),
                                   "vectors": len(vectors) if vectors else 0,
                                   "vectors_returned": bool(vectors)})
            if vectors:
                text_to_vec = dict(zip(unique_texts, vectors))
        except Exception as exc:  # noqa: BLE001
            raven_log("WARN", "P3", "ingest.resolve.embed_failed embedding batch failed, string-only scoring",
                      error_code="ARYX_ING_RESOLVE_DEGRADED",
                      context={"task_id": run_id, "stage": "resolve", "batch_start": start,
                               "batch_size": len(batch), "error_class": type(exc).__name__,
                               "recovery_selected": "string_only_scoring", "result": "degraded"})
            logger.warning("resolve run_id=%s embed batch start=%d size=%d failed, "
                           "falling back to string-only: %s", run_id, start, len(batch), exc)
        for r in batch:
            if r.text in text_to_vec:
                out[r.record_id] = text_to_vec[r.text]
    return out


def _route_pair(left: ResolutionRecord, right: ResolutionRecord, score: float,
                broker: Broker, union: UnionFind,
                review: ReviewSink | None, run_id: int | None = None) -> str:
    """Apply the four-way threshold routing to one scored pair.

    Returns:
        The band decision label: "merge", "adjudicate_merge",
        "adjudicate_no_merge", "review", "review_dropped", or "reject".
    """
    cfg = get_settings()
    auto = cfg.er_auto_merge
    adj = cfg.er_adjudicate
    rev = cfg.er_review
    def _pair(band: str, decision: str, **extra: object) -> None:
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ingest.resolve.pair pair routed",
                      context={"task_id": run_id, "left_id": left.record_id, "right_id": right.record_id,
                               "score": round(score, 4), "band": band, "decision": decision,
                               "selected_option": decision,
                               "available_options": ["merge", "adjudicate", "review", "reject"],
                               "reason_code": f"SCORE_IN_{band.upper()}_BAND",
                               "auto_merge": auto, "adjudicate_min": adj, "review_min": rev, **extra})

    if score >= auto:
        _pair("auto_merge", "merge")
        union.union(left.record_id, right.record_id)
        logger.info("resolve run_id=%s pair left=%s right=%s score=%.3f band=auto_merge decision=merge",
                    run_id, left.record_id, right.record_id, score)
        return "merge"
    if score >= adj:
        try:
            same = adjudicate(left, right, broker)
            if review is not None:
                review.offer(left, right, score, llm_verdict=same,
                             llm_reason="llm adjudication", status="auto_llm")
            logger.info("resolve run_id=%s pair left=%s right=%s score=%.3f band=adjudicate "
                        "llm_verdict=%s decision=%s", run_id, left.record_id, right.record_id,
                        score, same, "merge" if same else "no_merge")
            _pair("adjudicate", "merge" if same else "no_merge", llm_verdict=bool(same),
                  review_sink=review is not None)
            if same:
                union.union(left.record_id, right.record_id)
                return "adjudicate_merge"
            return "adjudicate_no_merge"
        except Exception as exc:  # noqa: BLE001 — LLM down -> human decides
            logger.warning("resolve run_id=%s pair left=%s right=%s score=%.3f band=adjudicate "
                           "adjudication failed, queueing for human: %s",
                           run_id, left.record_id, right.record_id, score, exc)
            bump(run_id, "adjudication_failed")
            raven_log("WARN", "P3", "ingest.resolve.adjudication_failed adjudication failed, queued for human",
                      error_code="ARYX_ING_RESOLVE_DEGRADED",
                      context={"task_id": run_id, "stage": "resolve", "left_id": left.record_id,
                               "right_id": right.record_id, "score": round(score, 4),
                               "error_class": type(exc).__name__, "recovery_selected": "human_review_queue",
                               "result": "degraded", "queued": review is not None})
            if review is not None:
                review.offer(left, right, score, llm_verdict=None,
                             llm_reason=f"llm unavailable: {exc}",
                             status="pending")
            return "adjudicate_no_merge"
    if score >= rev:
        if review is not None:
            try:
                review.offer(left, right, score, llm_verdict=None,
                             llm_reason=None, status="pending")
                logger.info("resolve run_id=%s pair left=%s right=%s score=%.3f band=review "
                            "decision=queued", run_id, left.record_id, right.record_id, score)
                _pair("review", "queued")
                return "review"
            except Exception as exc:  # noqa: BLE001 — queue write failed, don't fail the run
                logger.warning("resolve run_id=%s pair left=%s right=%s score=%.3f band=review "
                               "queue write failed, pair dropped: %s",
                               run_id, left.record_id, right.record_id, score, exc)
                _pair("review", "dropped_queue_write_failed", error_class=type(exc).__name__)
                return "review_dropped"
        logger.info("resolve run_id=%s pair left=%s right=%s score=%.3f band=review "
                    "decision=dropped_no_sink", run_id, left.record_id, right.record_id, score)
        _pair("review", "dropped_no_sink")
        return "review_dropped"
    logger.debug("resolve run_id=%s pair left=%s right=%s score=%.3f band=reject decision=no_merge",
                 run_id, left.record_id, right.record_id, score)
    _pair("reject", "no_merge")
    return "reject"


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
    run_id: int | None = None,
    exact_ids: bool = False,
    on_block_progress: Callable[[int, int], None] | None = None,
) -> list[tuple[ResolvedEntity, list[EntityMember]]]:
    """Resolve records into canonical entities via the funnel.

    Args:
        records: Landed records prepared for matching.
        broker: Model broker (embeddings local, adjudication frontier).
        ontology_type: Canonical type these records resolve into.
        policy: Optional survivorship policy (G3); weighted merge when None.
        review: Optional adjudication queue sink (G10); band pairs are queued.
        run_id: Discovery run being resolved, for log correlation.
        exact_ids: Merge on exact match-text equality only — for sources
            whose match keys are opaque identifiers (see _resolve_exact).
        on_block_progress: Optional callback(blocks_done, total_blocks), fired
            every _PROGRESS_EVERY blocks so long-running runs (LLM adjudication
            per pair) surface progress instead of looking stuck.

    Returns:
        (entity, members) pairs, one per cluster.
    """
    by_id = {r.record_id: r for r in records}
    union = UnionFind()
    pair_scores: dict[tuple[int, int], float] = {}
    band_counts: dict[str, int] = {}
    for record in records:
        union.add(record.record_id)

    if exact_ids:
        total_merged = _resolve_exact(records, union, pair_scores, run_id)
        pair_scores_by_root = _partition_pair_scores(union, pair_scores)
        results = [
            (_materialize(member_ids, by_id, pair_scores_by_root.get(root, {}),
                         ontology_type, policy),
             [EntityMember(landed_record_id=mid) for mid in member_ids])
            for root, member_ids in union.groups().items()
        ]
        logger.info(
            "resolved run_id=%s mode=exact_ids records=%d entities=%d merged=%d",
            run_id, len(records), len(results), total_merged,
        )
        bump(run_id, "merged", total_merged)
        raven_log("DEBUG", "P4", "ingest.resolve.exact_done exact-id resolution finished",
                  context={"task_id": run_id, "records": len(records), "entities": len(results),
                           "merged": total_merged, "selected_option": "exact_ids"})
        return results

    max_pairs_per_block = get_settings().max_pairs_per_block
    # The pair loop visits records in order and stops at max_pairs_per_block.
    # Embedding records beyond what the loop can reach is pure waste: cap at
    # the number of records n where n*(n-1)/2 ≤ max_pairs_per_block.
    _embed_cap = int((2 * max_pairs_per_block) ** 0.5) + 2  # n where n*(n-1)/2 ≤ max_pairs_per_block; +2 guards rounding
    blocks = block(records, run_id=run_id)
    block_items = list(blocks.items())
    total_blocks = len(block_items)
    total_merged = 0
    logger.info("resolve run_id=%s blocks=%d records=%d", run_id, total_blocks, len(records))

    # Prefetch every multi-member block's embeddings concurrently (2026-09-23,
    # docs/ingestion/SPARK_PARALLEL_MIGRATION_ANALYSIS_2026-09-23.md Phase 3).
    # _block_embeddings has no shared state -- broker.embed() is an
    # independent network call per block -- so this is safe to parallelize
    # even though the routing/union-find loop below must stay sequential:
    # MultiKeyBlocker deliberately places each record in up to 3 overlapping
    # blocks (prefix/token-set/Soundex), and `union`/`pair_scores`/
    # `band_counts` below have no synchronization, so naively parallelizing
    # THAT loop would race. Live-measured: embedding is ~99% of resolve()'s
    # wall-clock time on a realistic dataset (22.66s of 22.97s total, 96
    # records / 61 blocks) -- scoring, routing, and union-find bookkeeping
    # are comparatively free, so prefetching embeddings alone captures
    # nearly the entire available win without touching the unsafe part.
    embed_workers = max(1, get_settings().er_embed_workers)
    embeddings_by_block: dict[str, dict[int, list[float]]] = {}
    with ThreadPoolExecutor(max_workers=embed_workers) as pool:
        future_to_key = {
            submit_ctx(pool, _block_embeddings, group[:_embed_cap], broker, run_id): key
            for key, group in block_items if len(group) > 1
        }
        for future in as_completed(future_to_key):
            embeddings_by_block[future_to_key[future]] = future.result()

    for block_idx, (block_key, group) in enumerate(block_items):
        if len(group) <= 1:
            # Size-1 blocks have no pairs — skip OCI embed API call entirely.
            logger.debug(
                "resolve run_id=%s block=%d/%d size=1 skip total_merged=%d",
                run_id, block_idx + 1, total_blocks, total_merged,
            )
            if would_log("DEBUG"):
                raven_log("DEBUG", "P4", "ingest.resolve.block_singleton singleton block skipped",
                          context={"task_id": run_id, "block_idx": block_idx + 1, "total_blocks": total_blocks,
                                   "selected_option": "skip", "reason_code": "BLOCK_SIZE_1"})
            continue
        embeddings = embeddings_by_block.get(block_key, {})
        pairs_evaluated = 0
        block_merges = 0
        done = False
        for i in range(len(group)):
            if done:
                break
            for j in range(i + 1, len(group)):
                if pairs_evaluated >= max_pairs_per_block:
                    done = True
                    bump(run_id, "blocks_pair_capped")
                    raven_log("DEBUG", "P4", "ingest.resolve.block_pair_cap block pair cap reached",
                              context={"task_id": run_id, "block_idx": block_idx + 1, "members": len(group),
                                       "pairs_evaluated": pairs_evaluated, "threshold": max_pairs_per_block,
                                       "selected_option": "stop_block", "reason_code": "MAX_PAIRS_PER_BLOCK"})
                    break
                left, right = group[i], group[j]
                left_root_before = union.find(left.record_id)
                right_root_before = union.find(right.record_id)
                score = score_pair(left.text, right.text,
                                   embeddings.get(left.record_id),
                                   embeddings.get(right.record_id),
                                   run_id=run_id)
                pair_scores[(left.record_id, right.record_id)] = score
                decision = _route_pair(left, right, score, broker, union, review, run_id=run_id)
                band_counts[decision] = band_counts.get(decision, 0) + 1
                if left_root_before != right_root_before and \
                        union.find(left.record_id) == union.find(right.record_id):
                    block_merges += 1
                pairs_evaluated += 1
        total_merged += block_merges
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ingest.resolve.block_done block scored",
                      context={"task_id": run_id, "block_idx": block_idx + 1, "total_blocks": total_blocks,
                               "members": len(group), "pairs": pairs_evaluated, "merges": block_merges,
                               "embedded": len(embeddings)})
        logger.info(
            "resolve run_id=%s block=%d/%d size=%d pairs=%d merges=%d total_merged=%d",
            run_id, block_idx + 1, total_blocks, len(group),
            pairs_evaluated, block_merges, total_merged,
        )
        if on_block_progress is not None and (
            (block_idx + 1) % _PROGRESS_EVERY == 0 or block_idx + 1 == total_blocks
        ):
            on_block_progress(block_idx + 1, total_blocks)

    pair_scores_by_root = _partition_pair_scores(union, pair_scores)
    results = [
        (_materialize(member_ids, by_id, pair_scores_by_root.get(root, {}),
                     ontology_type, policy),
         [EntityMember(landed_record_id=mid) for mid in member_ids])
        for root, member_ids in union.groups().items()
    ]
    logger.info(
        "resolved run_id=%s records=%d entities=%d merged=%d adjudicated=%d "
        "reviewed=%d review_dropped=%d rejected=%d",
        run_id, len(records), len(results), total_merged,
        band_counts.get("adjudicate_merge", 0) + band_counts.get("adjudicate_no_merge", 0),
        band_counts.get("review", 0), band_counts.get("review_dropped", 0),
        band_counts.get("reject", 0),
    )
    bump(run_id, "merged", total_merged)
    bump(run_id, "adjudicated",
         band_counts.get("adjudicate_merge", 0) + band_counts.get("adjudicate_no_merge", 0))
    bump(run_id, "review_dropped", band_counts.get("review_dropped", 0))
    raven_log("DEBUG", "P4", "ingest.resolve.funnel_done pair funnel finished",
              context={"task_id": run_id, "records": len(records), "entities": len(results),
                       "blocks": total_blocks, "band_counts": dict(band_counts),
                       "max_pairs_per_block": max_pairs_per_block})
    return results
