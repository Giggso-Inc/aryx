"""
Background-processing trigger and bulk connect/disconnect:

  POST   /process           trigger background processing
  POST   /bulk-connection    bulk connect / disconnect
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, AsyncSessionLocal
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import (
    DatasourceBulkConnectionResponse,
    DatasourceConnectionRequest,
    DatasourceConnectionResponse,
    DatasourceProcessingRequest,
    DatasourceProcessingResponse,
)

router = APIRouter()


@router.post("/process", response_model=DatasourceProcessingResponse)
async def process_datasource(
    payload: DatasourceProcessingRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DatasourceProcessingResponse:
    """Trigger background processing for a datasource."""
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(payload.datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    background_tasks.add_task(_process_datasource_background, payload.datasource_id)

    return DatasourceProcessingResponse(
        datasource_id=payload.datasource_id,
        status="processing_started",
        message="Datasource processing started in background",
    )


async def _process_datasource_background(datasource_id: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
            if not ds:
                return
            ds.processing_status = "processing"
            ds.updated_at = datetime.utcnow()
            await db.commit()

            await asyncio.sleep(5)

            async with AsyncSessionLocal() as db2:
                ds2 = (await db2.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
                if ds2:
                    ds2.processing_status = "completed"
                    ds2.is_processed      = True
                    ds2.last_processed_at = datetime.utcnow()
                    ds2.updated_at        = datetime.utcnow()
                    await db2.commit()
        except Exception as exc:
            async with AsyncSessionLocal() as db3:
                ds3 = (await db3.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
                if ds3:
                    ds3.processing_status = "failed"
                    ds3.error_message     = str(exc)
                    ds3.updated_at        = datetime.utcnow()
                    await db3.commit()


@router.post("/bulk-connection", response_model=DatasourceBulkConnectionResponse)
async def bulk_manage_connections(
    payload: DatasourceConnectionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DatasourceBulkConnectionResponse:
    """Bulk connect or disconnect multiple GGDatasources."""
    await get_current_user_required(request, db)
    action = payload.action.lower()

    ids = [UUID(did) for did in payload.datasource_ids]
    datasources = (await db.execute(select(GGDatasource).where(GGDatasource.id.in_(ids)))).scalars().all()

    found_ids = {str(ds.id) for ds in datasources}
    missing   = set(payload.datasource_ids) - found_ids
    if missing:
        raise HTTPException(status_code=404, detail=f"Datasources not found: {', '.join(missing)}")

    successful: List[DatasourceConnectionResponse] = []
    failed:     List[Dict[str, Any]] = []

    for ds in datasources:
        if action == "connect":
            if ds.is_connected:
                failed.append({"datasource_id": str(ds.id), "error": "Already connected"})
                continue
            ds.is_connected = True
            msg = "Datasource connected successfully"
        else:
            if not ds.is_connected:
                failed.append({"datasource_id": str(ds.id), "error": "Already disconnected"})
                continue
            ds.is_connected = False
            msg = "Datasource disconnected successfully"

        ds.updated_at = datetime.utcnow()
        successful.append(DatasourceConnectionResponse(
            datasource_id=str(ds.id),
            is_connected=ds.is_connected,
            message=msg,
            updated_at=ds.updated_at,
        ))

    if successful:
        await db.commit()

    return DatasourceBulkConnectionResponse(
        successful_operations=successful,
        failed_operations=failed,
        total_successful=len(successful),
        total_failed=len(failed),
        action_performed=action,
        message=f"Successfully {action}ed {len(successful)} datasource(s)" + (f", {len(failed)} failed" if failed else ""),
    )
