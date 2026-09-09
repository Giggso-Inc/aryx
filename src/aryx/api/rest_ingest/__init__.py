"""REST API ingest package (Phase 8a folder restructuring,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Split out of
`api/rest_ingest_*.py`'s flat files in `src/aryx/api/` into their own
package; every name re-exported here so any caller that imports from
the package root instead of a specific submodule keeps working.
"""

from aryx.api.rest_ingest.rest_ingest_api import rest_ingest_router
from aryx.api.rest_ingest.rest_ingest_job import _run_rest, _type_from_url
from aryx.api.rest_ingest.rest_ingest_models import RestIngestRequest, RestPreviewRequest

__all__ = [
    "rest_ingest_router",
    "_run_rest",
    "_type_from_url",
    "RestIngestRequest",
    "RestPreviewRequest",
]
