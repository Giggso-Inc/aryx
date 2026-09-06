"""
Single template-file content, by DB template_id:

  GET    /content/{template_id}
"""

import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.template import Template
from app.schemas.template import TemplateFileResponse

router = APIRouter()


@router.get("/content/{template_id}", response_model=TemplateFileResponse)
async def get_template_content_by_id(
    template_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> TemplateFileResponse:
    """
    Get template file content by template ID.

    Args:
        template_id: Template ID to retrieve content for
        request: FastAPI request object
        db: Database session

    Returns:
        Template file content and metadata
    """
    # Authentication removed for testing
    # user = await get_current_user_required(request, db)

    try:
        # Find template record by template_id
        result = await db.execute(
            select(Template).where(Template.template_id == template_id)
        )
        template = result.scalar_one_or_none()

        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template not found: {template_id}"
            )

        # Get file path from database record
        file_path = template.file_path
        if not file_path:
            # Fallback to template directory + template_name
            template_dir = settings.TEMPLATE_DIR
            file_path = os.path.join(template_dir, template.template_name)

        # Check if file exists
        if not os.path.exists(file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template file not found: {file_path}"
            )

        # Security check - ensure file is within template directory
        template_dir = settings.TEMPLATE_DIR
        if not os.path.abspath(file_path).startswith(os.path.abspath(template_dir)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: File path outside template directory"
            )

        # Read file content
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Get file metadata
        file_stat = os.stat(file_path)
        file_size = file_stat.st_size
        last_modified = datetime.fromtimestamp(file_stat.st_mtime)

        return TemplateFileResponse(
            file_name=template.template_name,
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
            detail=f"Error reading template content: {str(e)}"
        )
