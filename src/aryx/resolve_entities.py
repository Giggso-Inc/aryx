"""Entity resolution orchestration: resolve a run's records into entities.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03),
`_key_selectivity` moved to `resolve_entities_selectivity.py` (zero
patch risk). The rest of this module stays together as a deliberate,
documented exception: `get_settings` is called both directly in
`resolve_run` and internally by `_id_like_keys`, and
`tests/test_resolve_run_wiring.py` whitebox-patches
`aryx.resolve_entities.get_settings` expecting BOTH call sites to see the
patched value — moving `_id_like_keys` to a module with its own
`from aryx.config import get_settings` import would silently stop seeing
that patch (the same bound-at-import-time gotcha this plan has hit
before). `AdjudicationStore`/`make_workspace_store`/`resolve`/
`resolve_chunked`/`PgChunkBackend` are likewise all patched directly and
called only from `resolve_run`, so they stay too.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.models import EntityMember, ResolutionRecord
from aryx.raven_log import raven_log
from aryx.resolution import resolve
from aryx.resolution.stats import pop as _pop_stats
from aryx.resolution.chunked import resolve_chunked
from aryx.resolution.review_queue import StoreReviewSink
from aryx.resolution.run import _materialize
from aryx.resolution.survivorship import SurvivorshipPolicy
from aryx.resolve_entities_selectivity import _full_uniqueness_ratio, _key_selectivity
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


def resolve_run(
    run_id: int,
    ontology_type: str,
    key_attrs: list[str],
    store: EntityStore,
    broker: Broker,
    on_progress: Progress | None = None,
    workspace_id: int = 1,
    force_exact: bool = False,
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
        force_exact: Caller-asserted override (§1 Tier 2, 2026-10-04) for
            when it already knows a tag's values are exact identifiers even
            though the key's *name* doesn't look ID-like (e.g.
            cpq_ingestion's generic ``text`` fallback key, whose values
            turned out to be 100% unique on a real 439,946-record tag).
            Normally ``exact_ids`` is decided purely by whether the key
            NAME matches ``_id_like_keys()`` -- a generic-fallback key never
            qualifies by name, even when the sampled values are fully
            unique, so without this the caller pays for
            ``_key_selectivity()``'s sampling pass just to arrive at the
            same conclusion non-deterministically depending on the sample.
            Same ``bool(key_attrs)`` guard as the name-based check: an empty
            match-key list must never trigger exact mode regardless of this
            flag.

    Returns:
        Number of entities created.
    """
    def _emit(stage: str, pct: int, detail: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(stage, pct, detail)
        except Exception as exc:  # noqa: BLE001 — a heartbeat failure must never abort the resolve
            logger.warning("resolve_run run_id=%s on_progress callback failed, "
                           "continuing resolve: %s", run_id, exc)

    settings = get_settings()
    _t0 = time.monotonic()
    sink_unavailable = False
    policy_fallback = False

    review = None
    try:
        adj_store = AdjudicationStore(settings.effective_dsn(), workspace_id)
        review = StoreReviewSink(adj_store, run_id)
    except Exception as exc:  # noqa: BLE001 — queue unavailable, funnel still runs
        logger.warning("resolve_run run_id=%s review sink unavailable, "
                       "review-band pairs will be dropped: %s", run_id, exc)
        sink_unavailable = True
        raven_log("WARN", "P3", "ingest.resolve.review_sink_unavailable review queue unavailable",
                  error_code="ARYX_ING_RESOLVE_DEGRADED",
                  context={"task_id": run_id, "stage": "resolve", "error_class": type(exc).__name__,
                           "recovery_selected": "drop_review_band_pairs", "result": "degraded"})

    policy = SurvivorshipPolicy(default_strategy=_DEFAULT_SURVIVORSHIP_STRATEGY)
    ws_store = None
    try:
        ws_store = make_workspace_store(settings.effective_dsn())
        raw = ws_store.get_survivorship(workspace_id)
        if raw:
            policy = SurvivorshipPolicy.from_json(raw)
    except Exception as exc:  # noqa: BLE001 — policy lookup failed, use safe default
        logger.warning("resolve_run run_id=%s survivorship policy lookup failed, "
                       "using default strategy=%s: %s",
                       run_id, _DEFAULT_SURVIVORSHIP_STRATEGY, exc)
        policy_fallback = True
        raven_log("WARN", "P3", "ingest.resolve.policy_lookup_failed survivorship policy lookup failed",
                  error_code="ARYX_ING_RESOLVE_DEGRADED",
                  context={"task_id": run_id, "stage": "resolve", "error_class": type(exc).__name__,
                           "recovery_selected": "default_strategy",
                           "fallback_target": _DEFAULT_SURVIVORSHIP_STRATEGY, "result": "degraded"})
    finally:
        if ws_store is not None:
            ws_store.close()

    # bool(key_attrs) is load-bearing: all([]) is True, and an empty match-key
    # list must never trigger exact mode.
    name_based_exact = (settings.er_exact_id_match and bool(key_attrs)
                        and all(k.lower() in _id_like_keys() for k in key_attrs))

    _emit("Resolve", 32, f"Loading landed records for run {run_id}")
    records = store.landed_records(run_id, key_attrs)
    _emit("Resolve", 38, f"{len(records)} records loaded — blocking and scoring pairs")

    def _on_block_progress(blocks_done: int, total_blocks: int) -> None:
        pct = 38 + int(20 * blocks_done / total_blocks)
        _emit("Resolve", pct, f"scored block {blocks_done}/{total_blocks}")

    # Key-selectivity guard: a table whose match-key columns are each a
    # single (or near-single) constant value across every row — e.g. a
    # sheet with no reliable natural key — has too little identity signal
    # to produce a meaningful block. Blocking still collapses everything
    # into one oversized block that gets correctly skipped, but only AFTER
    # paying the full cost of the key/blocking pass to discover that. A
    # real incident: 308,104 such records ran the full blocking pass (and,
    # separately, an unbatched per-cluster save) before reaching the same
    # all-singleton outcome this check reaches immediately. Not applicable
    # to name_based_exact mode: that path already never runs pairwise
    # scoring, so there's nothing to guard and no reason to pay the
    # sampling cost. A bare force_exact request, by contrast, MUST compute
    # this — see the verification note below — so only name_based_exact
    # skips the sample, not exact_ids generally (exact_ids isn't known yet
    # at this point; see its computation right after).
    selectivity = None if name_based_exact else _key_selectivity(
        records, settings.er_key_selectivity_sample_size,
    )

    # force_exact (§1 Tier 2) is a caller's ASSERTION, not proof, that a
    # match key named too genetically to qualify via _id_like_keys() still
    # has unique-enough values to resolve by exact equality. Taking that
    # assertion on faith was a real correctness bug (PR review M2,
    # 2026-10-04): cpq_ingestion's only signal for force_exact is
    # infer_match_keys_for_tag's source=="default", which fires whenever
    # neither the heuristic nor the LLM could confidently name a key --
    # that says nothing about whether the key's VALUES are actually
    # unique. A guessed key with low cardinality (e.g. a status/type
    # column) forced into exact mode would merge every record sharing a
    # value into one entity, silently losing records.
    #
    # PR review N1 (2026-10-04), round 2: the FIRST version of this
    # verification reused `selectivity` above -- a head-sampled estimate
    # (records[:sample_size]), not a full scan. A repeated placeholder
    # value (e.g. "N/A") concentrated outside the sampled head would make
    # the sample look fully unique while the real data isn't, and the
    # original 0.99 threshold tolerated up to ~1% real duplicates anyway
    # -- exactly the collisions exact-match merging must not tolerate.
    # force_exact's verification now runs `_full_uniqueness_ratio()`, a
    # full O(n) scan ("cheap next to resolve" even at 440K+ short strings,
    # same reasoning the reviewer gave) over every record, not a sample --
    # computed only when force_exact is actually requested, so callers
    # that never set it pay nothing extra.
    full_uniqueness = (
        _full_uniqueness_ratio(records)
        if force_exact and bool(key_attrs) and not name_based_exact
        else None
    )
    verified_force_exact = (
        full_uniqueness is not None
        and full_uniqueness >= settings.er_force_exact_min_selectivity
    )
    exact_ids = name_based_exact or verified_force_exact
    if force_exact and not verified_force_exact and not name_based_exact:
        logger.info(
            "resolve_run run_id=%s force_exact requested but NOT honored -- "
            "full-scan uniqueness=%s below er_force_exact_min_selectivity=%.4f "
            "(match_keys=%s); falling through to the normal fuzzy/chunked path",
            run_id, full_uniqueness, settings.er_force_exact_min_selectivity, key_attrs,
        )
        raven_log("INFO", "P4", "ingest.resolve.force_exact_rejected force_exact requested but not verified",
                  context={"task_id": run_id, "match_keys": list(key_attrs),
                           "full_uniqueness": full_uniqueness,
                           "threshold": settings.er_force_exact_min_selectivity,
                           "selected_option": "fuzzy", "available_options": ["exact_ids", "fuzzy"],
                           "reason_code": "FORCE_EXACT_NOT_VERIFIED"})
    if exact_ids:
        logger.info("resolve_run run_id=%s exact_ids=True match_keys=%s forced=%s",
                    run_id, key_attrs, not name_based_exact)
    raven_log("DEBUG", "P4", "ingest.resolve.exact_ids_check exact-id mode decision",
              context={"task_id": run_id, "ontology_type": ontology_type, "match_keys": list(key_attrs),
                       "er_exact_id_match": bool(settings.er_exact_id_match), "has_keys": bool(key_attrs),
                       "selected_option": "exact_ids" if exact_ids else "fuzzy",
                       "available_options": ["exact_ids", "fuzzy"],
                       "reason_code": ("ALL_KEYS_ID_LIKE" if name_based_exact
                                       else "CALLER_FORCED_EXACT_VERIFIED" if exact_ids
                                       else "NOT_ALL_KEYS_ID_LIKE_OR_DISABLED"),
                       "forced": exact_ids and not name_based_exact,
                       "policy_fallback": policy_fallback, "review_sink": not sink_unavailable})

    path = "normal"
    if selectivity is not None and selectivity < settings.er_min_key_selectivity:
        path = "low_selectivity"
        raven_log("INFO", "P4", "ingest.resolve.path_chosen resolve path: low key selectivity",
                  context={"task_id": run_id, "selected_option": path,
                           "available_options": ["exact_ids", "low_selectivity", "chunked", "normal"],
                           "reason_code": "KEY_SELECTIVITY_BELOW_MIN", "selectivity": round(selectivity, 4),
                           "threshold": settings.er_min_key_selectivity, "records": len(records),
                           "match_keys": list(key_attrs)})
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
        path = "chunked"
        raven_log("INFO", "P4", "ingest.resolve.path_chosen resolve path: chunked",
                  context={"task_id": run_id, "selected_option": path,
                           "available_options": ["exact_ids", "low_selectivity", "chunked", "normal"],
                           "reason_code": "RECORDS_ABOVE_CHUNK_THRESHOLD", "records": len(records),
                           "threshold": settings.er_chunk_threshold, "selectivity": selectivity})
        logger.info(
            "resolve_run run_id=%s records=%d exceeds er_chunk_threshold=%d — "
            "using chunked (streaming, Postgres-resumable) resolver",
            run_id, len(records), settings.er_chunk_threshold,
        )
        # PgChunkBackend is Postgres-only (uses ON CONFLICT DO NOTHING with
        # no Oracle override) -- deliberately settings.rdb_dsn, not
        # effective_dsn(), since this subsystem never runs on Oracle either way.
        backend = PgChunkBackend(settings.rdb_dsn, workspace_id, key_attrs)
        all_record_ids = [r.record_id for r in records]
        results = list(resolve_chunked(
            run_id, records, all_record_ids, backend, ontology_type, policy=policy,
            on_progress=_emit,
        ))
    else:
        path = "exact_ids" if exact_ids else "normal"
        raven_log("INFO", "P4", "ingest.resolve.path_chosen resolve path: " + path,
                  context={"task_id": run_id, "selected_option": path,
                           "available_options": ["exact_ids", "low_selectivity", "chunked", "normal"],
                           "reason_code": "EXACT_ID_KEYS" if exact_ids else "DEFAULT_FUNNEL",
                           "records": len(records), "chunk_threshold": settings.er_chunk_threshold,
                           "min_key_selectivity": settings.er_min_key_selectivity,
                           "selectivity": selectivity})
        results = resolve(records, broker, ontology_type, policy=policy, review=review,
                          run_id=run_id, exact_ids=exact_ids,

                          on_block_progress=_on_block_progress)
    _emit("Resolve", 58, f"{len(results)} clusters found — saving entities")
    created = store.save(results, on_progress=_emit)
    logger.info("resolve_run complete run_id=%s entities=%d", run_id, created)
    counts = _pop_stats(run_id)
    degraded = (sink_unavailable or counts.get("adjudication_failed", 0) > 0
                or counts.get("review_dropped", 0) > 0 or counts.get("edge_cap_hit", 0) > 0)
    impact = {"records": len(records), "entities": created, "merged": counts.get("merged", 0),
              "adjudicated": counts.get("adjudicated", 0),
              "adjudication_failed": counts.get("adjudication_failed", 0),
              "review_dropped": counts.get("review_dropped", 0),
              "blocks_skipped_oversized": counts.get("blocks_skipped_oversized", 0),
              "edge_cap_hit": bool(counts.get("edge_cap_hit", 0)), "review_sink_unavailable": sink_unavailable}
    ctx = {"task_id": run_id, "pipeline_run_id": run_id, "stage": "resolve",
           "duration_ms": int((time.monotonic() - _t0) * 1000), "path": path,
           "final_status": "degraded" if degraded else "complete",
           "result": "degraded" if degraded else "ok",
           "reason_code": "RESOLVE_DEGRADED" if degraded else "OK", "impact_scope": impact}
    if degraded:
        raven_log("WARN", "P3", "ingest.resolve.summary resolve finished degraded",
                  error_code="ARYX_ING_RESOLVE_DEGRADED", context=ctx)
    else:
        raven_log("INFO", "P4", "ingest.resolve.summary resolve finished", context=ctx)
    return created
