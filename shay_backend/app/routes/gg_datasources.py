"""
GGDatasource routes — unified datasource management across
workspace / channel / thread / message scopes.

Prefix: /api/v1/gg-datasources

Endpoints
─────────
  GET    /supported-log-types           list supported log types
  GET    /environment                   environment/vault debug config
  POST   /upload                        upload a single file (no DB row)
  POST   /upload/bulk                   upload multiple files (no DB rows)
  POST   /from-upload                   upload file + create GGDatasource row
  POST   /from-upload/bulk              upload files + create multiple GGDatasource rows
  POST   /bulk                          bulk-create from JSON payloads
  GET    /stats                         datasource statistics (scope-filtered)
  GET    /count                         connected datasource count by type
  GET    /resolved                      all datasources visible at a scope (with inheritance)
  GET    /                              list datasources (filter by level + scope)
  GET    /embedding-status/{scope_level}/{scope_id}  embedding status for a scope
  POST   /embedding/webhook             ML embedding completion webhook
  POST   /embedding/regenerate/{datasource_id}  re-trigger embedding
  POST   /process                       trigger background processing
  POST   /bulk-connection               bulk connect / disconnect
  GET    /{datasource_id}               get by ID
  PUT    /{datasource_id}               update metadata / flags
  DELETE /{datasource_id}               soft-delete (is_active = False)
  PUT    /{datasource_id}/status        update processing / embedding status (ML callback)
  POST   /{datasource_id}/connect       connect a datasource
  POST   /{datasource_id}/disconnect    disconnect a datasource
  GET    /{datasource_id}/connection-status  get connection status
  GET    /{datasource_id}/download      download / view file
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, Form,
    HTTPException, Query, Request, UploadFile, status,
)
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db, AsyncSessionLocal
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.models.gg_datasource import GGDatasource
from app.schemas.gg_datasource import (
    DatasourceBulkConnectionResponse,
    DatasourceConnectionRequest,
    DatasourceConnectionResponse,
    DatasourceProcessingRequest,
    DatasourceProcessingResponse,
    DatasourceTypeCount,
    DatasourceTypeCountResponse,
    FileUploadBulkResponse,
    FileUploadResponse,
    GGDatasourceBulkCreate,
    GGDatasourceBulkResponse,
    GGDatasourceCreate,
    GGDatasourceList,
    GGDatasourceResponse,
    GGDatasourceStats,
    GGDatasourceUpdate,
    GGEmbeddingStatusResponse,
    MLWebhookRequest,
    MLWebhookResponse,
    ProcessingStatusUpdate,
    RegenerateEmbeddingResponse,
    ResolvedDatasourcesResponse,
)
from app.services.file_storage import get_file_storage_service, generate_structured_path
from app.services.ml_service import ml_service, extract_table_names_from_datasources
from app.utils.file_validation import validate_file_content

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Media-type helpers (for download)
# ---------------------------------------------------------------------------

_FALLBACK_MEDIA_TYPES = {
    "csv":  "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls":  "application/vnd.ms-excel",
    "json": "application/json",
    "pdf":  "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc":  "application/msword",
    "txt":  "text/plain",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt":  "application/vnd.ms-powerpoint",
}

DATASOURCE_DATABASE_PROVIDERS = frozenset({
    "mysql", "postgresql", "sqlserver", "oracle", "mongodb",
    "dynamodb", "redshift", "snowflake",
})


def _get_media_type(ds: GGDatasource) -> str:
    ft = getattr(ds, "file_type", None)
    if ft and isinstance(ft, str) and "/" in ft.strip():
        return ft.strip()
    fn = getattr(ds, "filename", None) or ""
    if isinstance(fn, str):
        ext = os.path.splitext(fn)[1].lstrip(".").lower()
        if ext in _FALLBACK_MEDIA_TYPES:
            return _FALLBACK_MEDIA_TYPES[ext]
    return "application/octet-stream"


def _get_storage_file_path(ds: GGDatasource) -> Optional[str]:
    """Return stored file_path if we own the file (from upload endpoints)."""
    config = ds.config if isinstance(ds.config, dict) else {}
    path = config.get("file_path")
    if not path and ds.datasource_metadata:
        meta = ds.datasource_metadata
        if isinstance(meta, dict):
            creds = meta.get("credentials", {})
            if isinstance(creds, dict):
                path = creds.get("file_path")
    return path


def _get_google_drive_file_id(ds: GGDatasource) -> Optional[str]:
    config = ds.config if isinstance(ds.config, dict) else {}
    fid = config.get("file_id")
    if fid:
        return fid.strip()
    conn = config.get("connection_settings")
    if isinstance(conn, dict):
        account = conn.get("account") if isinstance(conn.get("account"), dict) else {}
        fid = account.get("file_id") or conn.get("file_id")
        if fid:
            return fid.strip()
    return None


def _get_external_view_url(ds: GGDatasource) -> Optional[str]:
    if ds.file_url and ds.file_url.strip():
        return ds.file_url.strip()
    config = ds.config if isinstance(ds.config, dict) else {}
    if config:
        url = config.get("file_url") or config.get("fileUrl")
        if url:
            return url.strip()
        conn = config.get("connection_settings")
        if isinstance(conn, dict):
            account = conn.get("account") if isinstance(conn.get("account"), dict) else {}
            for key in ("webViewLink", "web_content_link", "webContentLink", "url"):
                val = account.get(key) or conn.get(key)
                if val:
                    return val.strip()
    app_type = (getattr(ds, "app_type", None) or "").lower().replace(" ", "")
    if app_type in ("google_drive", "googledrive", "googledrives"):
        fid = _get_google_drive_file_id(ds)
        if fid:
            return f"https://drive.google.com/file/d/{fid}/view"
    return None


# ---------------------------------------------------------------------------
# Response helper
# ---------------------------------------------------------------------------

def _to_response(ds: GGDatasource) -> GGDatasourceResponse:
    return GGDatasourceResponse(
        id=str(ds.id),
        level=ds.level,
        workspace_id=str(ds.workspace_id) if ds.workspace_id else None,
        channel_id=str(ds.channel_id)     if ds.channel_id   else None,
        thread_id=str(ds.thread_id)       if ds.thread_id    else None,
        message_id=str(ds.message_id)     if ds.message_id   else None,
        added_by=str(ds.added_by)         if ds.added_by     else None,
        name=ds.name,
        filename=ds.filename,
        storage_type=ds.storage_type,
        provider=ds.provider,
        app_type=ds.app_type,
        config=ds.config,
        datasource_metadata=ds.datasource_metadata,
        vault_unique_id=str(ds.vault_unique_id) if ds.vault_unique_id else None,
        file_size=ds.file_size,
        file_type=ds.file_type,
        file_url=ds.file_url,
        log_type=ds.log_type,
        is_active=ds.is_active,
        is_connected=ds.is_connected,
        is_processed=ds.is_processed,
        processing_status=ds.processing_status,
        error_message=ds.error_message,
        is_embedding_required=ds.is_embedding_required,
        embedding_status=ds.embedding_status,
        last_processed_at=ds.last_processed_at,
        processing_time=ds.processing_time,
        record_count=ds.record_count,
        created_at=ds.created_at,
        updated_at=ds.updated_at,
    )


# ---------------------------------------------------------------------------
# Upload helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# GET /supported-log-types
# ---------------------------------------------------------------------------

@router.get("/supported-log-types", response_model=List[str])
async def get_supported_log_types():
    """Get list of supported log types configured in environment."""
    return settings.SUPPORTED_LOG_TYPES


# ---------------------------------------------------------------------------
# GET /environment
# ---------------------------------------------------------------------------

@router.get("/environment", response_model=Dict[str, Any])
async def get_environment_config():
    """Get current environment configuration for debugging vault settings."""
    from app.services.vault_data_builder import get_environment_info
    return get_environment_info()


# ---------------------------------------------------------------------------
# POST /upload — upload a single file (no datasource row created)
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    isValidationRequired: bool = Form(True),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """Upload a single file to storage (no GGDatasource row created)."""
    user = await get_current_user_required(request, db)

    company = (await db.execute(select(Company).where(Company.id == user.company_id))).scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    try:
        upload_result = await _upload_single_file(file, company, isValidationRequired)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {exc}")

    return FileUploadResponse(
        filename=upload_result["original_filename"],
        storage_path=upload_result["storage_path"],
        file_url=upload_result["file_url"],
        file_size=upload_result["file_size"],
        file_type=upload_result["file_type"],
        provider=upload_result["provider"],
    )


# ---------------------------------------------------------------------------
# POST /upload/bulk — upload multiple files (no datasource rows created)
# ---------------------------------------------------------------------------

@router.post("/upload/bulk", response_model=FileUploadBulkResponse)
async def upload_files_bulk(
    files: List[UploadFile] = File(...),
    isValidationRequired: bool = Form(True),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """Upload multiple files to storage (no GGDatasource rows created)."""
    user = await get_current_user_required(request, db)

    company = (await db.execute(select(Company).where(Company.id == user.company_id))).scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    uploaded_files: List[FileUploadResponse] = []
    failed_files: List[Dict[str, Any]] = []

    for file in files:
        try:
            upload_result = await _upload_single_file(file, company, isValidationRequired)
            uploaded_files.append(FileUploadResponse(
                filename=upload_result["original_filename"],
                storage_path=upload_result["storage_path"],
                file_url=upload_result["file_url"],
                file_size=upload_result["file_size"],
                file_type=upload_result["file_type"],
                provider=upload_result["provider"],
            ))
        except HTTPException as exc:
            failed_files.append({"filename": file.filename or "unknown", "error": exc.detail})
        except Exception as exc:
            failed_files.append({"filename": file.filename or "unknown", "error": str(exc)})

    return FileUploadBulkResponse(
        uploaded_files=uploaded_files,
        failed_files=failed_files,
        total_uploaded=len(uploaded_files),
        total_failed=len(failed_files),
    )


# ---------------------------------------------------------------------------
# POST /from-upload — upload file and create a GGDatasource row
# ---------------------------------------------------------------------------

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
):
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


# ---------------------------------------------------------------------------
# POST /from-upload/bulk — upload multiple files and create GGDatasource rows
# ---------------------------------------------------------------------------

@router.post("/from-upload/bulk", response_model=GGDatasourceBulkResponse)
async def create_datasources_from_upload_bulk(
    datasources_json: str      = Form(..., description='JSON array: [{level, scope_id, name, log_type}, ...]'),
    isValidationRequired: bool = Form(True),
    files: List[UploadFile]    = File(...),
    request: Request           = None,
    db: AsyncSession           = Depends(get_db),
):
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


# ---------------------------------------------------------------------------
# POST /bulk — bulk-create from JSON payloads
# ---------------------------------------------------------------------------

@router.post("/bulk", response_model=GGDatasourceBulkResponse, status_code=201)
async def bulk_create_datasources(
    payload: GGDatasourceBulkCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Bulk-create GGDatasource rows from JSON payloads."""
    user = await get_current_user_required(request, db)

    created: List[GGDatasourceResponse] = []
    failed:  List[Dict[str, Any]] = []

    for item in payload.datasources:
        scope_fk = {item.level + "_id": UUID(getattr(item, item.level + "_id"))}
        ds_obj = GGDatasource(
            id=uuid.uuid4(),
            level=item.level,
            **scope_fk,
            added_by=user.id,
            name=item.name,
            filename=item.filename,
            storage_type=item.storage_type,
            provider=item.provider,
            app_type=item.app_type,
            config=item.config or {},
            datasource_metadata=item.datasource_metadata or {},
            vault_unique_id=UUID(item.vault_unique_id) if item.vault_unique_id else None,
            file_size=item.file_size,
            file_type=item.file_type,
            file_url=item.file_url,
            log_type=item.log_type,
            is_embedding_required=item.is_embedding_required,
        )
        db.add(ds_obj)
        try:
            await db.commit()
            await db.refresh(ds_obj)
            created.append(_to_response(ds_obj))
        except Exception as exc:
            await db.rollback()
            failed.append({"name": item.name, "error": str(exc)})

    return GGDatasourceBulkResponse(
        created_datasources=created,
        failed_datasources=failed,
        total_created=len(created),
        total_failed=len(failed),
    )


