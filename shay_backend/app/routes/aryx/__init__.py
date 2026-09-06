"""Aryx bridge: ask + document ingestion.

Wires Prism7's Orchestrator (via Shay backend) to Aryx's REST API — plain
HTTP calls, no MCP layer. See docs/Aryx_Prism7_REST_Integration.docx for the
architecture rationale.

Every route here resolves the caller's Shay workspace_id to its bridged
Aryx workspace_id via the existing GET /admin/shay/workspaces/{id}/mapping
endpoint (the same lookup workspaces.py's delete/purge routes already use),
then calls the corresponding Aryx endpoint with the same shared-secret
header (_aryx_headers(), reused from workspaces.py) already used by
workspaces/ensure today.

Known limitation: /documents/{discovery_id}/summary and .../confirm are
gated by the caller having an active role in {workspace_id}, but Aryx's
discovery_id is not itself associated with a workspace on the Aryx side
(discoveries.py has no owning-workspace check) — a caller who is a member
of ANY workspace and knows another workspace's discovery_id could act on
it. Closing this gap requires an Aryx-side change (out of scope per this
integration's "zero Aryx changes" goal) — until then, treat discovery_id
as sensitive, short-lived, and never expose it outside the requesting
session.

This package was split from a single flat file (app/routes/aryx.py) to keep
each module under the house style's 150-line limit:
  - _shared.py     — timeouts, error mapping, workspace-access helpers
  - _ask.py         — POST /workspaces/{workspace_id}/ask
  - _documents.py   — read/summary/confirm document endpoints
  - _jobs.py        — job status polling endpoint

Three names are re-exported below because other modules import them
directly from this flat path (app/routes/aryx.py), and that import surface
must keep working unchanged after the split:
  - call_aryx_docs_read      (app/routes/datasources/_upload_bulk_files_aryx_setup.py,
                               app/routes/datasources/_upload_bulk_files_item.py)
  - _resolve_aryx_workspace_id (app/routes/datasources/_upload_bulk_files_aryx_setup.py)
  - call_aryx_job_status      (app/routes/datasources/_embedding_helpers/_aryx_status.py)
"""

from fastapi import APIRouter

from app.routes.aryx._ask import router as _ask_router
from app.routes.aryx._documents import call_aryx_docs_read, router as _documents_router
from app.routes.aryx._jobs import call_aryx_job_status, router as _jobs_router
from app.routes.aryx._shared import _resolve_aryx_workspace_id

router = APIRouter()
router.include_router(_ask_router)
router.include_router(_documents_router)
router.include_router(_jobs_router)

__all__ = [
    "router",
    "call_aryx_docs_read",
    "call_aryx_job_status",
    "_resolve_aryx_workspace_id",
]
