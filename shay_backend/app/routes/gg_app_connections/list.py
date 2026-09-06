"""GET /  list_connections"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.gg_app_connections import GGAppConnection
from app.models.member import GGMember
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.gg_app_connections import GGAppConnectionList

from ._shared import build_response

router = APIRouter()


@router.get("/", response_model=GGAppConnectionList)
async def list_connections(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    app_id: Optional[str] = None,
    level: Optional[str] = None,
    workspace_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    connection_status: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> GGAppConnectionList:
    """
    List GGAppConnections visible to the current user.

    Results are scoped to the user's company by joining through Workspace
    (for workspace-level) or Channel (for channel/thread-level connections).
    """
    user = await get_current_user_required(request, db)

    # Subquery: workspace_ids belonging to user's company
    company_workspace_ids = select(Workspace.id).where(
        Workspace.company_id == user.company_id
    )
    # Subquery: channel_ids belonging to user's company
    company_channel_ids = select(Channel.id).where(
        Channel.company_id == user.company_id
    )

    # Company filter: connection belongs to user's company via workspace OR channel
    company_filter = or_(
        and_(
            GGAppConnection.level == "workspace",
            GGAppConnection.workspace_id.in_(company_workspace_ids),
        ),
        and_(
            GGAppConnection.level == "channel",
            GGAppConnection.channel_id.in_(company_channel_ids),
        ),
        and_(
            # Thread connections: scoped via parent channel membership
            GGAppConnection.level == "thread",
            GGAppConnection.connected_by.in_(
                select(GGMember.user_id).where(
                    and_(
                        GGMember.level == "channel",
                        GGMember.channel_id.in_(company_channel_ids),
                        GGMember.is_active == True,
                    )
                )
            ),
        ),
    )

    filters = [company_filter]

    if app_id:
        filters.append(GGAppConnection.app_id == app_id)
    if level:
        filters.append(GGAppConnection.level == level)
    if workspace_id:
        filters.append(GGAppConnection.workspace_id == workspace_id)
    if channel_id:
        filters.append(GGAppConnection.channel_id == channel_id)
    if thread_id:
        filters.append(GGAppConnection.thread_id == thread_id)
    if connection_status:
        filters.append(GGAppConnection.connection_status == connection_status)
    if is_active is not None:
        filters.append(GGAppConnection.is_active == is_active)

    base_query = select(GGAppConnection).where(and_(*filters))

    total = (await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )).scalar()

    rows = (await db.execute(
        base_query.order_by(GGAppConnection.created_at.desc())
                  .offset((page - 1) * size)
                  .limit(size)
    )).scalars().all()

    # Batch-load connector users
    connector_ids = [r.connected_by for r in rows]
    users_by_id = {
        u.id: u for u in (
            await db.execute(select(User).where(User.id.in_(connector_ids)))
        ).scalars().all()
    } if connector_ids else {}

    return GGAppConnectionList(
        connections=[build_response(r, users_by_id.get(r.connected_by)) for r in rows],
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size,
    )
