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

import logging
from pathlib import Path
from typing import Callable

from aryx.csv_bml_ingestion import constants as C
from aryx.csv_bml_ingestion.bml_index import BmlIndex, BmlLookup
from aryx.csv_bml_ingestion.csv_reader import profile_max_bytes, read_layout
from aryx.csv_bml_ingestion.db import ConnectionFactory, execute_statements
from aryx.csv_bml_ingestion.engine_shapes import engine_shape_of_columns, load_engine_tables_enabled
from aryx.csv_bml_ingestion.errors import (
    CsvBmlIngestionError, SqlArtifactsMissingError, SqlAuthoringError, SqlUnsafeError,
)
from aryx.csv_bml_ingestion.options import IngestOptions, IngestResult
from aryx.csv_bml_ingestion.ownership import claim_new_table, require_owned_or_absent
from aryx.csv_bml_ingestion.overflow import OverflowPolicy
from aryx.csv_bml_ingestion.rows_step import load_csv_into_table
from aryx.csv_bml_ingestion.sql_author import Completer, author_sql, author_sql_from_layout
from aryx.csv_bml_ingestion.sql_catalog import load_sql_artifacts
from aryx.csv_bml_ingestion.sql_validate import validate_statements
from aryx.csv_bml_ingestion.table_name import extract_table_name
from aryx.csv_bml_ingestion.table_naming import rename_statements
from aryx.csv_bml_ingestion.tracking import RunTracker


def ingest_csv(
    csv_path: str | Path | None,
    bml_index: BmlIndex,
    factory: ConnectionFactory,
    *,
    replace: bool = True,
    batch_size: int = C.DEFAULT_BATCH_SIZE,
    sql_root: Path | None = None,
    overflow: OverflowPolicy = OverflowPolicy.REJECT,
    rejects_dir: Path | None = None,
    sql_author: Completer | None = None,
    owner: str = C.OWNER_TAG,
    physical_table: Callable[[str], str] | None = None,
) -> IngestResult:
    """Run the full pipeline for ``csv_path``.

    Args:
        csv_path: The CSV file; its stem is the target table name.
        bml_index: Pre-built index of the XML graph (build once, reuse).
        factory: Connection factory (see ``db.oracle_connection_factory``).
        replace: Delete existing rows before loading (default, full refresh).
        batch_size: Rows per ``executemany`` batch.
        sql_root: Directory holding ``<table>/schema.sql`` + ``indexes.sql`` (default:
            ``ARYX_CSV_BML_SQL_DIR`` or the package ``sql/`` folder).
        overflow: What to do with values that exceed their column
            (``reject`` default, ``truncate``, ``fail``) — see ``overflow``.
        sql_author: LLM completer used to author ``sql/<table>/`` when a BML query exists but the files
            do not (see ``sql_author``); ``None`` disables authoring.
        owner: Ownership tag. Only a table this pipeline created with the same tag (or an
            administrator adopted via COMMENT ON TABLE) is ever loaded into; any other
            existing table is refused with CBI_TABLE_PROTECTED.
        physical_table: Maps the logical table name (file stem) to the Oracle table actually used, e.g.
            ``ws7_attrsequence`` (see ``table_naming``). Called only AFTER step 2, which always matches
            on the logical name. ``None`` keeps the logical name (the CLI default).
        rejects_dir: Where ``<table>.rejects.csv`` is written (default: the CSV's directory).
    """
    opts = IngestOptions(replace, batch_size, sql_root, overflow, rejects_dir, sql_author, owner, physical_table)
    source = Path(str(csv_path)).name if csv_path else "<none>"
    result, tracker = IngestResult(source=source), RunTracker(source)
    tracker.info(C.STEP_RUN, "ingestion started", csv_path=str(csv_path))
    try:
        _run(result, tracker, csv_path, bml_index, factory, opts)
    except CsvBmlIngestionError as exc:
        result.status, result.error_code, result.message = "failed", exc.code, str(exc)
        tracker.error(C.STEP_RUN, f"ingestion failed: {exc}", error_code=exc.code, table=result.table)
    except Exception as exc:  # noqa: BLE001 -- unexpected: log with full detail, keep the batch alive
        result.status, result.error_code = "failed", "CBI_UNEXPECTED"
        result.message = f"unexpected {type(exc).__name__}; see the Raven log for details"
        tracker.error(C.STEP_RUN, f"unexpected failure: {exc!r}", error_code="CBI_UNEXPECTED",
                      table=result.table)
    else:
        tracker.info(C.STEP_RUN, f"ingestion finished status={result.status}", table=result.table,
                     rows_loaded=result.rows_loaded, rows_bad=result.rows_bad)
    return result


def _run(result: IngestResult, tracker: RunTracker, csv_path, bml_index: BmlIndex,
         factory: ConnectionFactory, opts: IngestOptions) -> None:
    table = _step_table_name(result, tracker, csv_path)
    csv_file = Path(str(csv_path))
    lookup = _step_bml_lookup(result, tracker, bml_index, table, csv_file)
    if lookup is None:
        return
    read_layout(csv_file)  # fail on a malformed CSV before any SQL is authored or run
    physical = opts.physical_table(table) if opts.physical_table else table   # only after step 2
    result.physical_table = physical
    if physical != table:
        tracker.info(C.STEP_BML_LOOKUP, f"workspace table name {physical}", table=table, physical_table=physical)
    _step_apply_schema(tracker, factory, table, physical, opts, csv_file, lookup)
    load_csv_into_table(csv_file, physical, factory, opts, tracker, result, logical=table)
    if not lookup.matches:
        _warn_over_read_cap(tracker, table, physical, result.rows_loaded)


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


