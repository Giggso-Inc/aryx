"""
Template-directory listing:

  GET    /files
"""

import os
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import settings
from app.schemas.template import TemplateFileListResponse, TemplateFileResponse

router = APIRouter()


@router.get("/files", response_model=TemplateFileListResponse)
async def list_template_files(
    request: Request = None
) -> TemplateFileListResponse:
    """
    List all template files in the template directory.

    Returns:
        List of template files with metadata
    """
    # Authentication removed for testing
    # user = await get_current_user_required(request)

    try:
        template_dir = settings.TEMPLATE_DIR

        # Check if template directory exists
        if not os.path.exists(template_dir):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template directory not found: {template_dir}"
            )

        files = []
        allowed_extensions = [ext.lower() for ext in settings.ALLOWED_TEMPLATE_TYPES]

        # Scan directory for template files
        for filename in os.listdir(template_dir):
            file_path = os.path.join(template_dir, filename)

            # Skip directories and hidden files
            if os.path.isdir(file_path) or filename.startswith('.'):
                continue

            # Check file extension
            _, ext = os.path.splitext(filename)
            if ext.lower() not in allowed_extensions:
                continue

            try:
                # Get file stats
                stat = os.stat(file_path)
                file_size = stat.st_size
                last_modified = datetime.fromtimestamp(stat.st_mtime)

                files.append(TemplateFileResponse(
                    file_name=filename,
                    file_path=file_path,
                    content="",  # Content not loaded for list view
                    file_size=file_size,
                    last_modified=last_modified
                ))

            except OSError as e:
                # Skip files that can't be accessed
                continue

        # Sort files by name
        files.sort(key=lambda x: x.file_name)

        return TemplateFileListResponse(
            files=files,
            directory=template_dir,
            total_files=len(files)
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing template files: {str(e)}"
        )
