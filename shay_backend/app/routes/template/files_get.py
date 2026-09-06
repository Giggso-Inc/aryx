"""
Single template-file content, by filename:

  GET    /files/{filename}
"""

import os
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import settings
from app.schemas.template import TemplateFileResponse

router = APIRouter()


@router.get("/files/{filename}", response_model=TemplateFileResponse)
async def get_template_file(
    filename: str,
    request: Request = None
) -> TemplateFileResponse:
    """
    Get a specific template file content.

    Args:
        filename: Name of the template file to retrieve

    Returns:
        Template file content and metadata
    """
    # Authentication removed for testing
    # user = await get_current_user_required(request)

    try:
        template_dir = settings.TEMPLATE_DIR
        file_path = os.path.join(template_dir, filename)

        # Security check - ensure file is within template directory
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

        # Check file extension
        _, ext = os.path.splitext(filename)
        if ext.lower() not in [ext.lower() for ext in settings.ALLOWED_TEMPLATE_TYPES]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type not allowed: {ext}"
            )

        # Read file content
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            # Try with different encoding
            with open(file_path, 'r', encoding='latin-1') as f:
                content = f.read()

        # Get file stats
        stat = os.stat(file_path)
        file_size = stat.st_size
        last_modified = datetime.fromtimestamp(stat.st_mtime)

        return TemplateFileResponse(
            file_name=filename,
            file_path=file_path,
            content=content,
            file_size=file_size,
            last_modified=last_modified
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reading template file: {str(e)}"
        )
