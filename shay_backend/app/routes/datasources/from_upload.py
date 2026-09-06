"""
Datasource POST /from-upload endpoint (upload a file and create a datasource
row for it in one call).

Guard clauses (channel lookup/access, duplicate-name, filename, company
lookup) are further extracted to _from_upload_validate.py (Raven
style-compliance, wave B4). Validation, upload, metadata-build, and the
finalize-with-vault call are delegated to _upload_shared.py and
_from_upload_persist.py; what remains here is the single linear happy-path
sequence gluing them together.
"""

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.schemas.datasource import DatasourceResponse
from app.services.file_storage import generate_structured_path, get_file_storage_service
from app.utils.file_validation import validate_file_content

from ._from_upload_persist import finalize_from_upload_datasource
from ._from_upload_validate import validate_from_upload_request
from ._upload_shared import build_config_from_upload_result, build_enhanced_metadata_for_upload

router = APIRouter()


@router.post("/from-upload", response_model=DatasourceResponse)
async def create_datasource_from_upload(
    name: Optional[str] = Form(None),
    channel_id: str = Form(...),
    log_type: Optional[str] = Form(None),
    datasource_metadata: Optional[str] = Form(None),  # JSON string
    file: UploadFile = File(...),
    isValidationRequired: bool = Form(True),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> DatasourceResponse:
    """Create a datasource from uploaded file"""
    user = await get_current_user_required(request)

    # Parse datasource_metadata if provided
    if datasource_metadata:
        try:
            import json
            json.loads(datasource_metadata)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON in datasource_metadata"
            )

    channel, company = await validate_from_upload_request(db, user, channel_id, name, file)

    storage_service = get_file_storage_service()

    try:
        file_content = await file.read()

        if isValidationRequired and not validate_file_content(file_content, file.filename):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File validation failed - no valid section headers found"
            )

        file_extension = os.path.splitext(file.filename)[1]
        base_filename = os.path.splitext(file.filename)[0]
        current_date = datetime.now().strftime("%Y-%m-%d")

        structured_path = generate_structured_path(
            company_name=company.name,
            company_id=str(company.id),
            file_type="datasource",
            original_filename=file.filename,
            base_filename=base_filename,
            file_extension=file_extension,
            current_date=current_date
        )

        upload_result = await storage_service.upload_file(
            file_content=file_content,
            destination_path=structured_path,
            original_filename=file.filename
        )

        # Auto-generate name from filename if not provided
        datasource_name = name
        if not datasource_name:
            name_base = os.path.splitext(file.filename)[0]
            datasource_name = name_base.replace('_', ' ').replace('-', ' ').title()

        storage_type, provider, config = build_config_from_upload_result(upload_result, file.filename)

        enhanced_metadata = await build_enhanced_metadata_for_upload(
            filename=file.filename,
            storage_type=storage_type,
            provider=provider,
            channel_id=channel_id,
            workspace_id=str(channel.workspace_id),
            user_id=str(user.id),
            file_size=len(file_content),
            file_type=file.content_type or "application/octet-stream",
            log_type=log_type,
            config=config,
            file_url=upload_result["file_url"],
            db=db,
        )

        return await finalize_from_upload_datasource(
            enhanced_metadata=enhanced_metadata,
            datasource_name=datasource_name,
            file=file,
            file_size=len(file_content),
            storage_type=storage_type,
            provider=provider,
            log_type=log_type,
            config=config,
            upload_result=upload_result,
            channel_id=channel_id,
            user=user,
            channel=channel,
            db=db,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create datasource from upload: {str(e)}"
        )