# ---------------------------------------------------------------------------
# POST /  — create
# ---------------------------------------------------------------------------

@router.post("/", response_model=GGDatasourceResponse, status_code=status.HTTP_201_CREATED)
async def create_datasource(
    payload: GGDatasourceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Add a datasource at workspace, channel, thread, or message scope.
    Exactly one scope FK must match the declared level.
    """
    current_user = await get_current_user_required(request, db)

    ds = GGDatasource(
        id=uuid.uuid4(),
        level=payload.level,
        workspace_id=UUID(payload.workspace_id) if payload.workspace_id else None,
        channel_id=UUID(payload.channel_id)     if payload.channel_id   else None,
        thread_id=UUID(payload.thread_id)       if payload.thread_id    else None,
        message_id=UUID(payload.message_id)     if payload.message_id   else None,
        added_by=current_user.id,
        name=payload.name,
        filename=payload.filename,
        storage_type=payload.storage_type,
        provider=payload.provider,
        app_type=payload.app_type,
        config=payload.config or {},
        datasource_metadata=payload.datasource_metadata or {},
        vault_unique_id=UUID(payload.vault_unique_id) if payload.vault_unique_id else None,
        file_size=payload.file_size,
        file_type=payload.file_type,
        file_url=payload.file_url,
        log_type=payload.log_type,
        is_embedding_required=payload.is_embedding_required,
    )
    db.add(ds)
    try:
        await db.commit()
        await db.refresh(ds)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    return _to_response(ds)


# ---------------------------------------------------------------------------
# GET /resolved  — inheritance-aware fetch (must be before /{id})
# ---------------------------------------------------------------------------

@router.get("/resolved", response_model=ResolvedDatasourcesResponse)
async def get_resolved_datasources(
    request: Request,
    workspace_id: Optional[str] = Query(None),
    channel_id:   Optional[str] = Query(None),
    thread_id:    Optional[str] = Query(None),
    message_id:   Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Return all active datasources visible at the given scope using
    top-down inheritance:  workspace → channel → thread → message.
    """
    await get_current_user_required(request, db)

    result: ResolvedDatasourcesResponse = ResolvedDatasourcesResponse()

    async def _fetch(level: str, fk_col, fk_val: Optional[str]):
        if not fk_val:
            return []
        stmt = (
            select(GGDatasource)
            .where(and_(
                fk_col == UUID(fk_val),
                GGDatasource.level == level,
                GGDatasource.is_active == True,
            ))
            .order_by(GGDatasource.name)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [_to_response(r) for r in rows]

    result.workspace = await _fetch("workspace", GGDatasource.workspace_id, workspace_id)
    result.channel   = await _fetch("channel",   GGDatasource.channel_id,   channel_id)
    result.thread    = await _fetch("thread",     GGDatasource.thread_id,    thread_id)
    result.message   = await _fetch("message",    GGDatasource.message_id,   message_id)
    result.total = (
        len(result.workspace) + len(result.channel) +
        len(result.thread)    + len(result.message)
    )
    return result


# ---------------------------------------------------------------------------
# GET /stats  — statistics (scope-filtered)
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=GGDatasourceStats)
async def get_datasource_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    level:        Optional[str] = Query(None),
    workspace_id: Optional[str] = Query(None),
    channel_id:   Optional[str] = Query(None),
    thread_id:    Optional[str] = Query(None),
    message_id:   Optional[str] = Query(None),
):
    """Get datasource statistics, optionally scoped by level and scope ID."""
    await get_current_user_required(request, db)

    filters = []
    if level:        filters.append(GGDatasource.level == level)
    if workspace_id: filters.append(GGDatasource.workspace_id == UUID(workspace_id))
    if channel_id:   filters.append(GGDatasource.channel_id   == UUID(channel_id))
    if thread_id:    filters.append(GGDatasource.thread_id    == UUID(thread_id))
    if message_id:   filters.append(GGDatasource.message_id   == UUID(message_id))

    base_q = select(GGDatasource).where(and_(*filters)) if filters else select(GGDatasource)

    all_rows = (await db.execute(base_q)).scalars().all()
    total     = len(all_rows)
    active    = sum(1 for r in all_rows if r.is_active)
    processed = sum(1 for r in all_rows if r.is_processed)
    pending   = sum(1 for r in all_rows if r.processing_status == "pending")
    failed_c  = sum(1 for r in all_rows if r.processing_status == "failed")
    total_sz  = sum(r.file_size for r in all_rows if r.file_size)

    st_breakdown: Dict[str, int] = {}
    prov_breakdown: Dict[str, int] = {}
    for r in all_rows:
        st_breakdown[r.storage_type] = st_breakdown.get(r.storage_type, 0) + 1
        if r.provider:
            prov_breakdown[r.provider] = prov_breakdown.get(r.provider, 0) + 1

    return GGDatasourceStats(
        total_datasources=total,
        active_datasources=active,
        processed_datasources=processed,
        pending_datasources=pending,
        failed_datasources=failed_c,
        total_file_size=total_sz,
        storage_type_breakdown=st_breakdown,
        provider_breakdown=prov_breakdown,
    )


