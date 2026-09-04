"""
Single-resource CRUD by ID plus file download/view:

  GET    /{datasource_id}
  GET    /{datasource_id}/download
  PUT    /{datasource_id}
  DELETE /{datasource_id}
  PUT    /{datasource_id}/status   (ML callback)

Must be registered after the literal-path submodules in this package
(upload, create_from_upload, create, query, embedding, processing) — its
GET/PUT/DELETE /{datasource_id} routes would otherwise swallow their
single-segment literal paths (e.g. GET /stats, GET /count).
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import GGDatasourceResponse, GGDatasourceUpdate, ProcessingStatusUpdate
from app.services.file_storage import get_file_storage_service
from .response import (
    DATASOURCE_DATABASE_PROVIDERS,
    _get_external_view_url,
    _get_media_type,
    _get_storage_file_path,
    _to_response,
)

router = APIRouter()


@router.get("/{datasource_id}", response_model=GGDatasourceResponse)
async def get_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGDatasourceResponse:
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")
    return _to_response(ds)


@router.get("/{datasource_id}/download")
async def download_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    view: bool = Query(False, description="If true, inline disposition for browser display; else attachment"),
) -> Response:
    """Download or view a datasource file. Streams local/S3 files; redirects to external URLs."""
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    # Case 1: file stored in our storage
    storage_path = _get_storage_file_path(ds)
    if storage_path:
        try:
            storage_service = get_file_storage_service()
            file_content = await storage_service.download_file(storage_path)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"File not found or failed to download: {exc}")
        media_type  = _get_media_type(ds)
        filename    = ds.filename or "datasource_file"
        disposition = "inline" if view else "attachment"
        return Response(
            content=file_content,
            media_type=media_type,
            headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
        )

    # Case 2: external URL
    external_url = _get_external_view_url(ds)
    if external_url:
        if "application/json" in (request.headers.get("accept") or "").lower():
            return JSONResponse(status_code=200, content={"url": external_url})
        return RedirectResponse(url=external_url, status_code=302)

    # Case 3: database datasource — no file
    if ds.storage_type == "database" or (ds.provider and ds.provider in DATASOURCE_DATABASE_PROVIDERS):
        raise HTTPException(
            status_code=404,
            detail="Database datasources do not have a viewable or downloadable file.",
        )

    raise HTTPException(status_code=404, detail="No downloadable file found for this datasource")


@router.put("/{datasource_id}", response_model=GGDatasourceResponse)
async def update_datasource(
    datasource_id: str,
    payload: GGDatasourceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGDatasourceResponse:
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        if field == "vault_unique_id" and value:
            value = UUID(value)
        setattr(ds, field, value)

    ds.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(ds)
    return _to_response(ds)


@router.delete("/{datasource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    ds.is_active  = False
    ds.updated_at = datetime.utcnow()
    await db.commit()


@router.put("/{datasource_id}/status", response_model=GGDatasourceResponse)
async def update_processing_status(
    datasource_id: str,
    payload: ProcessingStatusUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GGDatasourceResponse:
    """Called by ML agents to report processing / embedding progress."""
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(ds, field, value)

    if payload.processing_status == "completed":
        ds.last_processed_at = datetime.utcnow()

    ds.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(ds)
    return _to_response(ds)
