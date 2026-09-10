"""
Shared upload helpers used by both the plain-upload endpoints in this
package and app.routes.gg_datasources.create_from_upload (which builds a
GGDatasource row on top of an upload).
"""

import os
from datetime import datetime
from typing import Any, Dict

from fastapi import HTTPException, UploadFile

from app.models.company import Company
from app.services.file_storage import get_file_storage_service, generate_structured_path
from app.utils.file_validation import validate_file_content


async def _upload_single_file(
    file: UploadFile,
    company: Company,
    is_validation_required: bool,
) -> Dict[str, Any]:
    """Upload a file to storage and return upload_result dict. Raises HTTPException on failure."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")

    storage_service = get_file_storage_service()
    file_content = await file.read()

    if is_validation_required and not validate_file_content(file_content, file.filename):
        raise HTTPException(
            status_code=400,
            detail="File validation failed - no valid section headers found",
        )

    file_extension = os.path.splitext(file.filename)[1]
    base_filename  = os.path.splitext(file.filename)[0]
    current_date   = datetime.now().strftime("%Y-%m-%d")

    structured_path = generate_structured_path(
        company_name=company.name,
        company_id=str(company.id),
        file_type="datasource",
        original_filename=file.filename,
        base_filename=base_filename,
        file_extension=file_extension,
        current_date=current_date,
    )

    upload_result = await storage_service.upload_file(
        file_content=file_content,
        destination_path=structured_path,
        original_filename=file.filename,
    )
    upload_result["file_content"] = file_content
    upload_result["file_size"]    = len(file_content)
    upload_result["file_type"]    = file.content_type or "application/octet-stream"
    upload_result["original_filename"] = file.filename
    return upload_result


def _build_config_from_upload(upload_result: Dict[str, Any]) -> Dict[str, Any]:
    provider = upload_result.get("provider", "")
    config: Dict[str, Any] = {
        "file_path":         upload_result.get("storage_path"),
        "original_filename": upload_result.get("original_filename"),
    }
    if provider == "aws":
        config.update({"bucket_name": upload_result.get("bucket_name"), "region": upload_result.get("region")})
    elif provider == "azure":
        config.update({"container_name": upload_result.get("container_name"), "account_name": upload_result.get("account_name")})
    elif provider == "oracle":
        config.update({"bucket_name": upload_result.get("bucket_name"), "namespace": upload_result.get("namespace"), "compartment_id": upload_result.get("compartment_id")})
    return config