# ---------------------------------------------------------------------------
# GET /count  — connected datasource count by storage type
# ---------------------------------------------------------------------------

@router.get("/count", response_model=DatasourceTypeCountResponse)
async def get_datasource_type_count(
    request: Request,
    db: AsyncSession = Depends(get_db),
    level:        Optional[str] = Query(None),
    workspace_id: Optional[str] = Query(None),
    channel_id:   Optional[str] = Query(None),
    thread_id:    Optional[str] = Query(None),
    message_id:   Optional[str] = Query(None),
):
    """Get count of connected datasources by storage type (local, cloud, app, database)."""
    await get_current_user_required(request, db)

    filters = [GGDatasource.is_connected == True]
    if level:        filters.append(GGDatasource.level == level)
    if workspace_id: filters.append(GGDatasource.workspace_id == UUID(workspace_id))
    if channel_id:   filters.append(GGDatasource.channel_id   == UUID(channel_id))
    if thread_id:    filters.append(GGDatasource.thread_id    == UUID(thread_id))
    if message_id:   filters.append(GGDatasource.message_id   == UUID(message_id))

    count_q = (
        select(GGDatasource.storage_type, func.count(GGDatasource.id).label("cnt"))
        .where(and_(*filters))
        .group_by(GGDatasource.storage_type)
    )
    rows = (await db.execute(count_q)).all()
    type_counts = {r.storage_type: r.cnt for r in rows}

    ds_types = ["local", "cloud", "app", "database"]
    counts = []
    total = 0
    for t in ds_types:
        c = type_counts.get(t, 0)
        total += c
        counts.append(DatasourceTypeCount(type=t, count=c))

    return DatasourceTypeCountResponse(counts=counts, total_connected=total)


