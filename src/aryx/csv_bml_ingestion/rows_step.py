"""Step 4 — validate the CSV against the live table and load it.

Order: parse the meta block -> read the table's real column limits -> check
every CSV column exists in the table -> stream rows through the overflow
guard into batched inserts (one transaction).
"""
from __future__ import annotations

from pathlib import Path

from aryx.csv_bml_ingestion import constants as C
from aryx.csv_bml_ingestion.column_limits import fetch_column_limits
from aryx.csv_bml_ingestion.csv_reader import CsvStats, iter_rows, read_layout
from aryx.csv_bml_ingestion.db import ConnectionFactory, load_rows
from aryx.csv_bml_ingestion.errors import SchemaMismatchError
from aryx.csv_bml_ingestion.options import IngestOptions, IngestResult
from aryx.csv_bml_ingestion.overflow import OverflowReport, guard_rows
from aryx.csv_bml_ingestion.tracking import RunTracker


def load_csv_into_table(csv_file: Path, table: str, factory: ConnectionFactory,
                        opts: IngestOptions, tracker: RunTracker, result: IngestResult) -> None:
    """Load ``csv_file`` into ``table``; fills ``result`` (status ``loaded`` on success)."""
    layout = read_layout(csv_file)
    limits = fetch_column_limits(factory, table)
    if not limits:
        raise SchemaMismatchError(f"table {table!r} not found in the database after applying its schema")
    missing = [c for c in layout.columns if c not in limits]
    if missing:
        raise SchemaMismatchError(
            f"CSV columns not in table {table!r}: {missing} — update sql/{table}/schema.sql to match the CSV header"
        )
    tracker.info(C.STEP_CSV_INGEST, "loading rows", table=table, columns=len(layout.columns),
                 replace=opts.replace, overflow_policy=opts.overflow.value)

    stats, report = CsvStats(), OverflowReport()
    rejects_path = (opts.rejects_dir or csv_file.parent) / f"{table}.rejects.csv"
    rows = guard_rows(iter_rows(csv_file, layout, stats), layout.columns, limits,
                      opts.overflow, report, rejects_path)
    loaded = load_rows(
        factory, table, layout.columns, rows, batch_size=opts.batch_size, replace=opts.replace,
        on_batch=lambda n: tracker.debug(C.STEP_CSV_INGEST, f"{n} rows inserted so far", table=table),
    )
    _finish(result, tracker, table, loaded, stats, report)


def _finish(result: IngestResult, tracker: RunTracker, table: str, loaded: int,
            stats: CsvStats, report: OverflowReport) -> None:
    result.status, result.rows_loaded = "loaded", loaded
    result.rows_bad, result.rows_rejected = stats.rows_bad, report.rows_rejected
    result.rows_truncated = report.rows_truncated
    result.rejects_file = str(report.rejects_file or "")
    if stats.rows_bad:
        tracker.warn(C.STEP_CSV_INGEST, f"{stats.rows_bad} malformed rows skipped",
                     error_code="CBI_BAD_ROWS", table=table, samples=stats.bad_samples)
    if report.rows_rejected or report.rows_truncated:
        tracker.warn(
            C.STEP_CSV_INGEST,
            f"{report.rows_rejected} rows rejected and {report.rows_truncated} truncated for exceeding "
            f"column limits; widen the column in sql/{table}/schema.sql if these values are legitimate",
            error_code="CBI_VALUE_TOO_LONG", table=table, by_column=dict(report.by_column),
            longest=report.longest, samples=report.samples, rejects_file=result.rejects_file,
        )
    tracker.info(C.STEP_CSV_INGEST, f"loaded {loaded} rows into {table}", table=table, rows_loaded=loaded,
                 rows_bad=stats.rows_bad, rows_rejected=report.rows_rejected,
                 rows_truncated=report.rows_truncated)
