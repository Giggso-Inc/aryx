"""Document self-discovery API package (Phase 8a folder restructuring,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Split out of
`api/doc_discover_*.py`'s flat files in `src/aryx/api/` into their own
package; every name re-exported here so any caller that imports from
the package root instead of a specific submodule keeps working.
"""

from aryx.api.doc_discover.doc_discover_api import ConfirmRequest, doc_discover_router
from aryx.api.doc_discover.doc_discover_confirm_job import _confirm_job, _reset_discovery_status
from aryx.api.doc_discover.doc_discover_read_job import _build_read_progress, _read_job, _save_tmp

__all__ = [
    "ConfirmRequest",
    "doc_discover_router",
    "_confirm_job",
    "_reset_discovery_status",
    "_build_read_progress",
    "_read_job",
    "_save_tmp",
]
