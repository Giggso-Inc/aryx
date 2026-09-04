"""
Template-file upload (writes to disk AND creates the DB record):

  POST   /files/upload
"""

import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.template import Template
from app.schemas.template import TemplateResponse
from .helpers import generate_template_id

router = APIRouter()


@router.post("/files/upload", response_model=TemplateResponse)
async def upload_template_file(
    file: UploadFile = File(...),
    template_type: str = Form(...),
    platform: str = Form("BASE"),
    template_name: str = Form(...),
    additional_config: Optional[str] = Form(None),
    overwrite: bool = Form(False),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> TemplateResponse:
    """
    Upload a template file and create database record.

    Args:
        file: Template file to upload
        template_type: Template type (PWD, INVT, OTH)
        platform: Platform name (BASE, ZAPT, LOGA)
        template_name: Human-readable template name
        additional_config: Additional configuration as JSON string
        overwrite: Whether to overwrite existing file
        request: FastAPI request object
        db: Database session

    Returns:
        Created template record
"""
    # Authentication removed for testing
    # user = await get_current_user_required(request, db)

    try:
        # Validate template type
        allowed_types = ['PWD', 'INVT', 'OTH']
        if template_type not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid template type: {template_type}. Must be one of: {', '.join(allowed_types)}"
            )

        # Validate platform
        allowed_platforms = ['BASE', 'ZAPT', 'LOGA']
        if platform not in allowed_platforms:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid platform: {platform}. Must be one of: {', '.join(allowed_platforms)}"
            )

        template_dir = settings.TEMPLATE_DIR

        # Ensure template directory exists
        os.makedirs(template_dir, exist_ok=True)

        # Validate file extension
        _, ext = os.path.splitext(file.filename)
        if ext.lower() not in [ext.lower() for ext in settings.ALLOWED_TEMPLATE_TYPES]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type not allowed: {ext}. Allowed types: {settings.ALLOWED_TEMPLATE_TYPES}"
            )

        # Generate unique template ID based on template type and platform
        template_id = generate_template_id(template_type, platform)

        # Create file path
        file_path = os.path.join(template_dir, file.filename)

        # Check if file already exists
        if os.path.exists(file_path) and not overwrite:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"File already exists: {file.filename}. Use overwrite=true to replace."
            )

        # Read file content
        content = await file.read()

        # Write file to disk
        with open(file_path, 'wb') as f:
            f.write(content)

        # Parse additional config if provided
        config_dict = None
        if additional_config:
            import json
            try:
                config_dict = json.loads(additional_config)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid JSON in additional_config"
                )

        # Create database record
        template = Template(
            template_id=template_id,
            template_name=template_name,
            file_path=file_path,
            file_size=str(file.size) if file.size else "0",
            additional_config=config_dict
        )

        db.add(template)
        await db.commit()
        await db.refresh(template)

        return TemplateResponse.model_validate(template)

    except HTTPException:
        raise
    except Exception as e:
        # Clean up file if database operation fails
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading template file: {str(e)}"
        )