def _step_bml_lookup(result: IngestResult, tracker: RunTracker, bml_index: BmlIndex,
                     table: str, csv_file: Path | None = None) -> BmlLookup | None:
    """Step 2 — both sides lowercase; returns None (run skipped) when no BML query reads the table.

    A table no script reads is still loaded when the CPQ engine reads that table shape (``engine_shapes``): the
    returned lookup then has no matches, and step 3 derives the schema from the CSV header instead of from queries.
    """
    lookup = bml_index.lookup(table)
    result.bml_scripts = [m.label for m in lookup.matches]
    if lookup.matches:
        _log_matches(tracker, lookup)
        return lookup
    shape = _engine_shape(csv_file) if csv_file is not None else None
    if shape:
        tracker.info(C.STEP_BML_LOOKUP, f"no BML query reads table {table!r}, but the engine reads this table shape "
                     f"({shape}); loading it with a schema derived from the CSV header", table=table,
                     engine_shape=shape, source_graph=lookup.source)
        return BmlLookup(table=table, matches=(), near_misses=lookup.near_misses, source=lookup.source)
    result.status, result.error_code = "skipped", "CBI_BML_NOT_FOUND"
    result.message = f"no BML query reads table {table!r}" + (f" (searched the {lookup.source})" if lookup.source else "")
    tracker.error(C.STEP_BML_LOOKUP, result.message + " — skipping (no schema can be derived)",
                  error_code="CBI_BML_NOT_FOUND", table=table, near_misses=list(lookup.near_misses),
                  scripts_scanned=bml_index.script_count, source_graph=lookup.source)
    return None


def _log_matches(tracker: RunTracker, lookup: BmlLookup) -> None:
    tracker.info(
        C.STEP_BML_LOOKUP, f"found {len(lookup.matches)} query location(s) reading {lookup.table}",
        table=lookup.table, scripts=[m.label for m in lookup.matches], source_graph=lookup.source,
        queries=[q.sql[:200] for m in lookup.matches for q in m.queries][:6],
    )


def _step_apply_schema(tracker: RunTracker, factory: ConnectionFactory, table: str, physical: str,
                       opts: IngestOptions, csv_file: Path, lookup: BmlLookup) -> None:
    """Step 3 — load (or, if absent and enabled, LLM-author) the SQL files, then apply them.

    The SQL files and the validator use the logical ``table``; the statements are applied to ``physical``.
    """
    existed = require_owned_or_absent(factory, physical, opts.owner)   # first: before any LLM call, DDL or DELETE
    try:
        artifacts = load_sql_artifacts(table, opts.sql_root)
    except SqlArtifactsMissingError:
        layout = read_layout(csv_file)
        if not lookup.matches:       # no script reads it: the engine does (step 2), so derive the schema from the CSV
            author_sql_from_layout(table, layout, profile_max_bytes(csv_file, layout), tracker, opts.sql_root)
        elif opts.sql_author is None:
            raise
        else:
            author_sql(table, layout, profile_max_bytes(csv_file, layout), lookup, opts.sql_author, tracker,
                       opts.sql_root)
        artifacts = load_sql_artifacts(table, opts.sql_root)
    try:
        validate_statements(artifacts.schema_statements, artifacts.index_statements, table)
    except SqlAuthoringError as exc:
        raise SqlUnsafeError(f"SQL files in {artifacts.directory} failed the safety validator: {exc}") from exc
    tracker.info(C.STEP_SQL_ARTIFACTS, "loaded schema/index SQL", table=table,
                 schema_statements=len(artifacts.schema_statements),
                 index_statements=len(artifacts.index_statements), directory=str(artifacts.directory))
    statements = rename_statements(artifacts.schema_statements + artifacts.index_statements, table, physical)
    n_schema = len(artifacts.schema_statements)
    ran = execute_statements(factory, statements[:n_schema])
    if not existed:
        # Stamp before the indexes: DDL auto-commits, so if an index statement fails the table must already be
        # ours, or the next run would refuse our own table (CBI_TABLE_PROTECTED).
        claim_new_table(factory, physical, opts.owner)
    ran += execute_statements(factory, statements[n_schema:])
    tracker.info(C.STEP_APPLY_SCHEMA, f"applied {ran} DDL statements", table=table, physical_table=physical,
                 created=not existed)


def _engine_shape(csv_file: Path) -> str | None:
    """The engine Data Table shape of this CSV's columns, or None (also None when the switch is off or unreadable)."""
    if not load_engine_tables_enabled():
        return None
    try:
        return engine_shape_of_columns(read_layout(csv_file).columns)
    except CsvBmlIngestionError:
        return None          # a malformed CSV is reported by the step that reads it, not here
    except Exception:  # noqa: BLE001 -- e.g. an ImportError from the engine package: say so, then behave as before
        logging.getLogger(__name__).warning(
            "csv_bml_ingestion: engine table shape check failed for %s; treating it as not an engine table",
            csv_file.name, exc_info=True)
        return None


def _warn_over_read_cap(tracker: RunTracker, table: str, physical: str, rows_loaded: int) -> None:
    """An engine table no script reads was loaded in full; the engine reader stops at its own row cap."""
    from aryx.cpq.rdb.rdb_workspace_tables import MAX_ROWS_ENV, max_rows  # noqa: PLC0415

    cap = max_rows()
    if rows_loaded > cap:
        tracker.warn(C.STEP_CSV_INGEST, f"{physical} holds {rows_loaded} rows, more than the engine reads "
                     f"({MAX_ROWS_ENV}={cap}); the engine will see only the first {cap}", table=table,
                     physical_table=physical, rows_loaded=rows_loaded, read_cap=cap)
