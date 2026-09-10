"""
Shared helpers for the workspaces package: UUID coercion, workspace lookup,
response serialization, and the Aryx-bridge HTTP calls used across the
create/list/get/update/delete/purge endpoints.

Split from app/routes/workspaces.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceResponse


def _to_uuid(value: str, name: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {name} format",
        ) from exc


async def _get_workspace_or_404(db: AsyncSession, workspace_id: str) -> Workspace:
    """Load a workspace by route param, normalizing UUID input consistently."""
    workspace_uuid = _to_uuid(workspace_id, "workspace_id")
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_uuid))
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    return workspace


def serialize_workspace(workspace: Workspace) -> WorkspaceResponse:
    """Convert ORM workspace rows into the API response shape."""
    return WorkspaceResponse(
        id=str(workspace.id),
        name=workspace.name,
        description=workspace.description,
        company_id=str(workspace.company_id),
        is_active=workspace.is_active,
        is_public=workspace.is_public,
        ai_enabled=workspace.ai_enabled,
        ai_provider=workspace.ai_provider,
        ai_model=workspace.ai_model,
        max_messages=workspace.max_messages,
        max_attachments=workspace.max_attachments,
        workspace_type=workspace.workspace_type,
        user_id=str(workspace.user_id) if workspace.user_id else None,
        created_by=str(workspace.created_by) if workspace.created_by else None,
        settings=workspace.settings,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


def _aryx_headers() -> dict[str, str]:
    """Build auth headers for internal Shay -> Aryx service calls."""
    key = (settings.ARYX_INTERNAL_API_KEY or "").strip()
    if not key:
        raise RuntimeError("ARYX_INTERNAL_API_KEY is required for Shay bridge calls")
    return {
        "Content-Type": "application/json",
        "x-aryx-api-key": key,
    }


async def _ensure_aryx_workspace_bridge(_request: Request, workspace: Workspace) -> dict[str, Any]:
    """Create or reuse the Aryx bridge for a newly created Shay workspace."""
    import logging as _logging
    _log = _logging.getLogger(__name__)
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{settings.ARYX_API_URL_INTERNAL}/admin/shay/workspaces/ensure",
            json={
                "shay_workspace_id": str(workspace.id),
                "name": workspace.name,
                "description": workspace.description or "",
                "company_id": str(workspace.company_id),
            },
            headers=_aryx_headers(),
        )
        if response.is_error:
            _log.error(
                "aryx bridge error status=%d workspace=%s body=%s",
                response.status_code, workspace.id, response.text[:500],
            )
        response.raise_for_status()
        return response.json()


async def _delete_aryx_workspace_bridge(aryx_workspace_id: Any) -> None:
    """Delete the paired Aryx workspace for a Shay workspace."""
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.delete(
            f"{settings.ARYX_API_URL_INTERNAL}/admin/workspaces/{aryx_workspace_id}",
            headers=_aryx_headers(),
        )
        response.raise_for_status()


async def _update_aryx_workspace_bridge(
    _request: Request,
    aryx_workspace_id: Any,
    workspace: Workspace,
) -> dict[str, Any]:
    """Keep the bridged Aryx workspace metadata aligned with Shay workspace edits."""
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.put(
            f"{settings.ARYX_API_URL_INTERNAL}/admin/workspaces/{aryx_workspace_id}",
            json={
                "name": workspace.name,
                "description": workspace.description or "",
            },
            headers=_aryx_headers(),
        )
        response.raise_for_status()
        return response.json()


async def _bridge_for_workspace(request: Request, workspace: Workspace) -> dict[str, Any] | None:
    """Return the Aryx bridge mapping for a Shay workspace, creating it when missing."""
    bridge = await _ensure_aryx_workspace_bridge(request, workspace)
    return bridge
