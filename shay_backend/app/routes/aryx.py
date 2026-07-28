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
"""

from typing import Any, List
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.routes.workspaces import _aryx_headers, _get_workspace_or_404
from app.schemas.aryx import (
    AryxAskRequest,
    AryxDocsConfirmRequest,
    AryxDocsConfirmResponse,
    AryxDocsReadResponse,
    AryxDocsSummaryResponse,
    AryxJobStatusResponse,
)
from app.utils.permissions import require_active_workspace_role

router = APIRouter()

_TIMEOUT_ASK = httpx.Timeout(60.0)      # LLM-backed; slower than a plain CRUD call
_TIMEOUT_BRIDGE = httpx.Timeout(30.0)   # matches workspaces.py's bridge calls
_TIMEOUT_UPLOAD = httpx.Timeout(120.0)  # file upload can be larger; read itself is async server-side


def _raise_for_bridge_error(exc: Exception, action: str) -> None:
    """Map an httpx/bridge failure to the same HTTPException shape workspaces.py uses."""
    if isinstance(exc, httpx.HTTPStatusError):
        detail = exc.response.text or str(exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Aryx {action} failed: {detail}") from exc
    if isinstance(exc, httpx.RequestError):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Aryx service unavailable: {exc}") from exc
    if isinstance(exc, RuntimeError):
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    raise exc


async def _resolve_aryx_workspace_id(shay_workspace_id: str) -> int:
    """Look up the Aryx workspace bridged to this Shay workspace.

    Reuses the same GET /admin/shay/workspaces/{id}/mapping lookup already
    used by workspaces.py's delete/purge routes — it does not create a
    mapping, so the workspace must already have gone through
    POST /admin/shay/workspaces/ensure (i.e. it was created via Shay's
    normal workspace-create flow).
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT_BRIDGE) as client:
        try:
            resp = await client.get(
                f"{settings.ARYX_API_URL_INTERNAL}/admin/shay/workspaces/{shay_workspace_id}/mapping",
                headers=_aryx_headers(),
            )
            if resp.status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    f"no Aryx mapping for Shay workspace {shay_workspace_id} — "
                    "create it via the workspace-create flow first",
                )
            resp.raise_for_status()
        except HTTPException:
            raise
        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as exc:
            _raise_for_bridge_error(exc, "workspace lookup")
    mapping = resp.json()
    return int(mapping["aryx_workspace_id"])


async def _require_workspace_access(
    request: Request, db: AsyncSession, workspace_id: str,
) -> None:
    """Same auth gate as the existing workspace routes: authenticated user,
    active membership in this specific Shay workspace."""
    user = await get_current_user_required(request)
    workspace = await _get_workspace_or_404(db, workspace_id)
    await require_active_workspace_role(db, user.id, UUID(str(workspace.id)))


@router.post("/workspaces/{workspace_id}/ask")
async def ask(
    workspace_id: str,
    body: AryxAskRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Ask a question against the tenant's Aryx knowledge graph.

    Request:  {"thread_id": "shay-thread-abc", "question": "..."}
    Response: Aryx's POST /admin/shay/chats/ask body verbatim — see
              AryxAskResponse for the exact shape (answer, terms,
              tools_called, usage, grounding, citations).
    """
    await _require_workspace_access(request, db, workspace_id)

    async with httpx.AsyncClient(timeout=_TIMEOUT_ASK) as client:
        try:
            resp = await client.post(
                f"{settings.ARYX_API_URL_INTERNAL}/admin/shay/chats/ask",
                json={
                    "shay_workspace_id": workspace_id,
                    "shay_thread_id": body.thread_id,
                    "question": body.question,
                },
                headers=_aryx_headers(),
            )
            resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as exc:
            _raise_for_bridge_error(exc, "ask")
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

    upload_files = []
    for f in files:
        content = await f.read()
        upload_files.append(("files", (f.filename, content, f.content_type)))

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


@router.get("/workspaces/{workspace_id}/jobs/{job_id}", response_model=AryxJobStatusResponse)
async def job_status(
    workspace_id: str,
    job_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Poll a read or confirm job's live progress (stage/pct/status)."""
    await _require_workspace_access(request, db, workspace_id)

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
