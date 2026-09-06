"""Aryx bridge: document read/summary/confirm endpoints.

Split out of the original app/routes/aryx.py — see app/routes/aryx/__init__.py
for the full module-level docstring describing the bridge architecture.

call_aryx_docs_read is also imported directly by
app/routes/datasources/_upload_bulk_files_aryx_setup.py's kind="aryx" bulk
upload integration — see app/routes/aryx/__init__.py's re-export.
"""

from typing import Any, List

import httpx
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.routes.aryx._shared import (
    _TIMEOUT_BRIDGE,
    _TIMEOUT_UPLOAD,
    _raise_for_bridge_error,
    _require_workspace_access,
    _resolve_aryx_workspace_id,
)
from app.routes.workspaces import _aryx_headers
from app.schemas.aryx import AryxDocsConfirmRequest, AryxDocsConfirmResponse, AryxDocsReadResponse, AryxDocsSummaryResponse

router = APIRouter()


async def call_aryx_docs_read(
    aryx_workspace_id: int,
    files: List[tuple],
    context: str = "",
) -> dict[str, Any]:
    """Call Aryx's POST /admin/docs/read directly — the reusable core of the
    read_documents route below, also used by datasources.py's kind="aryx"
    bulk-upload integration so that path doesn't have to make a self-loopback
    HTTP call into this same service.

    Args:
        aryx_workspace_id: already-resolved Aryx integer workspace id.
        files: list of (filename, content_bytes, content_type) tuples —
               already read into memory by the caller.
        context: optional free-text context passed through to Aryx.
    """
    upload_files = [("files", (fname, content, ctype)) for fname, content, ctype in files]
    async with httpx.AsyncClient(timeout=_TIMEOUT_UPLOAD) as client:
        try:
            resp = await client.post(
                f"{settings.ARYX_API_URL_INTERNAL}/admin/docs/read",
                data={"context": context, "workspace_id": str(aryx_workspace_id)},
                files=upload_files,
                headers={"x-aryx-api-key": _aryx_headers()["x-aryx-api-key"]},
            )
            resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as exc:
            _raise_for_bridge_error(exc, "document read")
    return resp.json()


@router.post("/workspaces/{workspace_id}/documents/read", response_model=AryxDocsReadResponse)
async def read_documents(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    files: List[UploadFile] = File(...),
    context: str = Form(""),
) -> dict[str, Any]:
    """Upload one or more files and start Aryx's discovery (read) job.

    Request:  multipart/form-data — files=<one or more files>, context=<optional text>
    Response: {"discovery_id": "4442e079151b41b0817e70f75178a1b5"}

    The read job runs in the background on Aryx's side; poll
    GET /workspaces/{workspace_id}/jobs/{discovery_id} for progress, then
    call the summary/confirm routes below once it completes.
    """
    await _require_workspace_access(request, db, workspace_id)
    aryx_workspace_id = await _resolve_aryx_workspace_id(workspace_id)
    files_data = [(f.filename, await f.read(), f.content_type) for f in files]
    return await call_aryx_docs_read(aryx_workspace_id, files_data, context)


@router.get("/workspaces/{workspace_id}/documents/{discovery_id}/summary",
           response_model=AryxDocsSummaryResponse)
async def document_summary(
    workspace_id: str,
    discovery_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Discovered entity types/files for a completed (or in-progress) read job.

    Response: {"types": [{"type": "Invoice", "count": 42, "examples": [...]}, ...],
               "files": [{"filename": "x.csv", "ontology_type": "Widget"}, ...]}
    Returns {} if the read job hasn't produced a summary yet.
    """
    await _require_workspace_access(request, db, workspace_id)

    async with httpx.AsyncClient(timeout=_TIMEOUT_BRIDGE) as client:
        try:
            resp = await client.get(
                f"{settings.ARYX_API_URL_INTERNAL}/admin/docs/summary/{discovery_id}",
                headers=_aryx_headers(),
            )
            resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as exc:
            _raise_for_bridge_error(exc, "document summary lookup")
    return resp.json()


@router.post("/workspaces/{workspace_id}/documents/{discovery_id}/confirm",
            response_model=AryxDocsConfirmResponse)
async def confirm_documents(
    workspace_id: str,
    discovery_id: str,
    body: AryxDocsConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Confirm which discovered types/files to actually ingest into the graph.

    Request:  {"approved_types": ["Invoice", "Customer"], "approved_files": ["x.csv"]}
    Response: {"status": "queued", "job_id": "0c5844e2c0944efb89903511d93ccaa2"}

    Poll GET /workspaces/{workspace_id}/jobs/{job_id} for ingest progress.
    """
    await _require_workspace_access(request, db, workspace_id)

    async with httpx.AsyncClient(timeout=_TIMEOUT_BRIDGE) as client:
        try:
            resp = await client.post(
                f"{settings.ARYX_API_URL_INTERNAL}/admin/docs/confirm",
                json={
                    "discovery_id": discovery_id,
                    "approved_types": body.approved_types,
                    "approved_files": body.approved_files,
                },
                headers=_aryx_headers(),
            )
            resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as exc:
            _raise_for_bridge_error(exc, "document confirm")
    return resp.json()
