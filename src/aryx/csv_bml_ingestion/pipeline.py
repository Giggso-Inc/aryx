"""Orchestrates steps 1-4 for one CSV, with Raven logging and graceful failure.

    1. extract table name from the CSV filename        (table_name)
    2. identify the BML query in the XML graph          (bml_index)
    3. load + apply the LLM-authored schema/index SQL   (sql_catalog, db)
    4. validate + ingest the CSV rows                   (rows_step)

``ingest_csv`` never raises for expected failures (missing/invalid table
name, no BML query, missing SQL files, bad CSV, schema mismatch, DB
unavailable): each is logged through Raven with a stable error code and
returned as an ``IngestResult`` with ``status="failed"``/``"skipped"``, so a
batch of CSVs keeps going past one bad file.
"""
from __future__ import annotations

from pathlib import Path

from aryx.csv_bml_ingestion import constants as C
from aryx.csv_bml_ingestion.bml_index import BmlIndex, BmlLookup
from aryx.csv_bml_ingestion.csv_reader import read_layout
from aryx.csv_bml_ingestion.db import ConnectionFactory, execute_statements
from aryx.csv_bml_ingestion.errors import CsvBmlIngestionError
from aryx.csv_bml_ingestion.options import IngestOptions, IngestResult
from aryx.csv_bml_ingestion.overflow import OverflowPolicy
from aryx.csv_bml_ingestion.rows_step import load_csv_into_table
from aryx.csv_bml_ingestion.sql_catalog import load_sql_artifacts
from aryx.csv_bml_ingestion.table_name import extract_table_name
from aryx.csv_bml_ingestion.tracking import RunTracker


def ingest_csv(
    csv_path: str | Path | None,
    bml_index: BmlIndex,
    factory: ConnectionFactory,
    *,
    replace: bool = True,
    batch_size: int = C.DEFAULT_BATCH_SIZE,
    sql_root: Path = C.SQL_ROOT,
    overflow: OverflowPolicy = OverflowPolicy.REJECT,
    rejects_dir: Path | None = None,
) -> IngestResult:
    """Run the full pipeline for ``csv_path``.

    Args:
        csv_path: The CSV file; its stem is the target table name.
        bml_index: Pre-built index of the XML graph (build once, reuse).
        factory: Connection factory (see ``db.oracle_connection_factory``).
        replace: Delete existing rows before loading (default, full refresh).
        batch_size: Rows per ``executemany`` batch.
        sql_root: Directory holding ``<table>/schema.sql`` + ``indexes.sql``.
        overflow: What to do with values that exceed their column
            (``reject`` default, ``truncate``, ``fail``) — see ``overflow``.
        rejects_dir: Where ``<table>.rejects.csv`` is written (default: the CSV's directory).
    """
    opts = IngestOptions(replace, batch_size, sql_root, overflow, rejects_dir)
    source = Path(str(csv_path)).name if csv_path else "<none>"
    result, tracker = IngestResult(source=source), RunTracker(source)
    tracker.info(C.STEP_RUN, "ingestion started", csv_path=str(csv_path))
    try:
        _run(result, tracker, csv_path, bml_index, factory, opts)
    except CsvBmlIngestionError as exc:
        result.status, result.error_code, result.message = "failed", exc.code, str(exc)
        tracker.error(C.STEP_RUN, f"ingestion failed: {exc}", error_code=exc.code, table=result.table)
    except Exception as exc:  # noqa: BLE001 -- unexpected: log with full detail, keep the batch alive
        result.status, result.error_code, result.message = "failed", "CBI_UNEXPECTED", repr(exc)
        tracker.error(C.STEP_RUN, f"unexpected failure: {exc!r}", error_code="CBI_UNEXPECTED",
                      table=result.table)
    else:
        tracker.info(C.STEP_RUN, f"ingestion finished status={result.status}", table=result.table,
                     rows_loaded=result.rows_loaded, rows_bad=result.rows_bad)
    return result


def _run(result: IngestResult, tracker: RunTracker, csv_path, bml_index: BmlIndex,
         factory: ConnectionFactory, opts: IngestOptions) -> None:
    table = _step_table_name(result, tracker, csv_path)
    if not _step_bml_lookup(result, tracker, bml_index, table):
        return
    read_layout(Path(str(csv_path)))  # fail on a malformed CSV before any DDL runs
    _step_apply_schema(tracker, factory, table, opts)
    load_csv_into_table(Path(str(csv_path)), table, factory, opts, tracker, result)


def _step_table_name(result: IngestResult, tracker: RunTracker, csv_path) -> str:
    """Step 1 (negative flow: missing / unsafe name raises, caught by ``ingest_csv``)."""
    try:
        table = extract_table_name(csv_path)
    except CsvBmlIngestionError as exc:
        tracker.error(C.STEP_TABLE_NAME, f"cannot determine target table: {exc}", error_code=exc.code)
        raise
    result.table = table
    tracker.info(C.STEP_TABLE_NAME, f"target table={table}", table=table)
    return table


def _step_bml_lookup(result: IngestResult, tracker: RunTracker, bml_index: BmlIndex, table: str) -> bool:
    """Step 2 — both sides lowercase; returns False (run skipped) when no BML query reads the table."""
    lookup = bml_index.lookup(table)
    result.bml_scripts = [m.script_id for m in lookup.matches]
    if lookup.matches:
        _log_matches(tracker, lookup)
        return True
    result.status, result.error_code = "skipped", "CBI_BML_NOT_FOUND"
    result.message = f"no BML query reads table {table!r}"
    tracker.error(C.STEP_BML_LOOKUP, result.message + " — skipping (no schema can be derived)",
                  error_code="CBI_BML_NOT_FOUND", table=table, near_misses=list(lookup.near_misses),
                  scripts_scanned=bml_index.script_count)
    return False


def _log_matches(tracker: RunTracker, lookup: BmlLookup) -> None:
    tracker.info(
        C.STEP_BML_LOOKUP, f"found {len(lookup.matches)} BML script(s) querying {lookup.table}",
        table=lookup.table, scripts=[m.script_id for m in lookup.matches],
        queries=[q.sql[:200] for m in lookup.matches for q in m.queries][:6],
    )


def _step_apply_schema(tracker: RunTracker, factory: ConnectionFactory, table: str,
                       opts: IngestOptions) -> None:
    """Step 3 — load the committed SQL files and apply schema, then indexes."""
    artifacts = load_sql_artifacts(table, opts.sql_root)
    tracker.info(C.STEP_SQL_ARTIFACTS, "loaded schema/index SQL", table=table,
                 schema_statements=len(artifacts.schema_statements),
                 index_statements=len(artifacts.index_statements), directory=str(artifacts.directory))
    ran = execute_statements(factory, artifacts.schema_statements + artifacts.index_statements)
    tracker.info(C.STEP_APPLY_SCHEMA, f"applied {ran} DDL statements", table=table)
