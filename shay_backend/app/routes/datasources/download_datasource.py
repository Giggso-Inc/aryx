"""
Datasource GET /{datasource_id}/download endpoint.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.datasource import Datasource
from app.services.file_storage import get_file_storage_service

from ._download_vault_stream import stream_from_vault_credentials
from ._file_resolvers import (
    DATASOURCE_DATABASE_PROVIDERS,
    get_external_view_url_for_datasource,
    get_media_type_for_download,
    get_storage_file_path_for_deletion,
)
from ._vault_azure import download_from_azure_with_vault_credentials
from ._vault_gcp import download_from_gcp_with_vault_credentials
from ._vault_s3 import download_from_s3_with_vault_credentials

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{datasource_id}/download")
async def download_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    view: bool = Query(False, description="If true, use inline disposition for browser display; else attachment for download"),
    s3: bool = Query(False, description="If true, download from S3 using credentials from vault (datasource must have giggso_vault_id)"),
    azure: bool = Query(False, description="If true, download from Azure Blob using credentials from vault (datasource must have giggso_vault_id)"),
    gcp: bool = Query(False, description="If true, download from GCP Cloud Storage using credentials from vault (datasource must have giggso_vault_id)")
) -> Response:
    """
    Download or view datasource file content. One API for all sources:
    - Tabular files (Excel, CSV, etc.): view or download. Files in our S3/local storage are
      streamed with correct Content-Type (e.g. text/csv, spreadsheet) so browsers can display them.
    - Google Drive (and other app) datasources: view or download via redirect to the external
      view URL (webViewLink/webContentLink or file_url) so the same API works for Drive-added docs.
    - S3-stored files: files uploaded through the app (stored in our S3) are streamed and support
      both view (inline) and download (attachment); external S3 file_url is served via redirect.
    - When s3=1: credentials are taken from vault (using datasource_id -> giggso_vault_id); file is downloaded from S3 and streamed.
    - When azure=1: credentials are taken from vault (using datasource_id -> giggso_vault_id); file is downloaded from Azure Blob and streamed.
    - When gcp=1: credentials are taken from vault (using datasource_id -> giggso_vault_id); file is downloaded from GCP Cloud Storage and streamed.
    - Database datasources (Oracle, Redshift, MySQL, etc.): no file; returns 404 with clear message.
    Use view=1 for in-browser display (e.g. PDF, CSV, Excel), or omit for download.
    """
    user = await get_current_user_required(request)

    # Get datasource
    stmt = select(Datasource).where(Datasource.id == datasource_id)
    result = await db.execute(stmt)
    datasource = result.scalar_one_or_none()

    if not datasource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datasource not found"
        )

    # Check permissions
    if not datasource.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to datasource"
        )

    # Case: s3/azure/gcp=true — download using credentials from vault (datasource_id -> vault -> provider creds)
    if s3:
        return await stream_from_vault_credentials(datasource, db, view, "S3", download_from_s3_with_vault_credentials)
    if azure:
        return await stream_from_vault_credentials(datasource, db, view, "Azure", download_from_azure_with_vault_credentials)
    if gcp:
        return await stream_from_vault_credentials(datasource, db, view, "GCP", download_from_gcp_with_vault_credentials)

    # Case 1: File stored in our storage (manual upload via upload/from-upload/bulk)
    storage_file_path = get_storage_file_path_for_deletion(datasource)
    if storage_file_path:
        try:
            storage_service = get_file_storage_service()
            file_content = await storage_service.download_file(storage_file_path)
        except Exception as e:
            logger.error(f"Failed to download datasource file {datasource_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File not found or failed to download: {str(e)}"
            )
        # Content type for view: use correct media type for tabular (Excel, CSV) and others
        media_type = get_media_type_for_download(datasource)
        filename = datasource.filename or "datasource_file"
        disposition = "inline" if view else "attachment"
        return Response(
            content=file_content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'{disposition}; filename="{filename}"'
            }
        )

    # Case 2: External view/download URL (cloud storage, app integrations e.g. Google Drive, SharePoint)
    external_url = get_external_view_url_for_datasource(datasource)
    if external_url:
        if "application/json" in (request.headers.get("accept") or "").lower():
            return JSONResponse(status_code=200, content={"url": external_url})
        return RedirectResponse(url=external_url, status_code=302)

    # Case 3: Database datasources (Oracle, Redshift, MySQL, PostgreSQL, SQL Server, MongoDB, DynamoDB, Snowflake)
    # No file to view or download; only table/collection references
    if datasource.storage_type == "database" or (
        getattr(datasource, "provider", None) and datasource.provider in DATASOURCE_DATABASE_PROVIDERS
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Database datasources (e.g. Oracle, Redshift, MySQL, PostgreSQL, SQL Server, MongoDB, DynamoDB, Snowflake) do not have a viewable or downloadable file; they reference tables or collections."
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No downloadable file found for this datasource"
    )
