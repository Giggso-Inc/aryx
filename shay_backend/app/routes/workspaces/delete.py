"""
DELETE /{workspace_id} — delete_workspace.

Split from the original delete_purge.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.member import GGMember
from app.utils.permissions import require_active_workspace_role

from .helpers import _aryx_headers, _delete_aryx_workspace_bridge, _get_workspace_or_404

router = APIRouter()


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete workspace"""
    user = await get_current_user_required(request)
    workspace = await _get_workspace_or_404(db, workspace_id)

    await require_active_workspace_role(db, user.id, UUID(str(workspace.id)), allowed_roles={"admin"})

    bridge = None
    timeout = httpx.Timeout(30.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            mapping_response = await client.get(
                f"{settings.ARYX_API_URL_INTERNAL}/admin/shay/workspaces/{workspace_id}/mapping",
                headers=_aryx_headers(),
            )
            if mapping_response.status_code == status.HTTP_200_OK:
                bridge = mapping_response.json()
            elif mapping_response.status_code != status.HTTP_404_NOT_FOUND:
                mapping_response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text or str(exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Aryx workspace lookup failed: {detail}",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Aryx service unavailable: {exc}",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

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

    # Delete members explicitly before deleting the workspace.
    # db.delete(workspace) would cause SQLAlchemy to SET workspace_id=NULL
    # on related GGMember rows, which violates the exclusive-arc CHECK constraint
    # (level='workspace' requires workspace_id IS NOT NULL).
    await db.execute(delete(GGMember).where(GGMember.workspace_id == workspace.id))
    await db.delete(workspace)
    await db.commit()

    return {"message": "Workspace deleted successfully"}
