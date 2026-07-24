"""Entity resolution orchestration: resolve a run's records into entities."""
from __future__ import annotations

import logging
from collections.abc import Callable

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.resolution import resolve
from aryx.resolution.review_queue import StoreReviewSink
from aryx.resolution.survivorship import SurvivorshipPolicy
from aryx.store.adjudication_store import AdjudicationStore
from aryx.store.entity_store import EntityStore
from aryx.workspaces import make_workspace_store

logger = logging.getLogger(__name__)

Progress = Callable[[str, int, str], None]

_DEFAULT_SURVIVORSHIP_STRATEGY = "most_complete"

# Match keys that denote opaque unique identifiers — same convention as
# _id_priority_mk / _guess_key_col in doc_discovery.py. When ALL match keys
# are id-like, identity is exact by definition and fuzzy scoring is invalid.
_ID_LIKE_KEYS: frozenset[str] = frozenset({"id", "uuid", "guid", "key"})


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
                 and all(k.lower() in _ID_LIKE_KEYS for k in key_attrs))
    if exact_ids:
        logger.info("resolve_run run_id=%s exact_ids=True match_keys=%s", run_id, key_attrs)

    _emit("Resolve", 32, f"Loading landed records for run {run_id}")
    records = store.landed_records(run_id, key_attrs)
    _emit("Resolve", 38, f"{len(records)} records loaded — blocking and scoring pairs")
    results = resolve(records, broker, ontology_type, policy=policy, review=review,
                      run_id=run_id, exact_ids=exact_ids)
    _emit("Resolve", 58, f"{len(results)} clusters found — saving entities")
    created = store.save(results)
    logger.info("resolve_run complete run_id=%s entities=%d", run_id, created)
    return created
