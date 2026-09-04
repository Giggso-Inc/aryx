"""
Update / delete a template file + its DB record, looked up by
template_id-or-template_name ("identifier"):

  PUT    /files/{identifier}
  DELETE /files/{identifier}
"""

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.template import Template
from app.schemas.template import TemplateResponse

router = APIRouter()


@router.put("/files/{identifier}", response_model=TemplateResponse)
async def update_template_file(
    identifier: str,
    file: UploadFile = File(...),
    template_name: Optional[str] = Form(None),
    additional_config: Optional[str] = Form(None),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> TemplateResponse:
    """
    Update a template file and its database record by template_id or filename.

    Args:
        identifier: Template ID or filename to update
        file: New template file content
        template_name: Updated template name
        additional_config: Updated additional configuration
        request: FastAPI request object
        db: Database session

    Returns:
        Updated template record
    """
    # Authentication removed for testing
    # user = await get_current_user_required(request, db)

    try:
        # Find database record first (by template_id or template_name)
        result = await db.execute(
            select(Template).where(
                or_(
                    Template.template_id == identifier,
                    Template.template_name == identifier
                )
            )
        )
        template = result.scalar_one_or_none()

        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template record not found: {identifier}"
            )

        # Use the file_path from database record
        template_dir = settings.TEMPLATE_DIR
        file_path = template.file_path or os.path.join(template_dir, template.template_name)

        # Check if file exists
        if not os.path.exists(file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template file not found: {file_path}"
            )

        # Validate file extension
        _, ext = os.path.splitext(file.filename)
        if ext.lower() not in [ext.lower() for ext in settings.ALLOWED_TEMPLATE_TYPES]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type not allowed: {ext}. Allowed types: {settings.ALLOWED_TEMPLATE_TYPES}"
            )

        # Read new file content
        content = await file.read()

        # Update file on disk
        with open(file_path, 'wb') as f:
            f.write(content)

        # Parse additional config if provided
        if additional_config:
            import json
            try:
                config_dict = json.loads(additional_config)
                template.additional_config = config_dict
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid JSON in additional_config"
                )

        # Update database record
        if template_name:
            template.template_name = template_name
        template.updated_datetime = datetime.utcnow()

        await db.commit()
        await db.refresh(template)

        return TemplateResponse.model_validate(template)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating template file: {str(e)}"
        )


@router.delete("/files/{identifier}")
async def delete_template_file(
    identifier: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    """
    Delete a template file and its database record by template_id or filename.

    Args:
        identifier: Template ID or filename to delete
        request: FastAPI request object
        db: Database session

    Returns:
        Success message
    """
    # Authentication removed for testing
    # user = await get_current_user_required(request, db)

    try:
        # Find database record first (by template_id or template_name)
        result = await db.execute(
            select(Template).where(
                or_(
                    Template.template_id == identifier,
                    Template.template_name == identifier
                )
            )
        )
        template = result.scalar_one_or_none()

        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template record not found: {identifier}"
            )

        # Use the file_path from database record
        template_dir = settings.TEMPLATE_DIR
        file_path = template.file_path or os.path.join(template_dir, template.template_name)

        # Check if file exists
        if not os.path.exists(file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template file not found: {file_path}"
            )

        # Delete file from disk
        os.remove(file_path)

        # Delete database record
        await db.delete(template)
        await db.commit()

        return JSONResponse(
            content={"message": f"Template file '{identifier}' and its record deleted successfully"},
            status_code=status.HTTP_200_OK
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting template file: {str(e)}"
        )
