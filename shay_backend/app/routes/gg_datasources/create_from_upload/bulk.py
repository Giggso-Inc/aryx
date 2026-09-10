"""
POST /from-upload/bulk — upload multiple files and create GGDatasource rows.

Stated exception: this handler stays a little larger than a typical
endpoint because it is one atomic per-item upload -> vault-integration ->
row-create flow, repeated across the batch; the metadata + vault-integration
portion shared with single.py has already been extracted to ._metadata.
"""

import json
import os
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import GGDatasourceBulkResponse, GGDatasourceResponse
from ..response import _to_response
from ..upload import _upload_single_file
from ._metadata import _build_metadata_and_vault

router = APIRouter()


@router.post("/from-upload/bulk", response_model=GGDatasourceBulkResponse)
async def create_datasources_from_upload_bulk(
    datasources_json: str      = Form(..., description='JSON array: [{level, scope_id, name, log_type}, ...]'),
    isValidationRequired: bool = Form(True),
    files: List[UploadFile]    = File(...),
    request: Request           = None,
    db: AsyncSession           = Depends(get_db),
) -> GGDatasourceBulkResponse:
    """Upload multiple files and create GGDatasource rows. datasources_json must be a JSON array
    with one entry per file, each having: level, scope_id, name (optional), log_type (optional)."""
    user = await get_current_user_required(request, db)

    try:
        ds_list: List[Dict[str, Any]] = json.loads(datasources_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in datasources_json")

    if len(files) != len(ds_list):
        raise HTTPException(status_code=400, detail="Number of files must match number of datasource entries")

    company = (await db.execute(select(Company).where(Company.id == user.company_id))).scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    created: List[GGDatasourceResponse] = []
    failed:  List[Dict[str, Any]] = []

    for ds_meta, file in zip(ds_list, files):
        ds_name   = ds_meta.get("name")
        level     = ds_meta.get("level", "channel")
        scope_id  = ds_meta.get("scope_id", "")
        log_type  = ds_meta.get("log_type")

        if level not in ("workspace", "channel", "thread", "message"):
            failed.append({"name": ds_name, "error": f"Invalid level '{level}'"})
            continue

        try:
            upload_result = await _upload_single_file(file, company, isValidationRequired)
        except HTTPException as exc:
            failed.append({"name": ds_name or file.filename, "error": exc.detail})
            continue
        except Exception as exc:
            failed.append({"name": ds_name or file.filename, "error": str(exc)})
            continue

        if not ds_name:
            base = os.path.splitext(upload_result["original_filename"])[0]
            ds_name = base.replace("_", " ").replace("-", " ").title()

        try:
            provider, storage_type, config, final_metadata, vault_unique_id_val = (
                await _build_metadata_and_vault(upload_result, level, scope_id, log_type, user, db)
            )
        except Exception as exc:
            failed.append({"name": ds_name, "error": f"Vault integration failed: {exc}"})
            continue

        scope_kwargs: Dict[str, Any] = {level + "_id": uuid.UUID(scope_id)}
        ds_obj = GGDatasource(
            id=uuid.uuid4(),
            level=level,
            **scope_kwargs,
            added_by=user.id,
            name=ds_name,
            filename=upload_result["original_filename"],
            storage_type=storage_type,
            provider=provider,
            log_type=log_type,
            config=config,
            datasource_metadata=final_metadata,
            vault_unique_id=vault_unique_id_val,
            file_size=upload_result["file_size"],
            file_type=upload_result["file_type"],
            file_url=upload_result.get("file_url"),
        )
        db.add(ds_obj)
        try:
            await db.commit()
            await db.refresh(ds_obj)
            created.append(_to_response(ds_obj))
        except Exception as exc:
            await db.rollback()
            failed.append({"name": ds_name, "error": str(exc)})

    return GGDatasourceBulkResponse(
        created_datasources=created,
        failed_datasources=failed,
        total_created=len(created),
        total_failed=len(failed),
    )
