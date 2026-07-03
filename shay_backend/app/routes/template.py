"""
Template routes for managing template files.

This module provides API endpoints for:
- Fetching template files from the template directory
- Listing template files
- Template file operations (read, download)

Author: AI Assistant
Date: 2025-01-27
Version: 1.0.0
"""

import os
import mimetypes
import uuid
from datetime import datetime
from typing import List, Optional

# FastAPI imports
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse

# SQLAlchemy imports
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_

# Application imports
from app.core.database import get_db
from app.core.config import settings
from app.models.template import Template
from app.schemas.template import (
    TemplateFileResponse,
    TemplateFileListResponse,
    TemplateCreate,
    TemplateUpdate,
    TemplateResponse,
    TemplateListResponse,
    TemplateUploadRequest
)
# Authentication removed for testing
# from app.middleware.auth_middleware import get_current_user_required

# Create router
router = APIRouter(tags=["Templates"])


def generate_template_id(template_type: str, platform: str = 'BASE') -> str:
    """
    Generate a unique template ID based on template type and platform.
    
    Args:
        template_type: Template type (PWD, INVT, OTH)
        platform: Platform name (BASE, ZAPT, LOGA)
    
    Returns:
        str: Generated template ID with appropriate prefix
    """
    # Map template types to prefixes
    type_prefixes = {
        'PWD': 'TMPLT_PWD_',
        'INVT': 'TMPLT_INVT_',
        'OTH': 'TMPLT_OTH_'
    }
    
    # Map platforms to suffixes
    platform_suffixes = {
        'BASE': 'BASE_',
        'ZAPT': 'ZAPT_',
        'LOGA': 'LOGA_'
    }
    
    if template_type not in type_prefixes:
        raise ValueError(f"Invalid template type: {template_type}. Must be one of: PWD, INVT, OTH")
    
    if platform not in platform_suffixes:
        raise ValueError(f"Invalid platform: {platform}. Must be one of: BASE, ZAPT, LOGA")
    
    prefix = type_prefixes[template_type]
    platform_suffix = platform_suffixes[platform]
    
    # Generate unique suffix using UUID
    return f"{prefix}{platform_suffix}{uuid.uuid4().hex[:8].upper()}"


def get_template_type_from_id(template_id: str) -> str:
    """
    Extract template type from template ID.
    
    Args:
        template_id: Template ID (e.g., TMPLT_PWD_BASE_12345678, TMPLT_INVT_ZAPT_12345678)
    
    Returns:
        str: Template type (PWD, INVT, OTH)
    """
    if template_id.startswith('TMPLT_PWD_'):
        return 'PWD'
    elif template_id.startswith('TMPLT_INVT_'):
        return 'INVT'
    elif template_id.startswith('TMPLT_OTH_'):
        return 'OTH'
    else:
        raise ValueError(f"Unknown template ID format: {template_id}")


def get_platform_from_template_id(template_id: str) -> str:
    """
    Extract platform from template ID.
    
    Args:
        template_id: Template ID (e.g., TMPLT_PWD_BASE_12345678, TMPLT_INVT_ZAPT_12345678)
    
    Returns:
        str: Platform name (BASE, ZAPT, LOGA)
    """
    if '_BASE_' in template_id:
        return 'BASE'
    elif '_ZAPT_' in template_id:
        return 'ZAPT'
    elif '_LOGA_' in template_id:
        return 'LOGA'
    else:
        # Default to BASE if no platform is specified in old format
        return 'BASE'


def validate_template_id_for_type(template_id: str, expected_type: str) -> bool:
    """
    Validate that template ID matches the expected type.
    
    Args:
        template_id: Template ID to validate
        expected_type: Expected template type (PWD, INVT, OTH)
    
    Returns:
        bool: True if template ID matches expected type
    """
    try:
        actual_type = get_template_type_from_id(template_id)
        return actual_type == expected_type
    except ValueError:
        return False


