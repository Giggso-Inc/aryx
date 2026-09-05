"""
Per-item processing for from_upload_bulk.py (POST /from-upload/bulk).

Private module: extracted verbatim (per-datasource loop body) from the
original create_datasources_from_upload_bulk endpoint, so the endpoint file
itself stays under the line cap. Each expected failure (channel not found,
access denied, duplicate name, missing filename, failed validation, failed
vault integration) is raised as BulkItemFailure so the caller's loop can
append it to failed_datasources with the exact same message text as before;
any other exception is left to propagate and is caught generically by the
caller, exactly like the original per-item try/except.
"""

import os
from datetime import datetime

from sqlalchemy import and_, select

from app.models.channel import Channel
from app.models.datasource import Datasource
from app.services.file_storage import generate_structured_path
from app.utils.file_validation import validate_file_content

from ._bulk_item_failure import BulkItemFailure
from ._from_upload_bulk_persist import save_bulk_upload_item_with_vault
from ._upload_shared import build_config_from_upload_result, build_enhanced_metadata_for_upload

__all__ = ["BulkItemFailure", "process_from_upload_bulk_item"]


async def process_from_upload_bulk_item(datasource_data, file, isValidationRequired, company, storage_service, user, db) -> dict:
    """Process a single (datasource_data, file) pair. Returns the created_datasources entry dict."""
    # Get channel
    stmt = select(Channel).where(Channel.id == datasource_data.channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()

    if not channel:
        raise BulkItemFailure(datasource_data.name, "Channel not found")

    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise BulkItemFailure(datasource_data.name, "Access denied to channel")

    # Check for duplicate datasource in the same channel
    existing_datasource_stmt = select(Datasource).where(
        and_(
            Datasource.name == datasource_data.name,
            Datasource.channel_id == datasource_data.channel_id
        )
    )
    existing_datasource_result = await db.execute(existing_datasource_stmt)
    if existing_datasource_result.scalars().first():
        raise BulkItemFailure(
            datasource_data.name,
            f"Datasource with name '{datasource_data.name}' already exists in this channel"
        )

    # Validate file
    if not file.filename:
        raise BulkItemFailure(datasource_data.name, "File name is required")

    # Read file content
    file_content = await file.read()

    # Validate file content before uploading (if validation is required)
    if isValidationRequired and not validate_file_content(file_content, file.filename):
        raise BulkItemFailure(datasource_data.name, "File validation failed - no valid section headers found")

    # Generate structured path
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

    # Upload file with structured path
    upload_result = await storage_service.upload_file(
        file_content=file_content,
        destination_path=structured_path,
        original_filename=file.filename
    )

    # Auto-generate name from filename if not provided
    datasource_name = datasource_data.name
    if not datasource_name:
        base_filename = os.path.splitext(file.filename)[0]
        datasource_name = base_filename.replace('_', ' ').replace('-', ' ').title()

    storage_type, provider, config = build_config_from_upload_result(upload_result, file.filename)

    enhanced_metadata = await build_enhanced_metadata_for_upload(
        filename=file.filename,
        storage_type=storage_type,
        provider=provider,
        channel_id=datasource_data.channel_id,
        workspace_id=str(channel.workspace_id),
        user_id=str(user.id),
        file_size=len(file_content),
        file_type=file.content_type or "application/octet-stream",
        log_type=datasource_data.log_type,
        config=config,
        file_url=upload_result["file_url"],
        db=db,
    )

    return await save_bulk_upload_item_with_vault(
        datasource_data=datasource_data,
        file=file,
        file_content=file_content,
        storage_type=storage_type,
        provider=provider,
        config=config,
        enhanced_metadata=enhanced_metadata,
        upload_result=upload_result,
        datasource_name=datasource_name,
        channel=channel,
        user=user,
        db=db,
    )
