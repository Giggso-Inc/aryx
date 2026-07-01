"""Workspace routes for CRUD operations."""

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID
import httpx
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import settings
from app.core.database import get_db
from app.core.auth import generate_workspace_id
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceResponse,
    WorkspaceList,
    WorkspaceStats
)
from app.services.workspace_membership import ensure_workspace_membership

router = APIRouter()
security = HTTPBearer()


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


async def _ensure_aryx_workspace_bridge(request: Request, workspace: Workspace) -> dict[str, Any]:
    """Create or reuse the Aryx bridge for a newly created Shay workspace."""
    headers = {}
    authorization = request.headers.get("authorization")
    if authorization:
        headers["Authorization"] = authorization
    headers["Content-Type"] = "application/json"

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
            headers=headers,
        )
        response.raise_for_status()
        return response.json()


async def _delete_aryx_workspace_bridge(aryx_workspace_id: Any) -> None:
    """Delete the paired Aryx workspace for a Shay workspace."""
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.delete(
            f"{settings.ARYX_API_URL_INTERNAL}/admin/workspaces/{aryx_workspace_id}",
        )
        response.raise_for_status()


async def _bridge_for_workspace(request: Request, workspace: Workspace) -> dict[str, Any] | None:
    """Return the Aryx bridge mapping for a Shay workspace, creating it when missing."""
    bridge = await _ensure_aryx_workspace_bridge(request, workspace)
    return bridge


@router.post("/", response_model=WorkspaceResponse)
async def create_workspace(
    workspace_data: WorkspaceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Create a new workspace"""
    user = await get_current_user_required(request)
    
    # Check if user can create workspaces
    if not user.can_manage_workspace(user.company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to create workspace"
        )
    
    now = datetime.utcnow()

    # Create workspace
    workspace = Workspace(
        id=generate_workspace_id(),
        name=workspace_data.name,
        description=workspace_data.description,
        company_id=user.company_id,
        is_public=workspace_data.is_public,
        ai_enabled=workspace_data.ai_enabled,
        ai_provider=workspace_data.ai_provider,
        ai_model=workspace_data.ai_model,
        settings=workspace_data.settings,
        workspace_type=workspace_data.workspace_type,   
        user_id=user.id,
        created_by=user.id,
        created_at=now,
        updated_at=now,
    )
    
    db.add(workspace)
    await db.flush()
    await ensure_workspace_membership(
        db,
        workspace=workspace,
        user=user,
        role="admin",
    )
    await db.commit()
    await db.refresh(workspace)
    try:
        bridge = await _bridge_for_workspace(request, workspace)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text or str(exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Aryx workspace bridge creation failed: {detail}",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Aryx service unavailable: {exc}",
        ) from exc

    payload = serialize_workspace(workspace).model_dump()
    payload["bridge"] = bridge
    return payload


@router.get("/", response_model=WorkspaceList)
async def list_workspaces(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None
):
    """List workspaces for current user"""
    user = await get_current_user_required(request)
    
    # Build query
    query = select(Workspace)
    
    # Filter by company (unless admin)
    if not user.is_admin:
        query = query.where(Workspace.company_id == user.company_id)
    
    # Add search filter
    if search:
        query = query.where(Workspace.name.ilike(f"%{search}%"))
    
    # Add pagination
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)
    
    # Execute query
    result = await db.execute(query)
    workspaces = result.scalars().all()
    
    # Get total count
    count_query = select(func.count(Workspace.id))
    if not user.is_admin:
        count_query = count_query.where(Workspace.company_id == user.company_id)
    if search:
        count_query = count_query.where(Workspace.name.ilike(f"%{search}%"))
    
    count_result = await db.execute(count_query)
    total = count_result.scalar()
    
    bridged_workspaces = []
    for workspace in workspaces:
        bridge = await _bridge_for_workspace(request, workspace)
        payload = serialize_workspace(workspace).model_dump()
        payload["bridge"] = bridge
        bridged_workspaces.append(payload)

    return {
        "workspaces": bridged_workspaces,
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get workspace by ID"""
    user = await get_current_user_required(request)
    workspace = await _get_workspace_or_404(db, workspace_id)
    
    # Check access permissions
    if not workspace.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to workspace"
        )
    
    bridge = await _bridge_for_workspace(request, workspace)
    payload = serialize_workspace(workspace).model_dump()
    payload["bridge"] = bridge
    return payload


