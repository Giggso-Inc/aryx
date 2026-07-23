"""Entity resolution orchestration: resolve a run's records into entities."""
from __future__ import annotations

import logging
from collections.abc import Callable

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.models import EntityMember, ResolutionRecord
from aryx.resolution import resolve
from aryx.resolution.chunked import resolve_chunked
from aryx.resolution.review_queue import StoreReviewSink
from aryx.resolution.run import _materialize
from aryx.resolution.survivorship import SurvivorshipPolicy
from aryx.store.adjudication_store import AdjudicationStore
from aryx.store.chunk_backend import PgChunkBackend
from aryx.store.entity_store import EntityStore
from aryx.workspaces import make_workspace_store

logger = logging.getLogger(__name__)

Progress = Callable[[str, int, str], None]

_DEFAULT_SURVIVORSHIP_STRATEGY = "most_complete"


def _id_like_keys() -> frozenset[str]:
    """Config-driven match-key names that denote opaque unique identifiers —
    same convention (and same setting, ARYX_ID_LIKE_COLUMN_NAMES) as
    _id_priority_mk / _guess_key_col in doc_discovery.py. When ALL match
    keys are id-like, identity is exact by definition and fuzzy scoring is
    invalid."""
    return frozenset(
        s.strip().lower() for s in get_settings().id_like_column_names.split(",")
        if s.strip()
    )


def _key_selectivity(records: list[ResolutionRecord], sample_size: int) -> float:
    """Distinct-value ratio of match text over a bounded sample.

    A cheap, upfront signal for whether the match key has enough identity
    information to produce a meaningful block at all — the same principle
    already applied to FK-detection candidates (dynamic_fk.py) applied one
    layer over: measure selectivity before committing to expensive work,
    not after discovering it was pointless.
    """
    sample = records[:sample_size]
    if not sample:
        return 1.0
    distinct = len({r.text.strip().lower() for r in sample if r.text})
    return distinct / len(sample)


def resolve_run(
    run_id: int,
    ontology_type: str,
    key_attrs: list[str],
    store: EntityStore,
    broker: Broker,
    on_progress: Progress | None = None,
    workspace_id: int = 1,
) -> int:
    """Resolve one run's landed records into canonical entities.

    Args:
        run_id: The discovery run to resolve.
        ontology_type: Canonical type the records resolve into.
        key_attrs: Payload keys whose values form the match text.
        store: Open entity store.
        broker: Model broker (embeddings local, adjudication frontier).
        on_progress: Optional callback (stage, pct, detail).
        workspace_id: Workspace the run belongs to (review queue + survivorship policy).

    Returns:
        Number of entities created.
    """
    def _emit(stage: str, pct: int, detail: str) -> None:
        if on_progress is not None:
            on_progress(stage, pct, detail)

    settings = get_settings()

    review = None
    try:
        adj_store = AdjudicationStore(settings.rdb_dsn, workspace_id)
        review = StoreReviewSink(adj_store, run_id)
    except Exception as exc:  # noqa: BLE001 — queue unavailable, funnel still runs
        logger.warning("resolve_run run_id=%s review sink unavailable, "
                       "review-band pairs will be dropped: %s", run_id, exc)

    policy = SurvivorshipPolicy(default_strategy=_DEFAULT_SURVIVORSHIP_STRATEGY)
    ws_store = None
    try:
        ws_store = make_workspace_store(settings.rdb_dsn)
        raw = ws_store.get_survivorship(workspace_id)
        if raw:
            policy = SurvivorshipPolicy.from_json(raw)
    except Exception as exc:  # noqa: BLE001 — policy lookup failed, use safe default
        logger.warning("resolve_run run_id=%s survivorship policy lookup failed, "
                       "using default strategy=%s: %s",
                       run_id, _DEFAULT_SURVIVORSHIP_STRATEGY, exc)
    finally:
        if ws_store is not None:
            ws_store.close()

    # bool(key_attrs) is load-bearing: all([]) is True, and an empty match-key
    # list must never trigger exact mode.
    exact_ids = (settings.er_exact_id_match and bool(key_attrs)
                 and all(k.lower() in _id_like_keys() for k in key_attrs))
    if exact_ids:
        logger.info("resolve_run run_id=%s exact_ids=True match_keys=%s", run_id, key_attrs)

    _emit("Resolve", 32, f"Loading landed records for run {run_id}")
    records = store.landed_records(run_id, key_attrs)
    _emit("Resolve", 38, f"{len(records)} records loaded — blocking and scoring pairs")

    # Key-selectivity guard: a table whose match-key columns are each a
    # single (or near-single) constant value across every row — e.g. a
    # sheet with no reliable natural key — has too little identity signal
    # to produce a meaningful block. Blocking still collapses everything
    # into one oversized block that gets correctly skipped, but only AFTER
    # paying the full cost of the key/blocking pass to discover that. A
    # real incident: 308,104 such records ran the full blocking pass (and,
    # separately, an unbatched per-cluster save) before reaching the same
    # all-singleton outcome this check reaches immediately. Not applicable
    # to exact_ids mode: that path already never runs pairwise scoring.
    selectivity = None if exact_ids else _key_selectivity(
        records, settings.er_key_selectivity_sample_size,
    )
    if selectivity is not None and selectivity < settings.er_min_key_selectivity:
        logger.info(
            "resolve_run run_id=%s key_selectivity=%.4f below "
            "er_min_key_selectivity=%.4f (match_keys=%s, records=%d) — key has "
            "too little identity signal for meaningful blocking; skipping "
            "resolution, materializing one entity per record directly",
            run_id, selectivity, settings.er_min_key_selectivity, key_attrs, len(records),
        )
        results = [
            (_materialize([r.record_id], {r.record_id: r}, {}, ontology_type, policy),
             [EntityMember(landed_record_id=r.record_id)])
            for r in records
        ]
    # Large, low-key-quality tabular sheets (e.g. a 300K-row Data tab with no
    # natural row cap) can stall the in-memory O(block-size²) blocking/scoring
    # pass for hours. Above er_chunk_threshold, dispatch to the streaming
    # block-wise resolver instead — same cluster-equivalence contract
    # (tests/test_chunked_resolution.py), bounded memory, Postgres-resumable.
    # Not applicable to exact_ids mode: id-keyed sources already resolve by
    # exact equality with no pairwise scoring, regardless of size.
    elif not exact_ids and len(records) > settings.er_chunk_threshold:
        logger.info(
            "resolve_run run_id=%s records=%d exceeds er_chunk_threshold=%d — "
            "using chunked (streaming, Postgres-resumable) resolver",
            run_id, len(records), settings.er_chunk_threshold,
        )
        backend = PgChunkBackend(settings.rdb_dsn, workspace_id, key_attrs)
        all_record_ids = [r.record_id for r in records]
        results = list(resolve_chunked(
            run_id, records, all_record_ids, backend, ontology_type, policy=policy,
        ))
    else:
        results = resolve(records, broker, ontology_type, policy=policy, review=review,
                          run_id=run_id, exact_ids=exact_ids)
    _emit("Resolve", 58, f"{len(results)} clusters found — saving entities")
    created = store.save(results)
    logger.info("resolve_run complete run_id=%s entities=%d", run_id, created)
    return created