def validate_template_id_for_platform(template_id: str, expected_platform: str) -> bool:
    """
    Validate that template ID matches the expected platform.
    
    Args:
        template_id: Template ID to validate
        expected_platform: Expected platform (BASE, ZAPT, LOGA)
    
    Returns:
        bool: True if template ID matches expected platform
    """
    try:
        actual_platform = get_platform_from_template_id(template_id)
        return actual_platform == expected_platform
    except ValueError:
        return False


def is_valid_template_id_format(template_id: str) -> bool:
    """
    Check if template ID has valid format with platform.
    
    Args:
        template_id: Template ID to validate
    
    Returns:
        bool: True if template ID has valid format
    """
    valid_patterns = [
        'TMPLT_PWD_BASE_',
        'TMPLT_PWD_ZAPT_',
        'TMPLT_PWD_LOGA_',
        'TMPLT_INVT_BASE_',
        'TMPLT_INVT_ZAPT_',
        'TMPLT_INVT_LOGA_',
        'TMPLT_OTH_BASE_',
        'TMPLT_OTH_ZAPT_',
        'TMPLT_OTH_LOGA_'
    ]
    
    return any(template_id.startswith(pattern) for pattern in valid_patterns)


@router.get("/files", response_model=TemplateFileListResponse)
async def list_template_files(
    request: Request = None
):
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


@router.get("/files/{filename}", response_model=TemplateFileResponse)
async def get_template_file(
    filename: str,
    request: Request = None
):
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


@router.get("/content/{template_id}", response_model=TemplateFileResponse)
async def get_template_content_by_id(
    template_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
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


@router.get("/files/{filename}/download")
async def download_template_file(
    filename: str,
    request: Request = None
):
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
):
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


@router.put("/files/{identifier}", response_model=TemplateResponse)
async def update_template_file(
    identifier: str,
    file: UploadFile = File(...),
    template_name: Optional[str] = Form(None),
    additional_config: Optional[str] = Form(None),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
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
):
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


# Database template management endpoints (for listing database records)

@router.get("/", response_model=TemplateListResponse)
async def list_templates(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    is_active: Optional[str] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search in template name"),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """
    List template database records with pagination and filtering.
    
    Args:
        page: Page number
        size: Number of items per page
        is_active: Filter by active status
        search: Search query
        request: FastAPI request object
        db: Database session
        
    Returns:
        Paginated list of template records
    """
    # Authentication removed for testing
    # user = await get_current_user_required(request, db)
    
    try:
        # Build query
        query = select(Template)
        
        # Apply filters
        if is_active:
            query = query.where(Template.is_active == is_active)
        
        if search:
            query = query.where(
                or_(
                    Template.template_name.ilike(f"%{search}%"),
                    Template.template_id.ilike(f"%{search}%")
                )
            )
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar()
        
        # Apply pagination
        offset = (page - 1) * size
        query = query.offset(offset).limit(size).order_by(Template.created_datetime.desc())
        
        # Execute query
        result = await db.execute(query)
        templates = result.scalars().all()
        
        # Calculate pages
        pages = (total + size - 1) // size
        
        return TemplateListResponse(
            templates=[TemplateResponse.model_validate(t) for t in templates],
            total=total,
            page=page,
            size=size,
            pages=pages
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing templates: {str(e)}"
        )


@router.get("/{identifier}", response_model=TemplateResponse)
async def get_template(
    identifier: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific template database record by template_id or template_name.
    
    Args:
        identifier: Template ID or template name to retrieve
        request: FastAPI request object
        db: Database session
        
    Returns:
        Template record
    """
    # Authentication removed for testing
    # user = await get_current_user_required(request, db)
    
    try:
        # Try to find by template_id first, then by template_name
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
                detail=f"Template not found: {identifier}"
            )
        
        return TemplateResponse.model_validate(template)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving template: {str(e)}"
        )