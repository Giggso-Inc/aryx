"""
GET /{thread_id}/app-connections (list_thread_app_connections) — mounted at
/api/v1/threads.

Split from app/routes/threads/app_connections.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.utils.gg_app_connections import get_all_connections_for_scope

router = APIRouter()


@router.get("/{thread_id}/app-connections")
async def list_thread_app_connections(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    List all effective app connections visible at this thread.
    Returns thread-level connections first, then falls back to inherited
    channel and workspace connections.
    """
    await get_current_user_required(request, db)

    try:
        t_uuid = UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thread_id format")

    accounts = await get_all_connections_for_scope(db, thread_id=t_uuid)
    return {"app_connections": [a.to_dict() for a in accounts], "total": len(accounts)}