@router.put("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    workspace_data: WorkspaceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Update workspace"""
    user = await get_current_user_required(request)
    workspace = await _get_workspace_or_404(db, workspace_id)
    
    # Check permissions
    if not workspace.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to workspace"
        )
    
    # Update workspace
    update_data = workspace_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(workspace, field, value)
    workspace.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(workspace)
    
    bridge = await _bridge_for_workspace(request, workspace)
    payload = serialize_workspace(workspace).model_dump()
    payload["bridge"] = bridge
    return payload


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Delete workspace"""
    user = await get_current_user_required(request)
    workspace = await _get_workspace_or_404(db, workspace_id)

    if not workspace.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to workspace"
        )

    bridge = None
    timeout = httpx.Timeout(30.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            mapping_response = await client.get(
                f"{settings.ARYX_API_URL_INTERNAL}/admin/shay/workspaces/{workspace_id}/mapping"
            )
            if mapping_response.status_code == status.HTTP_200_OK:
                bridge = mapping_response.json()
    except httpx.RequestError:
        bridge = None

    await db.delete(workspace)
    await db.commit()

    if bridge and bridge.get("aryx_workspace_id"):
        try:
            await _delete_aryx_workspace_bridge(bridge["aryx_workspace_id"])
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text or str(exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Aryx workspace deletion failed: {detail}",
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Aryx service unavailable: {exc}",
            ) from exc

    return {"message": "Workspace deleted successfully"}


@router.post("/{workspace_id}/purge")
async def purge_workspace(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Purge Aryx data for the mapped workspace while keeping the Shay workspace."""
    user = await get_current_user_required(request)
    workspace = await _get_workspace_or_404(db, workspace_id)

    if not workspace.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to workspace"
        )

    timeout = httpx.Timeout(30.0)
    mapping_url = f"{settings.ARYX_API_URL_INTERNAL}/admin/shay/workspaces/{workspace_id}/mapping"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            mapping_response = await client.get(mapping_url)
            if mapping_response.status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Workspace bridge mapping not found"
                )
            mapping_response.raise_for_status()
            mapping = mapping_response.json()
            aryx_workspace_id = mapping.get("aryx_workspace_id")
            if not aryx_workspace_id:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Mapped Aryx workspace ID is missing"
                )

            purge_response = await client.post(
                f"{settings.ARYX_API_URL_INTERNAL}/admin/workspaces/{aryx_workspace_id}/purge",
                json={},
            )
            purge_response.raise_for_status()
            purge_result = purge_response.json()
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text or str(exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Aryx purge failed: {detail}"
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Aryx service unavailable: {exc}"
        ) from exc

    return {
        "status": purge_result.get("status", "purged"),
        "shay_workspace_id": workspace_id,
        "aryx_workspace_id": aryx_workspace_id,
        "bridge": "shay-backend",
    }


@router.get("/{workspace_id}/stats", response_model=WorkspaceStats)
async def get_workspace_stats(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get workspace statistics"""
    user = await get_current_user_required(request)
    workspace = await _get_workspace_or_404(db, workspace_id)
    workspace_uuid = UUID(str(workspace.id))
    
    # Check access permissions
    if not workspace.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to workspace"
        )
    
    # Get statistics (simplified for now)
    from app.models.message import Message, Thread
    from app.models.channel import Channel
    from app.models.attachment import Attachment
    from app.models.ai_response import AIResponse

    # Subquery: channel IDs belonging to this workspace
    channel_subq = select(Channel.id).where(Channel.workspace_id == workspace_uuid).scalar_subquery()

    # Count threads via channel chain (gg_threads has no workspace_id)
    thread_count = await db.execute(select(func.count(Thread.id)).where(Thread.channel_id.in_(channel_subq)))
    total_threads = thread_count.scalar()

    # Subquery: thread IDs belonging to channels in this workspace
    thread_subq = select(Thread.id).where(Thread.channel_id.in_(channel_subq)).scalar_subquery()

    # Count messages via thread chain (gg_messages has no workspace_id)
    msg_count = await db.execute(select(func.count(Message.id)).where(Message.thread_id.in_(thread_subq)))
    total_messages = msg_count.scalar()
    
    # Count attachments
    attach_count = await db.execute(select(func.count(Attachment.id)).where(Attachment.workspace_id == workspace_uuid))
    total_attachments = attach_count.scalar()
    
    # Count AI responses
    ai_count = await db.execute(select(func.count(AIResponse.id)).where(AIResponse.workspace_id == workspace_uuid))
    ai_responses_count = ai_count.scalar()
    
    return WorkspaceStats(
        workspace_id=workspace_id,
        total_messages=total_messages,
        total_threads=total_threads,
        total_attachments=total_attachments,
        ai_responses_count=ai_responses_count,
        last_activity=None  # TODO: Implement last activity calculation
    ) 
