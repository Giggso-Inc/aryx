"""
Upload-and-create endpoints (upload a file to storage AND create the
GGDatasource row in one call), plus their bulk counterpart:

  POST   /from-upload
  POST   /from-upload/bulk

Stated exception: both handlers are ~130-260 lines because each is one
atomic upload -> vault-integration -> row-create flow (mirrors the
single-atomic-flow exception in app/routes/tasks/crud.py); splitting the
vault-integration branch out on its own would not reduce total line count,
only relocate it, and would separate code that only makes sense read
together with the row it is about to attach `datasource_metadata` to.
"""

import json
import os
import uuid
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import GGDatasourceBulkResponse, GGDatasourceResponse
from .response import _to_response
from .upload import _build_config_from_upload, _upload_single_file

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

    parsed_metadata: Optional[Dict[str, Any]] = None
    if datasource_metadata:
        try:
            parsed_metadata = json.loads(datasource_metadata)
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

    provider     = upload_result.get("provider", "local")
    storage_type = "cloud" if provider in ("aws", "azure", "oracle") else "local"
    config       = _build_config_from_upload(upload_result)

    # Vault integration
    from app.services.vault_data_builder import enhance_datasource_metadata
    from app.routes.datasources import handle_vault_integration, generate_datasource_metadata, clean_metadata

    metadata = generate_datasource_metadata(
        filename=upload_result["original_filename"],
        storage_type=storage_type,
        channel_id=scope_id if level == "channel" else "",
        workspace_id=scope_id if level == "workspace" else "",
        user_id=str(user.id),
        file_size=upload_result["file_size"],
        file_type=upload_result["file_type"],
        provider=provider,
        app_type=None,
        log_type=log_type,
        config=config,
        file_url=upload_result.get("file_url"),
    )
    cleaned_metadata  = clean_metadata(metadata)
    enhanced_metadata = await enhance_datasource_metadata(
        existing_metadata=cleaned_metadata,
        storage_type=storage_type,
        provider=provider,
        config=config,
        db=db,
        channel_id=scope_id if level == "channel" else None,
    )

    vault_unique_id_val: Optional[UUID] = None
    if enhanced_metadata:
        try:
            vault_result = await handle_vault_integration(
                datasource_metadata=enhanced_metadata,
                user_id=str(user.id),
                company_id=str(user.company_id),
                db=db,
                required=True,
            )
            if vault_result:
                vault_unique_id_val = UUID(str(vault_result["vault_unique_id"]))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Vault integration failed: {exc}")

    final_metadata = (enhanced_metadata or {}).copy()
    if vault_unique_id_val:
        final_metadata["vault_unique_id"] = str(vault_unique_id_val)

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

    from app.services.vault_data_builder import enhance_datasource_metadata
    from app.routes.datasources import handle_vault_integration, generate_datasource_metadata, clean_metadata

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

        provider     = upload_result.get("provider", "local")
        storage_type = "cloud" if provider in ("aws", "azure", "oracle") else "local"
        config       = _build_config_from_upload(upload_result)

        metadata = generate_datasource_metadata(
            filename=upload_result["original_filename"],
            storage_type=storage_type,
            channel_id=scope_id if level == "channel" else "",
            workspace_id=scope_id if level == "workspace" else "",
            user_id=str(user.id),
            file_size=upload_result["file_size"],
            file_type=upload_result["file_type"],
            provider=provider,
            app_type=None,
            log_type=log_type,
            config=config,
            file_url=upload_result.get("file_url"),
        )
        cleaned_metadata  = clean_metadata(metadata)
        enhanced_metadata = await enhance_datasource_metadata(
            existing_metadata=cleaned_metadata,
            storage_type=storage_type,
            provider=provider,
            config=config,
            db=db,
            channel_id=scope_id if level == "channel" else None,
        )

        vault_unique_id_val: Optional[UUID] = None
        try:
            vault_result = await handle_vault_integration(
                datasource_metadata=enhanced_metadata,
                user_id=str(user.id),
                company_id=str(user.company_id),
                db=db,
                required=True,
            )
            if vault_result:
                vault_unique_id_val = UUID(str(vault_result["vault_unique_id"]))
        except Exception as exc:
            failed.append({"name": ds_name, "error": f"Vault integration failed: {exc}"})
            continue

        final_metadata = (enhanced_metadata or {}).copy()
        if vault_unique_id_val:
            final_metadata["vault_unique_id"] = str(vault_unique_id_val)

        scope_kwargs: Dict[str, Any] = {level + "_id": UUID(scope_id)}
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