# ---------------------------------------------------------------------------
# GET /  — list with filters
# ---------------------------------------------------------------------------

@router.get("/", response_model=GGDatasourceList)
async def list_datasources(
    request: Request,
    level:             Optional[str]  = Query(None, description="workspace | channel | thread | message"),
    workspace_id:      Optional[str]  = Query(None),
    channel_id:        Optional[str]  = Query(None),
    thread_id:         Optional[str]  = Query(None),
    message_id:        Optional[str]  = Query(None),
    storage_type:      Optional[str]  = Query(None),
    processing_status: Optional[str]  = Query(None),
    embedding_status:  Optional[int]  = Query(None),
    is_active:         Optional[bool] = Query(None),
    page:              int = Query(1, ge=1),
    page_size:         int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List datasources with optional filters and pagination."""
    await get_current_user_required(request, db)

    filters = []
    if level:             filters.append(GGDatasource.level == level)
    if workspace_id:      filters.append(GGDatasource.workspace_id == UUID(workspace_id))
    if channel_id:        filters.append(GGDatasource.channel_id   == UUID(channel_id))
    if thread_id:         filters.append(GGDatasource.thread_id    == UUID(thread_id))
    if message_id:        filters.append(GGDatasource.message_id   == UUID(message_id))
    if storage_type:      filters.append(GGDatasource.storage_type == storage_type)
    if processing_status: filters.append(GGDatasource.processing_status == processing_status)
    if embedding_status is not None:
                          filters.append(GGDatasource.embedding_status == embedding_status)
    if is_active is not None:
                          filters.append(GGDatasource.is_active == is_active)

    count_stmt = select(func.count(GGDatasource.id)).where(and_(*filters)) if filters else select(func.count(GGDatasource.id))
    total = (await db.execute(count_stmt)).scalar() or 0

    offset = (page - 1) * page_size
    stmt = (
        select(GGDatasource)
        .where(and_(*filters) if filters else True)
        .order_by(GGDatasource.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).scalars().all()

    return GGDatasourceList(
        items=[_to_response(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /embedding-status/{scope_level}/{scope_id}
# ---------------------------------------------------------------------------

@router.get("/embedding-status/{scope_level}/{scope_id}", response_model=GGEmbeddingStatusResponse)
async def get_embedding_status(
    scope_level: str,
    scope_id:    str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get embedding status for all datasources at a given scope level."""
    await get_current_user_required(request, db)

    if scope_level not in ("workspace", "channel", "thread", "message"):
        raise HTTPException(status_code=400, detail="scope_level must be workspace | channel | thread | message")

    fk_col = {
        "workspace": GGDatasource.workspace_id,
        "channel":   GGDatasource.channel_id,
        "thread":    GGDatasource.thread_id,
        "message":   GGDatasource.message_id,
    }[scope_level]

    stmt = select(GGDatasource).where(
        and_(fk_col == UUID(scope_id), GGDatasource.level == scope_level)
    )
    datasources = (await db.execute(stmt)).scalars().all()

    total = len(datasources)
    emb_required = in_progress = completed = failed = not_required = 0
    ds_list = []

    for ds in datasources:
        if ds.is_embedding_required:
            emb_required += 1
        if ds.embedding_status == 0:
            not_required += 1
        elif ds.embedding_status == 1:
            in_progress += 1
        elif ds.embedding_status == 2:
            completed += 1
        elif ds.embedding_status == 3:
            failed += 1
        ds_list.append({
            "id":                    str(ds.id),
            "name":                  ds.name,
            "filename":              ds.filename,
            "is_embedding_required": ds.is_embedding_required,
            "embedding_status":      ds.embedding_status,
            "error_message":         ds.error_message,
            "created_at":            ds.created_at,
            "updated_at":            ds.updated_at,
        })

    return GGEmbeddingStatusResponse(
        scope_level=scope_level,
        scope_id=scope_id,
        total_datasources=total,
        embedding_required=emb_required,
        in_progress=in_progress,
        completed=completed,
        failed=failed,
        not_required=not_required,
        datasources=ds_list,
    )


# ---------------------------------------------------------------------------
# POST /embedding/webhook  — ML callback
# ---------------------------------------------------------------------------

@router.post("/embedding/webhook", response_model=MLWebhookResponse)
async def ml_embedding_webhook(
    webhook_data: MLWebhookRequest,
    db: AsyncSession = Depends(get_db),
):
    """Webhook endpoint for ML team to report embedding completion status."""
    try:
        vault_unique_ids = webhook_data.vaultUniqueIds
        emb_status = 2 if webhook_data.status == "success" else 3

        updated = 0
        failed_c = 0
        for vault_uid in vault_unique_ids:
            try:
                uuid_val = UUID(vault_uid)
                stmt = select(GGDatasource).where(GGDatasource.vault_unique_id == uuid_val)
                rows = (await db.execute(stmt)).scalars().all()
                for ds in rows:
                    ds.embedding_status = emb_status
                    if emb_status == 3:
                        ds.error_message = webhook_data.message or "Embedding processing failed"
                    else:
                        ds.error_message = None
                    ds.updated_at = datetime.utcnow()
                    updated += 1
            except Exception:
                failed_c += 1

        if updated:
            await db.commit()

        return MLWebhookResponse(
            message=f"Updated {updated} datasource(s)",
            processed_count=updated,
            failed_count=failed_c,
        )
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to process webhook: {exc}")


# ---------------------------------------------------------------------------
# POST /embedding/regenerate/{datasource_id}
# ---------------------------------------------------------------------------

@router.post("/embedding/regenerate/{datasource_id}", response_model=RegenerateEmbeddingResponse)
async def regenerate_embedding(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Re-trigger embedding for a specific GGDatasource."""
    user = await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    if str(ds.added_by) != str(user.id):
        raise HTTPException(status_code=403, detail="You don't have permission to regenerate embedding for this datasource")

    if not ds.vault_unique_id:
        raise HTTPException(status_code=400, detail="Datasource does not have vault integration. Cannot regenerate embedding.")

    ds.embedding_status = 1  # in progress
    ds.updated_at = datetime.utcnow()
    await db.commit()

    try:
        from app.services.ml_service import get_embedd_type_from_file_type
        embedd_type = get_embedd_type_from_file_type(
            file_type=ds.file_type,
            storage_type=ds.storage_type,
            provider=ds.provider,
        )

        table_name = None
        if ds.datasource_metadata and isinstance(ds.datasource_metadata, dict):
            table_name = ds.datasource_metadata.get("tableName")

        auth_header = request.headers.get("Authorization")
        jwt_token = auth_header.split(" ")[1] if auth_header and auth_header.startswith("Bearer ") else None

        scope_id = str(
            ds.channel_id or ds.workspace_id or ds.thread_id or ds.message_id
        )

        await ml_service.request_embedding_processing(
            vault_unique_ids=[str(ds.vault_unique_id)],
            user_id=str(user.id),
            company_id=str(user.company_id),
            channel_id=scope_id,
            embedded_vault_unique_ids=[],
            jwt_token=jwt_token,
            embedd_type=embedd_type,
            table_name=table_name,
            table_names=None,
            openai_vault_token=None,
        )

        return RegenerateEmbeddingResponse(
            success=True,
            message="Embedding regeneration triggered successfully",
            datasource_id=datasource_id,
            embedding_status=1,
            status_description="in_progress",
        )
    except Exception as exc:
        ds.embedding_status = 3
        ds.error_message    = str(exc)
        ds.updated_at       = datetime.utcnow()
        await db.commit()
        return RegenerateEmbeddingResponse(
            success=False,
            message=f"Failed to trigger embedding: {exc}",
            datasource_id=datasource_id,
            embedding_status=3,
            status_description="failed",
        )


# ---------------------------------------------------------------------------
# POST /process  — trigger background processing
# ---------------------------------------------------------------------------

@router.post("/process", response_model=DatasourceProcessingResponse)
async def process_datasource(
    payload: DatasourceProcessingRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Trigger background processing for a datasource."""
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(payload.datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    background_tasks.add_task(_process_datasource_background, payload.datasource_id)

    return DatasourceProcessingResponse(
        datasource_id=payload.datasource_id,
        status="processing_started",
        message="Datasource processing started in background",
    )


async def _process_datasource_background(datasource_id: str):
    async with AsyncSessionLocal() as db:
        try:
            ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
            if not ds:
                return
            ds.processing_status = "processing"
            ds.updated_at = datetime.utcnow()
            await db.commit()

            await asyncio.sleep(5)

            async with AsyncSessionLocal() as db2:
                ds2 = (await db2.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
                if ds2:
                    ds2.processing_status = "completed"
                    ds2.is_processed      = True
                    ds2.last_processed_at = datetime.utcnow()
                    ds2.updated_at        = datetime.utcnow()
                    await db2.commit()
        except Exception as exc:
            async with AsyncSessionLocal() as db3:
                ds3 = (await db3.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
                if ds3:
                    ds3.processing_status = "failed"
                    ds3.error_message     = str(exc)
                    ds3.updated_at        = datetime.utcnow()
                    await db3.commit()


# ---------------------------------------------------------------------------
# POST /bulk-connection  — bulk connect / disconnect
# ---------------------------------------------------------------------------

@router.post("/bulk-connection", response_model=DatasourceBulkConnectionResponse)
async def bulk_manage_connections(
    payload: DatasourceConnectionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Bulk connect or disconnect multiple GGDatasources."""
    await get_current_user_required(request, db)
    action = payload.action.lower()

    ids = [UUID(did) for did in payload.datasource_ids]
    datasources = (await db.execute(select(GGDatasource).where(GGDatasource.id.in_(ids)))).scalars().all()

    found_ids = {str(ds.id) for ds in datasources}
    missing   = set(payload.datasource_ids) - found_ids
    if missing:
        raise HTTPException(status_code=404, detail=f"Datasources not found: {', '.join(missing)}")

    successful: List[DatasourceConnectionResponse] = []
    failed:     List[Dict[str, Any]] = []

    for ds in datasources:
        if action == "connect":
            if ds.is_connected:
                failed.append({"datasource_id": str(ds.id), "error": "Already connected"})
                continue
            ds.is_connected = True
            msg = "Datasource connected successfully"
        else:
            if not ds.is_connected:
                failed.append({"datasource_id": str(ds.id), "error": "Already disconnected"})
                continue
            ds.is_connected = False
            msg = "Datasource disconnected successfully"

        ds.updated_at = datetime.utcnow()
        successful.append(DatasourceConnectionResponse(
            datasource_id=str(ds.id),
            is_connected=ds.is_connected,
            message=msg,
            updated_at=ds.updated_at,
        ))

    if successful:
        await db.commit()

    return DatasourceBulkConnectionResponse(
        successful_operations=successful,
        failed_operations=failed,
        total_successful=len(successful),
        total_failed=len(failed),
        action_performed=action,
        message=f"Successfully {action}ed {len(successful)} datasource(s)" + (f", {len(failed)} failed" if failed else ""),
    )


# ---------------------------------------------------------------------------
# GET /{datasource_id}  — get by ID
# ---------------------------------------------------------------------------

@router.get("/{datasource_id}", response_model=GGDatasourceResponse)
async def get_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")
    return _to_response(ds)


# ---------------------------------------------------------------------------
# GET /{datasource_id}/download  — download / view file
# ---------------------------------------------------------------------------

@router.get("/{datasource_id}/download")
async def download_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    view: bool = Query(False, description="If true, inline disposition for browser display; else attachment"),
):
    """Download or view a datasource file. Streams local/S3 files; redirects to external URLs."""
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    # Case 1: file stored in our storage
    storage_path = _get_storage_file_path(ds)
    if storage_path:
        try:
            storage_service = get_file_storage_service()
            file_content = await storage_service.download_file(storage_path)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"File not found or failed to download: {exc}")
        media_type  = _get_media_type(ds)
        filename    = ds.filename or "datasource_file"
        disposition = "inline" if view else "attachment"
        return Response(
            content=file_content,
            media_type=media_type,
            headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
        )

    # Case 2: external URL
    external_url = _get_external_view_url(ds)
    if external_url:
        if "application/json" in (request.headers.get("accept") or "").lower():
            return JSONResponse(status_code=200, content={"url": external_url})
        return RedirectResponse(url=external_url, status_code=302)

    # Case 3: database datasource — no file
    if ds.storage_type == "database" or (ds.provider and ds.provider in DATASOURCE_DATABASE_PROVIDERS):
        raise HTTPException(
            status_code=404,
            detail="Database datasources do not have a viewable or downloadable file.",
        )

    raise HTTPException(status_code=404, detail="No downloadable file found for this datasource")


# ---------------------------------------------------------------------------
# PUT /{datasource_id}  — update
# ---------------------------------------------------------------------------

@router.put("/{datasource_id}", response_model=GGDatasourceResponse)
async def update_datasource(
    datasource_id: str,
    payload: GGDatasourceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        if field == "vault_unique_id" and value:
            value = UUID(value)
        setattr(ds, field, value)

    ds.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(ds)
    return _to_response(ds)


# ---------------------------------------------------------------------------
# DELETE /{datasource_id}  — soft delete
# ---------------------------------------------------------------------------

@router.delete("/{datasource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    ds.is_active  = False
    ds.updated_at = datetime.utcnow()
    await db.commit()


# ---------------------------------------------------------------------------
# PUT /{datasource_id}/status  — processing / embedding status (ML callback)
# ---------------------------------------------------------------------------

@router.put("/{datasource_id}/status", response_model=GGDatasourceResponse)
async def update_processing_status(
    datasource_id: str,
    payload: ProcessingStatusUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Called by ML agents to report processing / embedding progress."""
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(ds, field, value)

    if payload.processing_status == "completed":
        ds.last_processed_at = datetime.utcnow()

    ds.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(ds)
    return _to_response(ds)


# ---------------------------------------------------------------------------
# POST /{datasource_id}/connect
# ---------------------------------------------------------------------------

@router.post("/{datasource_id}/connect", response_model=DatasourceConnectionResponse)
async def connect_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Connect a datasource."""
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")
    if ds.is_connected:
        raise HTTPException(status_code=400, detail="Datasource is already connected")

    ds.is_connected = True
    ds.updated_at   = datetime.utcnow()
    await db.commit()
    await db.refresh(ds)

    return DatasourceConnectionResponse(
        datasource_id=str(ds.id),
        is_connected=ds.is_connected,
        message="Datasource connected successfully",
        updated_at=ds.updated_at,
    )


# ---------------------------------------------------------------------------
# POST /{datasource_id}/disconnect
# ---------------------------------------------------------------------------

@router.post("/{datasource_id}/disconnect", response_model=DatasourceConnectionResponse)
async def disconnect_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Disconnect a datasource."""
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")
    if not ds.is_connected:
        raise HTTPException(status_code=400, detail="Datasource is already disconnected")

    ds.is_connected = False
    ds.updated_at   = datetime.utcnow()
    await db.commit()
    await db.refresh(ds)

    return DatasourceConnectionResponse(
        datasource_id=str(ds.id),
        is_connected=ds.is_connected,
        message="Datasource disconnected successfully",
        updated_at=ds.updated_at,
    )


# ---------------------------------------------------------------------------
# GET /{datasource_id}/connection-status
# ---------------------------------------------------------------------------

@router.get("/{datasource_id}/connection-status", response_model=DatasourceConnectionResponse)
async def get_connection_status(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get connection status of a datasource."""
    await get_current_user_required(request, db)

    ds = (await db.execute(select(GGDatasource).where(GGDatasource.id == UUID(datasource_id)))).scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Datasource not found")

    return DatasourceConnectionResponse(
        datasource_id=str(ds.id),
        is_connected=ds.is_connected,
        message=f"Datasource is {'connected' if ds.is_connected else 'disconnected'}",
        updated_at=ds.updated_at,
    )
