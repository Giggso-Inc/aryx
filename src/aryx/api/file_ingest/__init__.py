"""File-ingest API package (Phase 8a folder restructuring,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Split out of
`api/file_ingest_*.py`'s flat files in `src/aryx/api/` into their own
package; every name re-exported here so any caller that imports from
the package root instead of a specific submodule keeps working.
"""

from aryx.api.file_ingest.file_ingest_api import (
    file_ingest_router,
    shutdown_executor,
    _get_executor,
)
from aryx.api.file_ingest.file_ingest_limits import (
    _ALL,
    _DATA_EXTS,
    _DOC_EXTS,
    _FK_REQUIRED_KEYS,
    _MAX_FILE,
    _MAX_FILES,
    _MAX_TOTAL,
)
from aryx.api.file_ingest.file_ingest_run import (
    _chunk_csv_bytes,
    _make_should_stop,
    _run_files,
    _save_tmp,
)

__all__ = [
    "file_ingest_router",
    "shutdown_executor",
    "_get_executor",
    "_ALL",
    "_DATA_EXTS",
    "_DOC_EXTS",
    "_FK_REQUIRED_KEYS",
    "_MAX_FILE",
    "_MAX_FILES",
    "_MAX_TOTAL",
    "_chunk_csv_bytes",
    "_make_should_stop",
    "_run_files",
    "_save_tmp",
]
