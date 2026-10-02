"""Entry point for the file-upload path: ingest uploaded CSVs via the stored XML knowledge graph.

``aryx.api.file_ingest.file_ingest_run`` creates one ``CsvBmlUploadSession`` per upload job
(when ``ARYX_CSV_BML_ENABLED`` is on) and calls ``ingest`` for each ``.csv``. A CSV's table name
must be read by a query in an XML knowledge graph already ingested into the same workspace;
otherwise it is skipped with ``CBI_BML_NOT_FOUND`` (never silently ingested another way).

Isolation: authored SQL and rejects live under ``<sql root>/ws_<workspace_id>/``, and tables
are owned per workspace (``csv_bml_ingestion:ws=<id>``), so one workspace cannot read or
overwrite another's SQL, rejects or tables, nor any application table (see ``ownership``).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from aryx.csv_bml_ingestion.constants import default_sql_root
from aryx.csv_bml_ingestion.errors import CsvBmlIngestionError
from aryx.csv_bml_ingestion.options import IngestResult
from aryx.csv_bml_ingestion.ownership import workspace_owner
from aryx.csv_bml_ingestion.table_naming import physical_table

logger = logging.getLogger(__name__)
REJECTS_DIR_ENV = "ARYX_CSV_BML_REJECTS_DIR"


class CsvBmlUploadSession:
    """One upload job's view of the workspace: connection and graph lookup built once, lazily."""

    def __init__(self, workspace_id: int, job_id: str | None = None) -> None:
        self.workspace_id = int(workspace_id)
        self.job_id = job_id
        self._factory = None
        self._lookup = None

    def _ready(self):  # noqa: ANN202
        if self._lookup is None:
            from aryx.csv_bml_ingestion.db import oracle_connection_factory  # noqa: PLC0415
            from aryx.csv_bml_ingestion.stored_graph import StoredGraphLookup  # noqa: PLC0415

            self._factory = oracle_connection_factory()
            self._lookup = StoredGraphLookup(self._factory, self.workspace_id)
        return self._factory, self._lookup

    def ingest(self, data: bytes, filename: str) -> IngestResult:
        """Ingest uploaded CSV ``data`` named ``filename``. Never raises; returns a result.

        A run that was skipped, failed, or had rejected rows is also stored (best effort) so the
        UI can show it and offer a re-run; see ``issue_store``.
        """
        result = self._ingest(data, filename)
        self._record(result, data)
        return result

    def _record(self, result: IngestResult, data: bytes) -> None:
        if self._factory is None:           # failed before a database connection existed
            return
        try:
            from aryx.csv_bml_ingestion.issue_store import IssueStore, should_record  # noqa: PLC0415

            store = IssueStore(self._factory)
            if should_record(result):
                result.run_id = store.record_run(self.workspace_id, self.job_id, result, data)
            if result.status == "loaded" or result.run_id:
                store.supersede_older(self.workspace_id, result.source, result.physical_table or result.table,
                                      result.run_id,
                                      reloaded=result.status == "loaded")
        except Exception as exc:  # noqa: BLE001 -- storing issues must never fail the upload itself
            logger.warning("csv_bml_ingestion: could not store issues for %r: %r", result.source, exc)

    def _ingest(self, data: bytes, filename: str) -> IngestResult:
        safe_name = Path(str(filename)).name or "upload.csv"
        try:
            from aryx.csv_bml_ingestion.llm_client import project_llm_completer  # noqa: PLC0415
            from aryx.csv_bml_ingestion.pipeline import ingest_csv  # noqa: PLC0415

            factory, lookup = self._ready()
            sql_root = default_sql_root() / f"ws_{self.workspace_id}"
            rejects = Path(os.environ.get(REJECTS_DIR_ENV, "").strip() or sql_root / "_rejects")
            with TemporaryDirectory() as tmp:
                path = Path(tmp) / safe_name
                path.write_bytes(data)
                return ingest_csv(path, lookup, factory, sql_root=sql_root, rejects_dir=rejects,
                                  sql_author=project_llm_completer(),
                                  owner=workspace_owner(self.workspace_id),
                                  physical_table=lambda logical: physical_table(logical, self.workspace_id))
        except CsvBmlIngestionError as exc:
            return IngestResult(source=safe_name, status="failed", error_code=exc.code, message=str(exc))
        except Exception as exc:  # noqa: BLE001 -- one bad file must not abort the rest of the upload
            logger.warning("csv_bml_ingestion: upload of %r failed unexpectedly: %r", safe_name, exc)
            return IngestResult(source=safe_name, status="failed", error_code="CBI_UNEXPECTED",
                                message=f"unexpected {type(exc).__name__}; see the log for details")
