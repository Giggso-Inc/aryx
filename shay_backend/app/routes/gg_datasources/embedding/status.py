"""GET /embedding-status/{scope_level}/{scope_id}."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import GGEmbeddingStatusResponse

router = APIRouter()


@router.get("/embedding-status/{scope_level}/{scope_id}", response_model=GGEmbeddingStatusResponse)
async def get_embedding_status(
    scope_level: str,
    scope_id:    str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGEmbeddingStatusResponse:
    """Get embedding status for all datasources at a given scope level."""
    await get_current_user_required(request, db)

    if scope_level not in ("workspace", "channel", "thread", "message"):
        raise HTTPException(status_code=400, detail="scope_level must be workspace | channel | thread | message")

    fk_col = {
        "workspace": GGDatasource.workspace_id,
        "channel":   GGDatasource.channel_id,
        "thread":    GGDatasource.thread_id,
        "message":   GGDatasource.message_id,
    }[scope_level]

    stmt = select(GGDatasource).where(
        and_(fk_col == UUID(scope_id), GGDatasource.level == scope_level)
    )
    datasources = (await db.execute(stmt)).scalars().all()

    total = len(datasources)
    emb_required = in_progress = completed = failed = not_required = 0
    ds_list = []

    for ds in datasources:
        if ds.is_embedding_required:
            emb_required += 1
        if ds.embedding_status == 0:
            not_required += 1
        elif ds.embedding_status == 1:
            in_progress += 1
        elif ds.embedding_status == 2:
            completed += 1
        elif ds.embedding_status == 3:
            failed += 1
        ds_list.append({
            "id":                    str(ds.id),
            "name":                  ds.name,
            "filename":              ds.filename,
            "is_embedding_required": ds.is_embedding_required,
            "embedding_status":      ds.embedding_status,
            "error_message":         ds.error_message,
            "created_at":            ds.created_at,
            "updated_at":            ds.updated_at,
        })

    return GGEmbeddingStatusResponse(
        scope_level=scope_level,
        scope_id=scope_id,
        total_datasources=total,
        embedding_required=emb_required,
        in_progress=in_progress,
        completed=completed,
        failed=failed,
        not_required=not_required,
        datasources=ds_list,
    )
