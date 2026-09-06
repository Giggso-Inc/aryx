"""
POST /from-upload — upload a file and create a GGDatasource row at the
specified scope.

Stated exception: this handler stays a little larger than a typical
endpoint because it is one atomic upload -> vault-integration -> row-create
flow (mirrors the single-atomic-flow exception in
app/routes/tasks/crud.py); the metadata + vault-integration portion shared
with bulk.py has already been extracted to ._metadata.
"""

import os
import uuid
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import GGDatasourceResponse
from ..response import _to_response
from ..upload import _upload_single_file
from ._metadata import _build_metadata_and_vault

router = APIRouter()


@router.post("/from-upload", response_model=GGDatasourceResponse, status_code=201)
async def create_datasource_from_upload(
    level: str                     = Form(..., description="workspace | channel | thread | message"),
    scope_id: str                  = Form(..., description="ID of the workspace / channel / thread / message"),
    name: Optional[str]            = Form(None),
    log_type: Optional[str]        = Form(None),
    datasource_metadata: Optional[str] = Form(None),  # JSON string
    isValidationRequired: bool     = Form(True),
    file: UploadFile               = File(...),
    request: Request               = None,
    db: AsyncSession               = Depends(get_db),
) -> GGDatasourceResponse:
    """Upload a file and create a GGDatasource row at the specified scope."""
    if level not in ("workspace", "channel", "thread", "message"):
        raise HTTPException(status_code=400, detail="level must be workspace | channel | thread | message")

    user = await get_current_user_required(request, db)

    if datasource_metadata:
        import json
        try:
            json.loads(datasource_metadata)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in datasource_metadata")

    company = (await db.execute(select(Company).where(Company.id == user.company_id))).scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    try:
        upload_result = await _upload_single_file(file, company, isValidationRequired)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {exc}")

    # Auto-generate name from filename
    datasource_name = name
    if not datasource_name:
        base = os.path.splitext(upload_result["original_filename"])[0]
        datasource_name = base.replace("_", " ").replace("-", " ").title()

    try:
        provider, storage_type, config, final_metadata, vault_unique_id_val = (
            await _build_metadata_and_vault(upload_result, level, scope_id, log_type, user, db)
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vault integration failed: {exc}")

    scope_kwargs: Dict[str, Any] = {level + "_id": UUID(scope_id)}
    ds = GGDatasource(
        id=uuid.uuid4(),
        level=level,
        **scope_kwargs,
        added_by=user.id,
        name=datasource_name,
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
    db.add(ds)
    try:
        await db.commit()
        await db.refresh(ds)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    return _to_response(ds)
