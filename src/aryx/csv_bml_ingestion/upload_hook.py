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

from aryx.csv_bml_ingestion.constants import OWNER_TAG, default_sql_root
from aryx.csv_bml_ingestion.errors import CsvBmlIngestionError
from aryx.csv_bml_ingestion.options import IngestResult

logger = logging.getLogger(__name__)
REJECTS_DIR_ENV = "ARYX_CSV_BML_REJECTS_DIR"


class CsvBmlUploadSession:
    """One upload job's view of the workspace: connection and graph lookup built once, lazily."""

    def __init__(self, workspace_id: int) -> None:
        self.workspace_id = int(workspace_id)
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
        """Ingest uploaded CSV ``data`` named ``filename``. Never raises; returns a result."""
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
                                  owner=f"{OWNER_TAG}:ws={self.workspace_id}")
        except CsvBmlIngestionError as exc:
            return IngestResult(source=safe_name, status="failed", error_code=exc.code, message=str(exc))
        except Exception as exc:  # noqa: BLE001 -- one bad file must not abort the rest of the upload
            logger.warning("csv_bml_ingestion: upload of %r failed unexpectedly: %r", safe_name, exc)
            return IngestResult(source=safe_name, status="failed", error_code="CBI_UNEXPECTED",
                                message=f"unexpected {type(exc).__name__}; see the log for details")
