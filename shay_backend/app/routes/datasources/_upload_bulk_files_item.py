"""
Per-file upload (plus optional additive Aryx ingestion) for POST
/upload/bulk.

Private module: split out of upload_bulk_files.py (Raven style-compliance,
wave B4) — one file's upload-then-optionally-ingest sequence, called once
per file by the endpoint's loop.
"""

import os
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, UploadFile

from app.models.company import Company
from app.routes.aryx import call_aryx_docs_read
from app.services.file_storage import generate_structured_path
from app.utils.file_validation import validate_file_content


async def _upload_one_bulk_file(
    file: UploadFile,
    company: Company,
    is_validation_required: bool,
    kind: Optional[str],
    aryx_workspace_id: Optional[int],
    aryx_setup_error: Optional[str],
    storage_service: Any,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Upload one file (plus optional Aryx ingestion).

    Returns (uploaded_entry, failed_entry) — exactly one of the two is not None.
    """
    try:
        if not file.filename:
            return None, {"filename": "unknown", "error": "File name is required"}

        # Read file content
        file_content = await file.read()

        # Validate file content before uploading (if validation is required)
        if is_validation_required and not validate_file_content(file_content, file.filename):
            return None, {"filename": file.filename, "error": "File validation failed - no valid section headers found"}

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

        uploaded_entry = {
            "filename": file.filename,
            "storage_path": upload_result["storage_path"],
            "file_url": upload_result["file_url"],
            "file_size": len(file_content),
            "file_type": file.content_type or "application/octet-stream",
            "provider": upload_result["provider"]
        }

        # --- Additive: start Aryx ingestion for this file using the
        # bytes already read above. Never touches uploaded_entry's
        # existing keys — only adds aryx_ingestion.
        if kind == "aryx":
            if aryx_setup_error:
                uploaded_entry["aryx_ingestion"] = {"error": aryx_setup_error}
            else:
                try:
                    aryx_result = await call_aryx_docs_read(
                        aryx_workspace_id,
                        [(file.filename, file_content, file.content_type)],
                    )
                    uploaded_entry["aryx_ingestion"] = {
                        "discovery_id": aryx_result.get("discovery_id"),
                        "status": "queued",
                    }
                except HTTPException as exc:
                    uploaded_entry["aryx_ingestion"] = {"error": str(exc.detail)}

        return uploaded_entry, None

    except Exception as e:
        return None, {"filename": file.filename, "error": str(e)}
