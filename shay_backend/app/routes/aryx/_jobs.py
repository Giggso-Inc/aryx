"""Aryx bridge: job status polling endpoint.

Split out of the original app/routes/aryx.py — see app/routes/aryx/__init__.py
for the full module-level docstring describing the bridge architecture.

call_aryx_job_status is also imported directly by
app/routes/datasources/_embedding_helpers/_aryx_status.py — see
app/routes/aryx/__init__.py's re-export.
"""

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.routes.aryx._shared import _TIMEOUT_BRIDGE, _raise_for_bridge_error, _require_workspace_access
from app.routes.workspaces import _aryx_headers
from app.schemas.aryx import AryxJobStatusResponse

router = APIRouter()


async def call_aryx_job_status(job_id: str) -> dict[str, Any]:
    """Call Aryx's GET /admin/jobs/{job_id} directly — reusable core of the
    job_status route below. Aryx's job endpoint is workspace-agnostic (job_id
    alone is sufficient), so no workspace resolution is needed here.

    Best-effort callers (e.g. datasources.py's status-merge) should catch the
    HTTPException this can raise and degrade gracefully rather than fail an
    otherwise-successful response.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT_BRIDGE) as client:
        try:
            resp = await client.get(
                f"{settings.ARYX_API_URL_INTERNAL}/admin/jobs/{job_id}",
                headers=_aryx_headers(),
            )
            if resp.status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
            resp.raise_for_status()
        except HTTPException:
            raise
        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as exc:
            _raise_for_bridge_error(exc, "job status lookup")
    return resp.json()


@router.get("/workspaces/{workspace_id}/jobs/{job_id}", response_model=AryxJobStatusResponse)
async def job_status(
    workspace_id: str,
    job_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Poll a read or confirm job's live progress (stage/pct/status)."""
    await _require_workspace_access(request, db, workspace_id)
    return await call_aryx_job_status(job_id)
