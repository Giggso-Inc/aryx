"""GET /{datasource_id}/download — download or view a datasource file."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.gg_datasource import GGDatasource
from app.services.file_storage import get_file_storage_service
from ..response import (
    DATASOURCE_DATABASE_PROVIDERS,
    _get_external_view_url,
    _get_media_type,
    _get_storage_file_path,
)

router = APIRouter()


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
