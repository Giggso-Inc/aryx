"""POST /  create_connection"""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app import App
from app.models.gg_app_connections import GGAppConnection
from app.schemas.gg_app_connections import GGAppConnectionCreate, GGAppConnectionResponse

from ._shared import assert_member_access, assert_scope_exists, build_response

router = APIRouter()


@router.post("/", response_model=GGAppConnectionResponse, status_code=201)
async def create_connection(
    data: GGAppConnectionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGAppConnectionResponse:
    """Create a new GGAppConnection at workspace, channel, or thread scope."""
    user = await get_current_user_required(request, db)

    # Verify app exists and is active
    app = (await db.execute(
        select(App).where(and_(App.id == data.app_id, App.is_active == True))
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="App not found or not active")

    # Verify scope exists and get company_id
    company_id = await assert_scope_exists(
        db, data.level, data.workspace_id, data.channel_id, data.thread_id
    )

    # Verify user has access to the target scope
    await assert_member_access(
        db,
        user_id=user.id,
        level=data.level,
        workspace_id=data.workspace_id,
        channel_id=data.channel_id,
        thread_id=data.thread_id,
        user_company_id=str(user.company_id),
        company_id_from_scope=company_id,
    )

    # Check for existing active connection at this scope
    duplicate_filter = {
        "workspace": and_(GGAppConnection.workspace_id == data.workspace_id, GGAppConnection.level == "workspace"),
        "channel":   and_(GGAppConnection.channel_id   == data.channel_id,   GGAppConnection.level == "channel"),
        "thread":    and_(GGAppConnection.thread_id    == data.thread_id,    GGAppConnection.level == "thread"),
    }
    existing = (await db.execute(
        select(GGAppConnection).where(
            and_(
                GGAppConnection.app_id == data.app_id,
                GGAppConnection.is_active == True,
                duplicate_filter[data.level],
            )
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"App is already connected at this {data.level} scope",
        )

    # Inject Jira credentials from settings
    connection_settings = data.connection_settings
    if connection_settings and isinstance(connection_settings, dict):
        if connection_settings.get("provider") == "jira":
            import copy
            connection_settings = copy.deepcopy(connection_settings)
            connection_settings["client_id"] = settings.JIRA_CLIENT_ID
            connection_settings["client_secret"] = settings.JIRA_CLIENT_SECRET

    conn = GGAppConnection(
        id=uuid4(),
        app_id=data.app_id,
        level=data.level,
        workspace_id=data.workspace_id,
        channel_id=data.channel_id,
        thread_id=data.thread_id,
        connected_by=user.id,
        connection_name=data.connection_name,
        connection_status=data.connection_status,
        connection_settings=connection_settings,
        webhook_url=data.webhook_url,
        callback_url=data.callback_url,
        is_active=data.is_active,
        auto_sync=data.auto_sync,
        sync_interval=data.sync_interval,
        provider=data.provider,
        auth_type=data.auth_type,
    )
    db.add(conn)
    try:
        await db.commit()
        await db.refresh(conn)
    except Exception as exc:
        await db.rollback()
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="App already connected at this scope.")
        raise

    return build_response(conn, user)
