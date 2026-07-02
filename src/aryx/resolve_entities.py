"""Entity resolution orchestration: resolve a run's records into entities."""
from __future__ import annotations

import logging
from collections.abc import Callable

from aryx.broker import Broker
from aryx.resolution import resolve
from aryx.store.entity_store import EntityStore

logger = logging.getLogger(__name__)

Progress = Callable[[str, int, str], None]


def resolve_run(
    run_id: int,
    ontology_type: str,
    key_attrs: list[str],
    store: EntityStore,
    broker: Broker,
    on_progress: Progress | None = None,
) -> int:
    """Resolve one run's landed records into canonical entities.

    Args:
        run_id: The discovery run to resolve.
        ontology_type: Canonical type the records resolve into.
        key_attrs: Payload keys whose values form the match text.
        store: Open entity store.
        broker: Model broker (embeddings local, adjudication frontier).
        on_progress: Optional callback (stage, pct, detail).

    Returns:
        Number of entities created.
    """
    def _emit(stage: str, pct: int, detail: str) -> None:
        if on_progress is not None:
            on_progress(stage, pct, detail)

    _emit("Resolve", 32, f"Loading landed records for run {run_id}")
    records = store.landed_records(run_id, key_attrs)
    _emit("Resolve", 38, f"{len(records)} records loaded — blocking and scoring pairs")
    results = resolve(records, broker, ontology_type)
    _emit("Resolve", 58, f"{len(results)} clusters found — saving entities")
    created = store.save(results)
    logger.info("resolve_run complete run_id=%s entities=%d", run_id, created)
    return created
