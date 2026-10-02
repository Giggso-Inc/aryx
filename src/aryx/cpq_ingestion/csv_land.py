"""Direct CSV -> Postgres landing, no knowledge graph involved at all.

Mirrors raw_graph's "write-only, no resolve" posture (see raw_graph/
__init__.py's Pass 1 docstring), but for CSV instead of XML: same
``ARYX_INGEST_PIPELINE=cpq_ingestion`` switch, activated when
``ARYX_INGEST_FILE_TYPE`` includes ``csv`` (see ``routing.py`` --
the same env var accepts a comma-separated list, e.g. ``"xml,csv"``, so
both file types can be active at once without one disabling the other).

Deliberately does not call ``resolve_run()``/``run_pipeline()``'s later
stages: these rows are landed for their own sake -- a queryable, per-run
relational copy in ``aryx_landed_record`` -- not meant to become graph
entities. No resolve, no relate, no ``aryx_entity``/``aryx_relationship``
row, no graph projection. If a future requirement needs these rows
resolved into the graph after all, that is a new, separate call site
(mirroring how raw_graph's Pass 1 write and Pass 2 resolve/relate are two
independent pieces) -- not something this module should grow into itself.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.connectors.csv_source import CsvConnector
from aryx.discover import discover
from aryx.store.datasource_store import DatasourceStore
from aryx.store.postgres_store import PostgresStore

logger = logging.getLogger(__name__)

#: aryx_landed_record.source_system stamped on every row landed this way --
#: lets provenance/debugging tell a directly-landed CSV row apart from one
#: that went through the full CSV -> Resolve -> Relate -> graph pipeline.
SOURCE_SYSTEM = "cpq_ingestion_csv_direct"

#: Datasource "kind" for a directly-landed CSV -- same string as SOURCE_SYSTEM
#: so a row's aryx_run.source_system and its Data > Sources catalog entry are
#: always identifiable as the same thing. Surfaced via source_catalog_meta.
#: _display_kind(), so an upload through this path shows up there like any
#: other upload instead of being invisible (previously only written to
#: aryx_landed_record, which that page never reads).
_DATASOURCE_KIND = SOURCE_SYSTEM


def land_csv_directly(
    data: bytes,
    stem: str,
    *,
    workspace_id: int,
    dsn: str,
    log_id: str | None = None,
) -> dict[str, Any]:
    """Land one CSV file's rows into ``aryx_landed_record``, nothing else.

    Args:
        data: Raw CSV file bytes.
        stem: Filename stem -- used as the landed run's ``dataset`` label,
            matching the convention every other CSV/XML source already uses.
        workspace_id: Curated workspace this upload belongs to (the landed
            rows are scoped to it even though nothing else in that
            workspace's graph ever reads them).
        dsn: Postgres DSN.
        log_id: Optional correlation id for diagnostic logging.

    Returns:
        ``{"run_id": ..., "source_key": ..., "rows_landed": ...}``.
    """
    connector = CsvConnector(data, system=SOURCE_SYSTEM, dataset=stem)
    store = PostgresStore(dsn, workspace_id)
    logger.info(
        "cpq_ingestion csv_direct did=%s source_key=%s workspace_id=%s starting discover()",
        log_id, stem, workspace_id,
    )
    try:
        run_id = discover(connector, store, SOURCE_SYSTEM, stem)
        rows_landed = store.count_landed(run_id)
    finally:
        store.close()
    result = {"run_id": run_id, "source_key": stem, "rows_landed": rows_landed}
    logger.info(
        "cpq_ingestion csv_direct landed did=%s source_key=%s workspace_id=%s run_id=%s rows=%d",
        log_id, stem, workspace_id, run_id, rows_landed,
    )
    # Register as a datasource so the file shows up on the Data > Sources
    # catalog page like any other upload -- previously only written to
    # aryx_landed_record, which that page never reads. ensure() is a
    # get-or-create keyed on (workspace_id, name), so landing the same file
    # twice is a no-op here, not a duplicate row. Best-effort: a
    # datasource-registration failure must never fail the actual landing
    # that already succeeded above.
    try:
        DatasourceStore(dsn).ensure(workspace_id, f"{stem}.csv"[:255], _DATASOURCE_KIND)
    except Exception:  # noqa: BLE001
        logger.warning(
            "cpq_ingestion: datasource ensure failed for landed csv %r",
            stem, exc_info=True,
        )
    return result
