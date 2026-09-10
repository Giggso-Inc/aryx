"""
Shared "download from vault credentials and stream" helper for
download_datasource.py's s3=1 / azure=1 / gcp=1 query-param branches.

Private module: the three branches were identical except for which
downloader function and provider name they used; extracted here so
download_datasource.py's endpoint body stays under the line cap.
"""

from typing import Callable

from fastapi import HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ._file_resolvers import get_media_type_for_download
from ._vault_helpers import get_vault_credentials_for_datasource


async def stream_from_vault_credentials(
    datasource, db: AsyncSession, view: bool, provider_label: str, downloader: Callable
) -> Response:
    """Resolve vault credentials for `datasource` and stream its file via `downloader`."""
    if not datasource.giggso_vault_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Datasource has no vault integration; cannot download from {provider_label} with vault credentials."
        )
    vault_creds = await get_vault_credentials_for_datasource(datasource, db)
    if not vault_creds:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vault record or credentials not found for this datasource."
        )
    file_content = await downloader(datasource, vault_creds, db)
    if not file_content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Could not download file from {provider_label} (check vault credentials and datasource bucket/key or file_url)."
        )
    media_type = get_media_type_for_download(datasource)
    filename = datasource.filename or "datasource_file"
    disposition = "inline" if view else "attachment"
    return Response(
        content=file_content,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'}
    )
