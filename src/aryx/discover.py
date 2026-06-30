"""Discovery orchestration: run one source end-to-end (extract -> land).

Top-level use case that wires a connector, the streaming spine, and the
landing store under a single tracked run. This is the seam where an external
orchestrator (cron / queue / API) hooks in.
"""
from __future__ import annotations

import logging

from collections.abc import Callable

from aryx.broker import Broker
from aryx.connectors.base import Connector
from aryx.pipeline.run import run_spine
from aryx.pipeline.tag import tag_fields
from aryx.store.batch_sink import BatchSink
from aryx.store.postgres_store import PostgresStore

logger = logging.getLogger(__name__)

Progress = Callable[[str, int, str], None]


def discover(
    connector: Connector,
    store: PostgresStore,
    system: str,
    dataset: str,
    broker: Broker | None = None,
    on_progress: Progress | None = None,
) -> int:
    """Land a source's cleaned records + profiles under one tracked run.

    When a broker is supplied, profiled fields are also semantically tagged
    (stage 4) on the cheap tier. Without one, this is the pure data plane.

    Args:
        connector: Configured source connector.
        store: Open Postgres landing store.
        system: Source system label for the run.
        dataset: Source dataset/table label for the run.
        broker: Optional model broker; enables field tagging when present.
        on_progress: Optional callback (stage, pct, detail).

    Returns:
        The run id, for downstream stages to reference.
    """
    def _emit(stage: str, pct: int, detail: str) -> None:
        if on_progress is not None:
            on_progress(stage, pct, detail)

    _emit("Discover", 8, "Extracting records from source")
    run_id = store.start_run(system, dataset)
    sink = BatchSink(store, run_id)
    profiles = run_spine(connector, sink=sink)
    sink.flush()
    _emit("Discover", 15, f"{sink.total} records extracted — saving profiles")
    store.save_profiles(run_id, profiles)
    _emit("Discover", 20, f"{sink.total} records landed · {len(profiles)} field profiles saved")
    if broker is not None:
        _emit("Discover", 22, f"Tagging {len(profiles)} fields with LLM")
        tags = tag_fields(profiles, broker)
        store.save_tags(run_id, tags)
        _emit("Discover", 25, f"{len(tags)} fields tagged")
        logger.info("discover tagged run_id=%s tags=%d", run_id, len(tags))
    store.finish_run(run_id, sink.total)
    logger.info("discover complete run_id=%s records=%d", run_id, sink.total)
    return run_id
