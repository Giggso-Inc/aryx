"""
Template-file download:

  GET    /files/{filename}/download
"""

import mimetypes
import os

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.core.config import settings

router = APIRouter()


@router.get("/files/{filename}/download")
async def download_template_file(
    filename: str,
    request: Request = None
) -> FileResponse:
    """
    Download a template file.

    Args:
        filename: Name of the template file to download

    Returns:
        File download response
    """
    # Authentication removed for testing
    # user = await get_current_user_required(request)

    try:
        template_dir = settings.TEMPLATE_DIR
        file_path = os.path.join(template_dir, filename)

        # Security check
        if not os.path.abspath(file_path).startswith(os.path.abspath(template_dir)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: File path outside template directory"
            )

        # Check if file exists
        if not os.path.exists(file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template file not found: {filename}"
            )

        # Determine media type
        media_type, _ = mimetypes.guess_type(file_path)
        if media_type is None:
            media_type = 'application/octet-stream'

        return FileResponse(
            path=file_path,
            filename=filename,
            media_type=media_type
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error downloading template file: {str(e)}"
        )
