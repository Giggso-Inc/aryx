"""
JSON-payload create endpoints (no file upload involved):

  POST   /bulk   bulk-create from a list of JSON payloads
  POST   /       create a single datasource
"""

import uuid
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import (
    GGDatasourceBulkCreate,
    GGDatasourceBulkResponse,
    GGDatasourceCreate,
    GGDatasourceResponse,
)
from .response import _to_response

router = APIRouter()


@router.post("/bulk", response_model=GGDatasourceBulkResponse, status_code=201)
async def bulk_create_datasources(
    payload: GGDatasourceBulkCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGDatasourceBulkResponse:
    """Bulk-create GGDatasource rows from JSON payloads."""
    user = await get_current_user_required(request, db)

    created: List[GGDatasourceResponse] = []
    failed:  List[Dict[str, Any]] = []

    for item in payload.datasources:
        scope_fk = {item.level + "_id": UUID(getattr(item, item.level + "_id"))}
        ds_obj = GGDatasource(
            id=uuid.uuid4(),
            level=item.level,
            **scope_fk,
            added_by=user.id,
            name=item.name,
            filename=item.filename,
            storage_type=item.storage_type,
            provider=item.provider,
            app_type=item.app_type,
            config=item.config or {},
            datasource_metadata=item.datasource_metadata or {},
            vault_unique_id=UUID(item.vault_unique_id) if item.vault_unique_id else None,
            file_size=item.file_size,
            file_type=item.file_type,
            file_url=item.file_url,
            log_type=item.log_type,
            is_embedding_required=item.is_embedding_required,
        )
        db.add(ds_obj)
        try:
            await db.commit()
            await db.refresh(ds_obj)
            created.append(_to_response(ds_obj))
        except Exception as exc:
            await db.rollback()
            failed.append({"name": item.name, "error": str(exc)})

    return GGDatasourceBulkResponse(
        created_datasources=created,
        failed_datasources=failed,
        total_created=len(created),
        total_failed=len(failed),
    )


@router.post("/", response_model=GGDatasourceResponse, status_code=status.HTTP_201_CREATED)
async def create_datasource(
    payload: GGDatasourceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGDatasourceResponse:
    """
    Add a datasource at workspace, channel, thread, or message scope.
    Exactly one scope FK must match the declared level.
    """
    current_user = await get_current_user_required(request, db)

    ds = GGDatasource(
        id=uuid.uuid4(),
        level=payload.level,
        workspace_id=UUID(payload.workspace_id) if payload.workspace_id else None,
        channel_id=UUID(payload.channel_id)     if payload.channel_id   else None,
        thread_id=UUID(payload.thread_id)       if payload.thread_id    else None,
        message_id=UUID(payload.message_id)     if payload.message_id   else None,
        added_by=current_user.id,
        name=payload.name,
        filename=payload.filename,
        storage_type=payload.storage_type,
        provider=payload.provider,
        app_type=payload.app_type,
        config=payload.config or {},
        datasource_metadata=payload.datasource_metadata or {},
        vault_unique_id=UUID(payload.vault_unique_id) if payload.vault_unique_id else None,
        file_size=payload.file_size,
        file_type=payload.file_type,
        file_url=payload.file_url,
        log_type=payload.log_type,
        is_embedding_required=payload.is_embedding_required,
    )
    db.add(ds)
    try:
        await db.commit()
        await db.refresh(ds)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    return _to_response(ds)
