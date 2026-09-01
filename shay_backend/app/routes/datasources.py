"""
Datasource routes for managing data sources from various platforms
"""

import asyncio
import base64
import json as _json
import uuid
import os
import logging
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urlparse, unquote
from datetime import datetime
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import Response, RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc, String
from sqlalchemy.sql.expression import literal
from sqlalchemy.orm import joinedload

from app.core.database import get_db, AsyncSessionLocal
from app.core.auth import generate_workspace_id
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.channel import Channel
from app.models.workspace import Workspace
from app.models.datasource import Datasource
from app.models.company import Company
from app.models.channel_member import ChannelMember
from app.models.message import Thread
from app.utils.channel_access import check_channel_access, check_channel_access_by_thread
from app.services.file_storage import get_file_storage_service, generate_structured_path
from app.services.vault_service import vault_service
from app.services.ml_service import ml_service, extract_table_names_from_datasources
from app.services.socket_client_service import get_socket_service
from app.services.vault_data_builder import enhance_datasource_metadata
from app.models.giggso_vault import GiggsoVault
from app.utils.file_validation import validate_file_content, get_validation_summary
from app.schemas.datasource import (
    DatasourceCreate,
    DatasourceBulkCreate,
    DatasourceUpdate,
    DatasourceResponse,
    DatasourceList,
    DatasourceListWithRelations,
    DatasourceStats,
    DatasourceTypeCount,
    DatasourceTypeCountResponse,
    DatasourceProcessingRequest,
    DatasourceProcessingResponse,
    DatasourceBulkResponse,
    LocalDatasourceCreate,
    CloudDatasourceCreate,
    AppDatasourceCreate,
    FileUploadResponse,
    FileUploadBulkResponse,
    DatasourceFromUpload,
    DatasourceFromUploadBulk,
    DatasourceConnectionResponse,
    DatasourceConnectionRequest,
    DatasourceBulkConnectionResponse,
    EmbeddingStatusResponse,
    MLWebhookRequest,
    MLWebhookResponse,
    RegenerateEmbeddingResponse,
    DatasourceBulkCreateInternal,
    DatasourceCreateInternal
)
from app.routes.aryx import (
    _resolve_aryx_workspace_id as _resolve_aryx_workspace_id_for_datasources,
    call_aryx_docs_read,
    call_aryx_job_status,
)
from app.routes.workspaces import _get_workspace_or_404
from app.utils.permissions import require_active_workspace_role

# Initialize logger
logger = logging.getLogger(__name__)

router = APIRouter()


async def _aryx_ingestion_status_for(datasource_metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Best-effort live Aryx job status for a datasource, additive only.

    Returns None (never raises) unless datasource_metadata carries an
    aryx.discovery_id — i.e. this datasource was created via a kind="aryx"
    bulk upload. A datasource without that key is completely unaffected;
    a transient Aryx-unreachable error degrades to None rather than failing
    the caller's whole response.
    """
    if not datasource_metadata:
        return None
    aryx_meta = datasource_metadata.get("aryx")
    if not isinstance(aryx_meta, dict):
        return None
    discovery_id = aryx_meta.get("discovery_id")
    if not discovery_id:
        return None
    try:
        return await call_aryx_job_status(discovery_id)
    except Exception as exc:  # noqa: BLE001 — status enrichment must never break the caller
        logger.warning("aryx_ingestion_status lookup failed for discovery_id=%s: %s", discovery_id, exc)
        return {"error": "status temporarily unavailable"}


@router.get("/supported-log-types", response_model=List[str])
async def get_supported_log_types():
    """Get list of supported log types configured in environment"""
    return settings.SUPPORTED_LOG_TYPES


def clean_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Remove null, empty string, and default values from metadata"""
    cleaned = {}
    for key, value in metadata.items():
        # Skip null values
        if value is None:
            continue
        
        # Skip empty strings
        if isinstance(value, str) and value == "":
            continue
        
        # Skip empty lists
        if isinstance(value, list) and len(value) == 0:
            continue
        
        # Skip empty dicts
        if isinstance(value, dict) and len(value) == 0:
            continue
        
        # Skip default values that are commonly not needed
        if key in ["botFlag", "countFlg", "datasourcePrivacy", "disconnectDataSource", 
                   "emailAttachmentFlg", "emailValidate", "embeddingsGenerated", 
                   "embeddingStatus", "enableDecrypt", "isValidate", "maxCount", 
                   "minCount", "multiSelect", "regenerateEmbeddings", 
                   "scheduleEmbeddingDelayTime", "scheduleEmbeddingFlg", 
                   "startFrom", "threadId", "topicLevelFlg"] and value == 0:
            continue
        
        if key in ["botFlag", "isValidate", "workspaceChannelFlg"] and value == 1:
            continue
        
        if key in ["maxCount"] and value == 10:
            continue
        
        if key in ["minCount", "startFrom", "threadId"] and value == 0:
            continue
        
        cleaned[key] = value
    
    return cleaned


def get_storage_file_path_for_deletion(datasource) -> Optional[str]:
    """
    Extract file path for storage deletion when datasource was uploaded by our system.
    Returns path only when we own the file (from upload, from-upload, from-upload/bulk).
    file_path in config indicates file was stored via our file storage service.
    """
    # Check config first - set when we upload via from-upload or from-upload/bulk
    config = datasource.config if isinstance(datasource.config, dict) else {}
    file_path = config.get("file_path")
    # Fallback: check datasource_metadata for file_path (some flows store it there)
    if not file_path and datasource.datasource_metadata:
        meta = datasource.datasource_metadata
        if isinstance(meta, dict):
            credentials = meta.get("credentials", {})
            if isinstance(credentials, dict):
                file_path = credentials.get("file_path")
    return file_path

# Supported database provider types (no file to view/download; table/collection references only)
DATASOURCE_DATABASE_PROVIDERS = frozenset({
    "mysql", "postgresql", "sqlserver", "oracle", "mongodb", "dynamodb", "redshift", "snowflake"
})

# Extension -> media type for all supported upload formats (csv, xlsx, xls, json, pdf, docx, doc, txt, pptx, ppt)
# Ensures download/view API returns correct Content-Type for every supported file format
_FALLBACK_MEDIA_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "json": "application/json",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "txt": "text/plain",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.ms-powerpoint",
}


def get_media_type_for_download(datasource) -> str:
    """
    Resolve Content-Type for streaming a datasource file (e.g. from our S3/local storage).
    Supports all UI-supported formats: csv, xlsx, xls, json, pdf, docx, doc, txt, pptx, ppt.
    Uses file_type when it looks like a MIME type; otherwise infers from filename for view=1.
    """
    # Prefer stored file_type if it looks like a MIME type (contains "/")
    ft = getattr(datasource, "file_type", None)
    if ft and isinstance(ft, str) and "/" in ft.strip():
        return ft.strip()
    # Infer from filename for tabular and common types
    fn = getattr(datasource, "filename", None) or ""
    if isinstance(fn, str):
        ext = os.path.splitext(fn)[1].lstrip(".").lower()
        if ext in _FALLBACK_MEDIA_TYPES:
            return _FALLBACK_MEDIA_TYPES[ext]
    return "application/octet-stream"


def _get_google_drive_file_id(datasource) -> Optional[str]:
    """Extract Google Drive file_id from datasource config or metadata (for building view URL)."""
    # From config: top-level file_id or connection_settings.account.file_id
    config = datasource.config if isinstance(datasource.config, dict) else {}
    fid = config.get("file_id")
    if fid and isinstance(fid, str) and fid.strip():
        return fid.strip()
    conn = config.get("connection_settings")
    if isinstance(conn, dict):
        account = conn.get("account") if isinstance(conn.get("account"), dict) else {}
        fid = (account.get("file_id") or conn.get("file_id"))
        if fid and isinstance(fid, str) and fid.strip():
            return fid.strip()
    # From config.credentials.additional_config (if present on config)
    creds = config.get("credentials")
    if isinstance(creds, dict):
        add = creds.get("additional_config")
        if isinstance(add, dict):
            fid = add.get("file_id")
            if fid and isinstance(fid, str) and fid.strip():
                return fid.strip()
    # From datasource_metadata.credentials.additional_config
    meta = datasource.datasource_metadata if isinstance(getattr(datasource, "datasource_metadata", None), dict) else {}
    creds = meta.get("credentials")
    if isinstance(creds, dict):
        add = creds.get("additional_config")
        if isinstance(add, dict):
            fid = add.get("file_id")
            if fid and isinstance(fid, str) and fid.strip():
                return fid.strip()
    return None


def get_external_view_url_for_datasource(datasource) -> Optional[str]:
    """
    Resolve a view/download URL for datasources that reference external content.
    - App storage (Google Drive, SharePoint, etc.): file_url on model, or from config/connection_settings,
      or for Google Drive build URL from file_id when only file_id is stored.
    - Cloud storage: file_url on model or in config.
    - Database storage: no file URL (returns None); caller should return appropriate response.
    """
    # Prefer top-level file_url on the datasource
    if datasource.file_url and isinstance(datasource.file_url, str) and datasource.file_url.strip():
        return datasource.file_url.strip()
    # Resolve from config (app or cloud may store URL only in config)
    config = datasource.config if isinstance(datasource.config, dict) else {}
    # Direct file_url in config (e.g. cloud with URL in config)
    if config:
        url = config.get("file_url") or config.get("fileUrl")
        if url and isinstance(url, str) and url.strip():
            return url.strip()
        # App storage: try connection_settings (Google Drive webViewLink/webContentLink, etc.)
        conn = config.get("connection_settings")
        if isinstance(conn, dict):
            account = conn.get("account") if isinstance(conn.get("account"), dict) else {}
            for key in ("webViewLink", "web_content_link", "webContentLink", "url", "viewUrl", "view_url", "alternateLink"):
                val = account.get(key) or conn.get(key)
                if val and isinstance(val, str) and val.strip():
                    return val.strip()
    # Google Drive: if only file_id is stored (no link), build standard view URL
    app_type = (getattr(datasource, "app_type", None) or "").lower().replace(" ", "")
    if app_type in ("google_drive", "googledrive", "googledrives"):
        file_id = _get_google_drive_file_id(datasource)
        if file_id:
            return f"https://drive.google.com/file/d/{file_id}/view"
    return None


async def get_vault_credentials_for_datasource(datasource, db: AsyncSession) -> Optional[Dict[str, Any]]:
    """
    Resolve vault by datasource_id (via datasource.giggso_vault_id), open vault and return stored credentials.
    Returns the full payload from vault (contains 'credentials' and possibly file_url, file_path, etc.).
    """
    if not getattr(datasource, "giggso_vault_id", None):
        return None
    vault_stmt = select(GiggsoVault).where(GiggsoVault.giggso_vault_id == datasource.giggso_vault_id)
    vault_result = await db.execute(vault_stmt)
    vault_record = vault_result.scalar_one_or_none()
    if not vault_record or not vault_record.vault_unique_id:
        return None
    vault_data = await vault_service.retrieve_from_vault(vault_record.vault_unique_id)
    return vault_data


def _get_s3_bucket_and_key(datasource, vault_creds: Optional[Dict[str, Any]] = None) -> Optional[Tuple[str, str]]:
    """Resolve S3 bucket and object key from datasource config, file_url, or vault credentials."""
    config = datasource.config if isinstance(getattr(datasource, "config", None), dict) else {}
    creds = (vault_creds or {}).get("credentials", {}) if isinstance(vault_creds, dict) else {}
    # Prefer explicit bucket_name + file_path from config
    bucket = config.get("bucket_name") or creds.get("bucket_name")
    key = config.get("file_path") or creds.get("file_path")
    if bucket and key:
        return (bucket.strip(), key.strip())
    # Parse from datasource file_url (e.g. https://bucket.s3.region.amazonaws.com/key or https://s3.region.amazonaws.com/bucket/key)
    file_url = getattr(datasource, "file_url", None) or (config.get("file_url") or config.get("fileUrl"))
    if not file_url or "s3" not in (file_url or "").lower():
        return None
    try:
        parsed = urlparse(file_url)
        path = (parsed.path or "").strip("/")
        path = unquote(path)
        hostname = (parsed.hostname or "").lower()
        # Virtual-hosted: https://bucket.s3.region.amazonaws.com/key
        if ".s3." in hostname and "amazonaws.com" in hostname:
            bucket_from_host = hostname.split(".s3.")[0]
            key_from_path = path if path else None
            if key_from_path and bucket_from_host:
                return (bucket_from_host, key_from_path)
            if bucket_from_host and not path:
                return None
        # Path-style: https://s3.region.amazonaws.com/bucket/key
        if "s3" in hostname and "amazonaws.com" in hostname and path:
            parts = path.split("/", 1)
            if len(parts) >= 2:
                return (parts[0], parts[1])
            if len(parts) == 1:
                return (parts[0], "")
    except Exception:
        pass
    return None


def _get_azure_container_and_blob(datasource, vault_creds: Optional[Dict[str, Any]] = None) -> Optional[Tuple[str, str]]:
    """Resolve Azure container and blob path from datasource config, file_url/location, or vault credentials."""
    config = datasource.config if isinstance(getattr(datasource, "config", None), dict) else {}
    creds = (vault_creds or {}).get("credentials", {}) if isinstance(vault_creds, dict) else {}
    container = config.get("container_name") or config.get("bucket_name") or creds.get("bucket_name")
    blob_path = config.get("file_path") or creds.get("file_path")
    if container and blob_path:
        # file_path from vault may be URL-encoded (e.g. Manned%20Voice%20Support%20-%20Documentation.docx)
        return (container.strip(), unquote(blob_path.strip()))
    # Vault uses "location" for Azure blob URL (e.g. https://account.blob.core.windows.net/container/blob)
    file_url = (
        getattr(datasource, "file_url", None)
        or (config.get("file_url") or config.get("fileUrl"))
        or (vault_creds.get("file_url") or vault_creds.get("fileUrl") or vault_creds.get("location"))
        if isinstance(vault_creds, dict) else None
    )
    if not file_url or "blob.core.windows.net" not in (file_url or "").lower():
        return None
    try:
        # https://account.blob.core.windows.net/container/path/to/blob
        parsed = urlparse(file_url)
        path = (parsed.path or "").strip("/")
        path = unquote(path)
        parts = path.split("/", 1)
        if len(parts) >= 2:
            return (parts[0], parts[1])
        if len(parts) == 1 and parts[0]:
            return (parts[0], "")
    except Exception:
        pass
    return None


def _get_gcp_bucket_and_blob(datasource, vault_creds: Optional[Dict[str, Any]] = None) -> Optional[Tuple[str, str]]:
    """Resolve GCP bucket and object path from datasource config, file_url/location, or vault credentials."""
    config = datasource.config if isinstance(getattr(datasource, "config", None), dict) else {}
    creds = (vault_creds or {}).get("credentials", {}) if isinstance(vault_creds, dict) else {}
    bucket = config.get("bucket_name") or creds.get("bucket_name")
    blob_path = config.get("file_path") or creds.get("file_path")
    if bucket and blob_path:
        # file_path from vault may be URL-encoded (e.g. test/logs%20shay%20v2%2030.txt)
        return (bucket.strip(), unquote(blob_path.strip()))
    # Prefer datasource/file_url then config then vault (vault uses "location" for GCP storage URL)
    file_url = (
        getattr(datasource, "file_url", None)
        or (config.get("file_url") or config.get("fileUrl"))
        or (vault_creds.get("file_url") or vault_creds.get("fileUrl") or vault_creds.get("location"))
        if isinstance(vault_creds, dict) else None
    )
    if not file_url:
        return None
    file_url = (file_url or "").strip()
    # gs://bucket/path/to/object
    if file_url.startswith("gs://"):
        try:
            rest = file_url[5:].lstrip("/")  # remove "gs://"
            rest = unquote(rest)
            parts = rest.split("/", 1)
            if len(parts) >= 2:
                return (parts[0], parts[1])
            if len(parts) == 1 and parts[0]:
                return (parts[0], "")
        except Exception:
            pass
        return None
    # https://storage.googleapis.com/bucket/path or https://storage.cloud.google.com/bucket/path
    if "storage.googleapis.com" in file_url or "storage.cloud.google.com" in file_url:
        try:
            parsed = urlparse(file_url)
            path = (parsed.path or "").strip("/")
            path = unquote(path)
            parts = path.split("/", 1)
            if len(parts) >= 2:
                return (parts[0], parts[1])
            if len(parts) == 1 and parts[0]:
                return (parts[0], "")
        except Exception:
            pass
    return None


async def download_from_s3_with_vault_credentials(
    datasource, vault_creds: Dict[str, Any], db: AsyncSession
) -> Optional[bytes]:
    """Download file from S3 using credentials stored in vault (datasource identified by request)."""
    bucket_key = _get_s3_bucket_and_key(datasource, vault_creds)
    if not bucket_key:
        return None
    bucket, key = bucket_key
    creds = vault_creds.get("credentials", vault_creds)
    access_key = creds.get("access_key") or creds.get("accessKeyId")
    secret_key = creds.get("secret_access_key") or creds.get("secretAccessKey")
    region = (creds.get("region") or creds.get("region_name") or "us-east-1").strip()
    if not access_key or not secret_key:
        return None
    try:
        import boto3
        client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        response = client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()
    except Exception as e:
        logger.warning(f"S3 download with vault credentials failed: {e}")
        return None


async def download_from_azure_with_vault_credentials(
    datasource, vault_creds: Dict[str, Any], db: AsyncSession
) -> Optional[bytes]:
    """Download file from Azure Blob using credentials stored in vault (connection string, or account key via accessToken/secret_access_key + location)."""
    container_blob = _get_azure_container_and_blob(datasource, vault_creds)
    if not container_blob:
        logger.warning("Azure download: could not resolve container/blob (check datasource/vault file_url, location, or container_name+file_path)")
        return None
    container, blob_path = container_blob
    blob_path_decoded = unquote(blob_path) if isinstance(blob_path, str) else blob_path
    creds = vault_creds.get("credentials", vault_creds)
    # Prefer connection string (access_key or connection_string in credentials)
    connection_string = creds.get("access_key") or creds.get("connection_string")
    if connection_string:
        try:
            from azure.storage.blob import BlobServiceClient
            blob_service = BlobServiceClient.from_connection_string(connection_string)
            blob_client = blob_service.get_blob_client(container=container, blob=blob_path_decoded)
            download_stream = blob_client.download_blob()
            return download_stream.readall()
        except Exception as e:
            logger.warning(f"Azure download with vault credentials failed: {e}", exc_info=True)
            return None
    # Vault structure uses accessToken (top level) or credentials.secret_access_key as account key; parse account from location
    account_key = vault_creds.get("accessToken") or creds.get("secret_access_key") or creds.get("secretAccessKey") or creds.get("secretKey")
    if not account_key:
        logger.warning("Azure download: vault missing connection_string or accessToken/secret_access_key")
        return None
    location = vault_creds.get("location") or vault_creds.get("file_url") or vault_creds.get("fileUrl") or getattr(datasource, "file_url", None)
    if not location or "blob.core.windows.net" not in location.lower():
        logger.warning("Azure download: need location (blob URL) to derive account name when using account key")
        return None
    try:
        parsed = urlparse(location)
        hostname = (parsed.hostname or "").strip().lower()
        if ".blob.core.windows.net" not in hostname:
            return None
        account_name = hostname.split(".blob.core.windows.net")[0] if ".blob.core.windows.net" in hostname else hostname.split(".")[0]
        account_url = f"https://{account_name}.blob.core.windows.net"
        from azure.storage.blob import BlobServiceClient
        from azure.core.credentials import AzureNamedKeyCredential
        credential = AzureNamedKeyCredential(name=account_name, key=account_key)
        blob_service = BlobServiceClient(account_url=account_url, credential=credential)
        blob_client = blob_service.get_blob_client(container=container, blob=blob_path_decoded)
        download_stream = blob_client.download_blob()
        return download_stream.readall()
    except Exception as e:
        logger.warning(f"Azure download with vault credentials failed: {e}", exc_info=True)
        return None


async def download_from_gcp_with_vault_credentials(
    datasource, vault_creds: Dict[str, Any], db: AsyncSession
) -> Optional[bytes]:
    """Download file from GCP Cloud Storage using credentials stored in vault (service_account_json)."""
    bucket_blob = _get_gcp_bucket_and_blob(datasource, vault_creds)
    if not bucket_blob:
        logger.warning("GCP download: could not resolve bucket/blob (check datasource/vault file_url or bucket_name+file_path)")
        return None
    bucket_name, blob_path = bucket_blob
    creds = vault_creds.get("credentials", vault_creds)
    # Support both snake_case and camelCase keys from vault
    service_account_json = creds.get("service_account_json") or creds.get("serviceAccountJson")
    project_id = creds.get("project_id") or creds.get("projectId")
    # If vault stores the raw service account object at top level (type=service_account)
    if not service_account_json and isinstance(vault_creds, dict) and vault_creds.get("type") == "service_account" and vault_creds.get("private_key"):
        service_account_json = vault_creds
    if not service_account_json:
        logger.warning("GCP download: vault credentials missing service_account_json / serviceAccountJson")
        return None
    # service_account_json may be base64-encoded JSON, plain JSON string, or already a dict (vault often stores base64)
    if isinstance(service_account_json, str):
        try:
            # Vault structure for GCP stores it as base64-encoded JSON
            decoded = base64.b64decode(service_account_json).decode("utf-8")
            sa_info = _json.loads(decoded)
        except Exception:
            try:
                sa_info = _json.loads(service_account_json)
            except Exception as e:
                logger.warning(f"GCP download: service_account_json is not valid JSON or base64 JSON: {e}")
                return None
    else:
        sa_info = service_account_json
    if not isinstance(sa_info, dict):
        return None
    try:
        from google.cloud import storage
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_info(sa_info)
        project = (project_id or sa_info.get("project_id") or "").strip() or None
        client = storage.Client(credentials=credentials, project=project)
        bucket = client.bucket(bucket_name)
        # blob_path may be URL-encoded when from vault credentials.file_path
        blob_path_decoded = unquote(blob_path) if isinstance(blob_path, str) else blob_path
        blob = bucket.blob(blob_path_decoded)
        return blob.download_as_bytes()
    except Exception as e:
        logger.warning(f"GCP download with vault credentials failed: {e}", exc_info=True)
        return None


async def handle_vault_integration(
    datasource_metadata: Dict[str, Any], 
    user_id: str,
    company_id: str,
    db: AsyncSession,
    required: bool = True
) -> Optional[str]:
    """
    Handle vault integration for datasource metadata
    
    Args:
        datasource_metadata: Complete datasource metadata dictionary (after cleanup)
        user_id: User ID
        company_id: Company ID
        db: Database session
        required: If True, vault failure will raise HTTPException. If False, returns None on failure.
        
    Returns:
        giggso_vault_id (UUID) if vault save successful, None if vault save failed and not required
        
    Raises:
        HTTPException: If vault integration fails and vault is required
    """
    if not datasource_metadata:
        return None
    
    # Generate vault unique ID
    vault_unique_id = vault_service.generate_vault_unique_id(str(user_id), "datasource")
    
    # Save entire metadata to vault (no transformation)
    saved_vault_id = await vault_service.save_to_vault(datasource_metadata, vault_unique_id)
    
    # If vault save failed, handle based on required flag
    if not saved_vault_id:
        if required:
            print(f"Vault save failed for ID: {vault_unique_id} - cannot proceed with datasource creation")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save sensitive data to vault. Datasource creation cannot proceed without secure storage."
            )
        else:
            print(f"Vault save failed for ID: {vault_unique_id} - continuing without vault integration")
            return None
    
    # Only create vault record if external vault save was successful
    try:
        # Create a shorter vault label that fits within 50 characters
        base_label = f"ds_{vault_unique_id[:8]}"  # Use first 8 chars of vault_unique_id
        vault_label = f"{base_label}_ok"  # External vault save successful
        
        vault_record = GiggsoVault(
            vault_unique_id=vault_unique_id,
            user_id=user_id,  # Store as UUID string
            vault_label=vault_label,
            vault_type="datasource_metadata",
            company_id=company_id,  # Store as UUID string
            created_by=user_id,  # Store as UUID string
            created_datetime=datetime.utcnow()
        )
        
        db.add(vault_record)
        # Flush to ensure the record is sent to the database before commit
        # This is important for Oracle and other databases that require explicit flushing
        await db.flush()
        await db.commit()
        print(f"Committed vault record to database: {vault_unique_id}")
        
        # Refresh to get the generated UUID
        await db.refresh(vault_record)
        
        # This ensures the commit persisted, especially important for Oracle databases
        verify_stmt = select(GiggsoVault).where(
            GiggsoVault.vault_unique_id == vault_unique_id
        )
        verify_result = await db.execute(verify_stmt)
        verified_record = verify_result.scalar_one_or_none()
        
        if not verified_record:            
            # Try to query by giggso_vault_id as well
            id_verify_stmt = select(GiggsoVault).where(
                GiggsoVault.giggso_vault_id == vault_record.giggso_vault_id
            )
            id_verify_result = await db.execute(id_verify_stmt)
            id_verified_record = id_verify_result.scalar_one_or_none()
            
            if id_verified_record:
                print(f"WARNING: Record found by giggso_vault_id but not by vault_unique_id")
                print(f"WARNING: Found record vault_unique_id: {id_verified_record.vault_unique_id}")
            else:
                print(f"ERROR: Record not found by giggso_vault_id either")
            
            raise Exception(f"Vault record commit verification failed: Record with vault_unique_id '{vault_unique_id}' not found after commit. This indicates the commit did not persist.")
        
        print(f"✅ Verified vault record exists in database: {vault_unique_id}, giggso_vault_id: {verified_record.giggso_vault_id}")
        print(f"Successfully stored credentials in vault. Vault ID: {vault_unique_id}")
        print(f"External vault save successful, created database record with ID: {vault_unique_id}")
        
        # Return both giggso_vault_id (UUID) and vault_unique_id (string)
        return {
            "giggso_vault_id": vault_record.giggso_vault_id,
            "vault_unique_id": vault_unique_id
        }
        
    except Exception as e:
        # Rollback the transaction if commit failed
        try:
            await db.rollback()
        except:
            pass  # Ignore rollback errors
        
        print(f"Failed to create vault record in database: {str(e)}")
        # If database creation fails, we can't proceed - this is a critical error
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Critical error: Failed to create vault record in database: {str(e)}"
        )


def generate_app_filename(datasource_data) -> str:
    """
    Generate a meaningful filename for app storage type based on connection_settings
    Format: "App Name - Account Name" or "App Name" as fallback
    """
    try:
        # Get connection_settings from config
        connection_settings = None
        if datasource_data.config and hasattr(datasource_data.config, 'connection_settings'):
            connection_settings = datasource_data.config.connection_settings
        elif datasource_data.config and isinstance(datasource_data.config, dict):
            connection_settings = datasource_data.config.get('connection_settings')
        
        if connection_settings and isinstance(connection_settings, dict):
            account = connection_settings.get('account', {})
            app = account.get('app', {}) if isinstance(account, dict) else {}
            
            # Extract app name and account name
            app_name = app.get('name', '') if isinstance(app, dict) else ''
            account_name = account.get('name', '') if isinstance(account, dict) else ''
            
            # Create filename based on available data
            if app_name and account_name:
                return f"{app_name} - {account_name}"
            elif app_name:
                return app_name
            elif account_name:
                return f"Account - {account_name}"
        else:
            # Fallback to app_type based naming ONLY if connection_settings is not present
            app_type = getattr(datasource_data, 'app_type', 'unknown')
            if app_type == 'google_drive':
                return "Google Drive"
            elif app_type == 'sharepoint':
                return "SharePoint"
            elif app_type == 'dropbox':
                return "Dropbox"
            elif app_type == 'oneDrive':
                return "OneDrive"
            else:
                return f"{app_type.title()} Datasource"
            
    except Exception as e:
        # Ultimate fallback
        app_type = getattr(datasource_data, 'app_type', 'unknown')
        return f"{app_type.title()} Datasource"

def generate_datasource_metadata(
    filename: str,
    storage_type: str,
    channel_id: str,
    workspace_id: str,
    user_id: str,
    file_size: int,
    file_type: str,
    provider: Optional[str] = None,
    app_type: Optional[str] = None,
    log_type: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    file_url: Optional[str] = None,
    is_embedding_required: bool = False
) -> Dict[str, Any]:
    """Generate metadata structure for datasource"""
    
    # Extract file format from filename or URL
    if filename:
        file_format = os.path.splitext(filename)[1].lstrip('.').lower()
        if not file_format:
            file_format = ""  # Default format
        
        # Generate unique filename with date pattern
        base_filename = os.path.splitext(filename)[0]
        current_date = datetime.now().strftime("%Y-%m-%d")
        unique_filename = f"{base_filename}_{current_date}.{file_format}"
    else:
        # For cloud storage without filename, use a default
        file_format = "txt"
        unique_filename = f"cloud_file_{datetime.now().strftime('%Y-%m-%d')}.{file_format}"
    
    # Generate giggs token (simple hash of current timestamp)
    timestamp = int(datetime.now().timestamp())
    giggs_token = f"{timestamp}JtmtSTJj6F"
    
    # Handle different storage types
    if storage_type == "database":
        # For database storage (MySQL, PostgreSQL, SQL Server, Oracle, MongoDB, DynamoDB, Redshift, Snowflake)
        # Provider contains the database type (mysql, postgresql, sqlserver, oracle, mongodb, dynamodb, redshift, snowflake)
        database_type = provider or "mysql"  # Default to mysql if not specified
        
        # Extract database credentials from config
        db_username = ""
        db_password = ""
        db_hostname = ""
        db_port = ""
        db_database_name = ""
        db_schema_name = ""
        db_table_name = ""
        db_collection_name = ""
        db_service_name = ""
        db_account_id = ""
        db_warehouse = ""
        db_region_name = ""
        db_access_key_id = ""
        db_secret_access_key = ""
        
        if config:
            db_username = config.get("username") or config.get("user") or ""
            db_password = config.get("password") or config.get("pass") or ""
            db_hostname = config.get("hostname") or config.get("host") or config.get("endpoint") or ""
            db_port = str(config.get("port", "")) if config.get("port") else ""
            db_database_name = config.get("databaseName") or config.get("database") or config.get("dbname") or ""
            db_schema_name = config.get("schemaName") or config.get("schema") or ""
            db_table_name = config.get("tableName") or ""
            db_collection_name = config.get("collectionName") or ""
            db_service_name = config.get("serviceName") or config.get("service") or ""
            db_account_id = config.get("accountId") or config.get("account") or ""
            db_warehouse = config.get("warehouse") or ""
            db_region_name = config.get("regionName") or config.get("region") or ""
            db_access_key_id = config.get("accessKeyId") or config.get("access_key_id") or ""
            db_secret_access_key = config.get("secretAccessKey") or config.get("secret_access_key") or ""
        
        metadata = {
            "accessKey": "",
            "accessKeyId": db_access_key_id if database_type == "dynamodb" else None,
            "accessToken": "",
            "accountId": db_account_id if database_type == "snowflake" else "",
            "app": [],
            "appType": None,
            "logType": log_type,
            "attachments": None,
            "azureKey": None,
            "botFlag": 1,
            "byodToken": None,
            "clientId": None,
            "clientSecret": None,
            "contextFileGiggsoVaultIds": None,
            "contextFiles": None,
            "cookies": [],
            "countFlg": 0,
            "credentials": config or {},
            "databaseName": db_database_name,
            "databaseType": database_type,  # mysql, postgresql, sqlserver, oracle, mongodb, dynamodb, redshift, snowflake
            "logFile": False,  # Databases are not log files
            "datasourcePrivacy": 0,
            "dataType": "referenceData",
            "disconnectDataSource": 0,
            "emailAttachmentFlg": 0,
            "emailValidate": 0,
            "embeddingsGenerated": 0,
            "embeddingStatus": 1 if is_embedding_required else 0,
            "emrClusterId": None,
            "enableDecrypt": 0,
            "endpoint": None,
            "errorCode": None,
            "errorMessage": None,
            "externalAppId": None,
            "fileDetails": None,
            "fileFormat": "",
            "fileNameAndPath": [],
            "fileOwnerId": None,
            "giggsoToken": giggs_token,
            "giggsoTokens": [],
            "googleDriveFiles": [],
            "workspaceChannelFlg": 1,
            "hostname": db_hostname,
            "indexColumnName": None,
            "indexColumnType": None,
            "isSummary": None,
            "isValidate": 1,
            "level": None,
            "localFileInfos": None,
            "localFiles": [],
            "location": "",
            "maxCount": 10,
            "minCount": 0,
            "monitoringId": None,
            "multiSelect": 0,
            "objectName": None,
            "objectNames": None,
            "password": db_password,
            "port": db_port,
            "recordProcessType": None,
            "regenerateEmbeddings": 0,
            "regionName": db_region_name if database_type == "dynamodb" else None,
            "userId": user_id,
            "restrictedURLs": None,
            "scheduleEmbeddingDelay": None,
            "scheduleEmbeddingDelayTime": 0,
            "scheduleEmbeddingFlg": 0,
            "scheduleEmbeddingTimeUnit": None,
            "schemaName": db_schema_name,
            "secretAccessKey": db_secret_access_key if database_type == "dynamodb" else None,
            "secretKey": None,
            "serviceName": db_service_name if database_type == "oracle" else None,
            "siteName": None,
            "size": file_size or 0,
            "startFrom": 0,
            "storageProvider": database_type,
            "storageType": "database",
            "tableId": "",
            "tableName": db_table_name if db_table_name else (db_collection_name if database_type == "mongodb" else ""),
            "tableNames": None,
            "threadId": 0,
            "topicLevelFlg": 1,
            "update": None,
            "url": None,
            "useCaseType": None,
            "username": db_username,
            "validatedId": None,
            "warehouse": db_warehouse if database_type == "snowflake" else "",
            "workspaceId": workspace_id,
            "channelId": channel_id,
            "filename": filename or "",
            "unique_filename": unique_filename if filename else ""
        }
        
        # Add collectionName for MongoDB
        if database_type == "mongodb" and db_collection_name:
            metadata["collectionName"] = db_collection_name
        
        return clean_metadata(metadata)
    
    elif storage_type == "cloud" and provider in ["aws", "azure", "oracle", "gcp"]:
        # For cloud storage (AWS, Azure, Oracle, GCP)
        access_key = ""
        access_token = ""
        location = ""
        local_files = []
        
        # Extract location based on provider
        if provider == "aws":
            if config and "bucket_name" in config and "file_path" in config:
                location = f"s3://{config['bucket_name']}/{config['file_path']}"
            elif config and "file_url" in config:
                # Extract S3 path from URL
                file_url = config.get("file_url", "")
                if "s3.amazonaws.com" in file_url:
                    # Convert S3 URL to s3:// format
                    location = file_url.replace("https://", "s3://").replace(".s3.amazonaws.com/", "/")
        elif provider == "azure":
            if config and "account_name" in config and "container_name" in config and "file_path" in config:
                location = f"https://{config['account_name']}.blob.core.windows.net/{config['container_name']}/{config['file_path']}"
            elif config and "file_url" in config:
                location = config.get("file_url", "")
        elif provider == "oracle":
            if config and "bucket_name" in config and "file_path" in config:
                location = f"https://objectstorage.{config.get('namespace', '')}.oraclecloud.com/n/{config.get('namespace', '')}/b/{config['bucket_name']}/o/{config['file_path']}"
            elif config and "file_url" in config:
                location = config.get("file_url", "")
        elif provider == "gcp":
            if config and "bucket_name" in config and "file_path" in config:
                location = f"gs://{config['bucket_name']}/{config['file_path']}"
            elif config and "file_url" in config:
                gcp_file_url = config.get("file_url", "")
                # Convert GCS URL to gs:// format if needed
                if "storage.googleapis.com" in gcp_file_url or "storage.cloud.google.com" in gcp_file_url:
                    # Extract bucket and path from URL
                    # Format: https://storage.googleapis.com/bucket-name/path/to/file
                    parts = gcp_file_url.replace("https://storage.googleapis.com/", "").replace("https://storage.cloud.google.com/", "").split("/", 1)
                    if len(parts) == 2:
                        location = f"gs://{parts[0]}/{parts[1]}"
                    elif len(parts) == 1:
                        location = f"gs://{parts[0]}"
                elif gcp_file_url.startswith("gs://"):
                    location = gcp_file_url
            elif file_url:
                # Use file_url directly if it's already in gs:// format
                if file_url.startswith("gs://"):
                    location = file_url
        
        # Extract credentials from config if available
        if config:
            if "access_key" in config:
                access_key = config["access_key"]
            if "secret_key" in config:
                access_token = config["secret_key"]
        
        metadata = {
            "accessKey": access_key,
            "accessKeyId": None,
            "accessToken": access_token,
            "accountId": "",
            "app": [],
            "appType": app_type,
            "logType": log_type,
            "attachments": None,
            "azureKey": None,
            "botFlag": 1,
            "byodToken": None,
            "clientId": None,
            "clientSecret": None,
            "contextFileGiggsoVaultIds": None,
            "contextFiles": None,
            "cookies": [],
            "countFlg": 0,
            "credentials": config or {},
            "databaseName": "",
            "databaseType": "cloud",
            "logFile": True,
            "datasourcePrivacy": 0,
            "dataType": "referenceData",
            "disconnectDataSource": 0,
            "emailAttachmentFlg": 0,
            "emailValidate": 0,
            "embeddingsGenerated": 0,
            "embeddingStatus": 1 if is_embedding_required else 0,
            "emrClusterId": None,
            "enableDecrypt": 0,
            "endpoint": None,
            "errorCode": None,
            "errorMessage": None,
            "externalAppId": None,
            "fileDetails": None,
            "fileFormat": file_format,
            "fileNameAndPath": [],
            "fileOwnerId": None,
            "giggsoToken": giggs_token,
            "giggsoTokens": [],
            "googleDriveFiles": [],
            "workspaceChannelFlg": 1,
            "hostname": None,
            "indexColumnName": None,
            "indexColumnType": None,
            "isSummary": None,
            "isValidate": 1,
            "level": None,
            "localFileInfos": None,
            "localFiles": local_files,
            "location": location,
            "maxCount": 10,
            "minCount": 0,
            "monitoringId": None,
            "multiSelect": 0,
            "objectName": None,
            "objectNames": None,
            "password": "",
            "port": None,
            "recordProcessType": None,
            "regenerateEmbeddings": 0,
            "regionName": None,
            "userId": user_id,
            "restrictedURLs": None,
            "scheduleEmbeddingDelay": None,
            "scheduleEmbeddingDelayTime": 0,
            "scheduleEmbeddingFlg": 0,
            "scheduleEmbeddingTimeUnit": None,
            "schemaName": "",
            "secretAccessKey": None,
            "secretKey": None,
            "serviceName": None,
            "siteName": None,
            "size": file_size,
            "startFrom": 0,
            "storageProvider": provider,
            "storageType": "cloud",
            "tableId": "",
            "tableName": "",
            "tableNames": None,
            "threadId": 0,
            "topicLevelFlg": 1,
            "update": None,
            "url": None,
            "useCaseType": None,
            "username": "",
            "validatedId": None,
            "warehouse": "",
            "workspaceId": workspace_id,
            "channelId": channel_id,
            "filename": filename,
            "unique_filename": unique_filename
        }
    else:
        # For local and app storage
        metadata = {
            "accessKey": "",
            "accessKeyId": None,
            "accessToken": "",
            "accountId": "",
            "app": [],
            "appType": app_type,
            "logType": log_type,
            "attachments": None,
            "azureKey": None,
            "botFlag": 1,
            "byodToken": None,
            "clientId": None,
            "clientSecret": None,
            "contextFileGiggsoVaultIds": None,
            "contextFiles": None,
            "cookies": [],
            "countFlg": 0,
            "credentials": config or {},
            "databaseName": "",
            "databaseType": storage_type,
            "logFile": True,
            "datasourcePrivacy": 0,
            "dataType": "referenceData",
            "disconnectDataSource": 0,
            "emailAttachmentFlg": 0,
            "emailValidate": 0,
            "embeddingsGenerated": 0,
            "embeddingStatus": 1 if is_embedding_required else 0,
            "emrClusterId": None,
            "enableDecrypt": 0,
            "endpoint": None,
            "errorCode": None,
            "errorMessage": None,
            "externalAppId": None,
            "fileDetails": None,
            "fileFormat": file_format,
            "fileNameAndPath": [],
            "fileOwnerId": None,
            "giggsoToken": giggs_token,
            "giggsoTokens": [],
            "googleDriveFiles": [],
            "workspaceChannelFlg": 1,
            "hostname": None,
            "indexColumnName": None,
            "indexColumnType": None,
            "isSummary": None,
            "isValidate": 1,
            "level": None,
            "localFileInfos": None,
            "localFiles": [unique_filename],
            "location": "",
            "maxCount": 10,
            "minCount": 0,
            "monitoringId": None,
            "multiSelect": 0,
            "objectName": None,
            "objectNames": None,
            "password": "",
            "port": None,
            "recordProcessType": None,
            "regenerateEmbeddings": 0,
            "regionName": None,
            "userId": user_id,
            "restrictedURLs": None,
            "scheduleEmbeddingDelay": None,
            "scheduleEmbeddingDelayTime": 0,
            "scheduleEmbeddingFlg": 0,
            "scheduleEmbeddingTimeUnit": None,
            "schemaName": "",
            "secretAccessKey": None,
            "secretKey": None,
            "serviceName": None,
            "siteName": None,
            "size": file_size,
            "startFrom": 0,
            "storageProvider": provider or "",
            "storageType": storage_type,
            "tableId": "",
            "tableName": "",
            "tableNames": None,
            "threadId": 0,
            "topicLevelFlg": 1,
            "update": None,
            "url": None,
            "useCaseType": None,
            "username": "",
            "validatedId": None,
            "warehouse": "",
            "workspaceId": workspace_id,
            "channelId": channel_id,
            "filename": filename,
            "unique_filename": unique_filename
        }
    
    # Clean the metadata to remove null/empty/default values
    return clean_metadata(metadata)


@router.post("/", response_model=DatasourceResponse)
async def create_datasource(
    datasource_data: DatasourceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Create a single datasource"""
    user = await get_current_user_required(request)
    
    # Get channel
    stmt = select(Channel).where(Channel.id == datasource_data.channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )
    
    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )
    
    # Check for duplicate datasource in the same channel
    existing_datasource_stmt = select(Datasource).where(
        and_(
            Datasource.name == datasource_data.name,
            Datasource.channel_id == datasource_data.channel_id
        )
    )
    existing_datasource_result = await db.execute(existing_datasource_stmt)
    existing_datasource = existing_datasource_result.scalars().first()
    
    if existing_datasource:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Datasource with name '{datasource_data.name}' already exists in this channel"
        )
    
    # Validate storage type specific requirements
    if datasource_data.storage_type == "cloud" and not datasource_data.provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider is required for cloud storage type"
        )
    
    if datasource_data.storage_type == "app" and not datasource_data.app_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="App type is required for app storage type"
        )
    
    # Auto-generate name from filename if not provided
    datasource_name = datasource_data.name
    if not datasource_name:
        # Get filename (either provided or extract from URL)
        filename = datasource_data.filename
        if not filename and datasource_data.file_url:
            # Extract filename from URL
            filename = os.path.basename(datasource_data.file_url.split('?')[0])  # Remove query params
            if not filename:
                filename = "cloud_file"  # Fallback name
        
        if filename:
            # Remove extension and replace underscores/hyphens with spaces
            base_filename = os.path.splitext(filename)[0]
            datasource_name = base_filename.replace('_', ' ').replace('-', ' ').title()
        else:
            datasource_name = "Cloud Datasource"  # Default name
    
    # Get filename (either provided or extract from URL/location) - MUST be done BEFORE generating metadata
    filename = datasource_data.filename
    if not filename:
        if datasource_data.file_url:
            filename = os.path.basename(datasource_data.file_url.split('?')[0])  # Remove query params
            if not filename:
                filename = "cloud_file"  # Fallback name
        elif datasource_data.location:
            # Extract filename from location (gs://, s3://, https://, etc.)
            location = datasource_data.location
            # Remove protocol prefix (gs://, s3://, https://, etc.)
            if "://" in location:
                path_part = location.split("://", 1)[1]
                # Remove bucket name (first part before /)
                if "/" in path_part:
                    file_path = "/".join(path_part.split("/")[1:])
                    filename = os.path.basename(file_path) if file_path else None
                else:
                    filename = None
            else:
                filename = os.path.basename(location)
            
            if not filename:
                filename = "cloud_file"  # Fallback name
        elif datasource_data.storage_type == "database":
            provider = datasource_data.provider or "database"
            db_name = datasource_data.name or f"{provider}_connection"
            filename = "".join(c for c in db_name if c.isalnum() or c in (' ', '-', '_')).strip()
            if not filename:
                filename = f"{provider}_datasource"
            if not filename.endswith(('.db', '.sql', '.csv')):
                filename = f"{filename}.db"
        else:
            filename = datasource_data.name or "datasource"
            filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_')).strip()
            if not filename:
                filename = "datasource"
    
    # Generate metadata structure (now with extracted filename)
    metadata = generate_datasource_metadata(
        filename=filename,  # Use extracted filename instead of datasource_data.filename
        storage_type=datasource_data.storage_type,
        channel_id=datasource_data.channel_id,
        workspace_id=str(channel.workspace_id),
        user_id=str(user.id),
        file_size=datasource_data.file_size,
        file_type=datasource_data.file_type,
        provider=datasource_data.provider,
        app_type=datasource_data.app_type,
        log_type=datasource_data.log_type,
        config=datasource_data.config.dict() if datasource_data.config else None,
        file_url=datasource_data.file_url,
        is_embedding_required=datasource_data.is_embedding_required or False
    )
    
    # Clean the metadata to remove null, empty, and default values
    cleaned_metadata = clean_metadata(metadata)
    
    # Enhance metadata for database, cloud, and app storage types (all require vault integration)
    if datasource_data.storage_type in ["database", "cloud", "app"]:
        
        enhanced_metadata = await enhance_datasource_metadata(
            existing_metadata=cleaned_metadata,
            storage_type=datasource_data.storage_type,
            provider=datasource_data.provider,
            config=datasource_data.config.dict() if datasource_data.config else None,
            app_type=datasource_data.app_type,
            db=db,
            channel_id=datasource_data.channel_id,
            location=datasource_data.location,
            accessToken=datasource_data.accessToken
        )
        # Use enhanced metadata for vault storage
        cleaned_metadata = enhanced_metadata
    
    # Handle vault integration for datasource metadata
    vault_unique_id = None
    if cleaned_metadata:
        # For cloud and database datasources (which contain sensitive credentials), vault integration is required
        # For local file uploads, vault integration is optional
        vault_required = datasource_data.storage_type in ["cloud", "database", "app"]
        
        try:
            vault_result = await handle_vault_integration(
                datasource_metadata=cleaned_metadata,
                user_id=str(user.id),
                company_id=str(channel.company_id),
                db=db,
                required=vault_required
            )
            vault_unique_id = vault_result["vault_unique_id"] if vault_result else None
            giggso_vault_id = vault_result["giggso_vault_id"] if vault_result else None
        except HTTPException as e:
            # Re-raise HTTPException for required vault integration
            raise e
        except Exception as e:
            # For unexpected errors, log and fail
            print(f"Unexpected error during vault integration: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to integrate with vault service"
            )
    
    # Store cleaned metadata directly in database (with vault integration for backup)
    final_metadata = cleaned_metadata.copy()
    if vault_unique_id:
        final_metadata["vault_unique_id"] = str(vault_unique_id)
    
    # Create datasource (without redundant workspace_id and company_id)
    datasource = Datasource(
        id=str(uuid.uuid4()),
        name=datasource_name,
        filename=filename,
        storage_type=datasource_data.storage_type,
        provider=datasource_data.provider,
        app_type=datasource_data.app_type,
        log_type=datasource_data.log_type,
        config=datasource_data.config.dict() if datasource_data.config else None,
        datasource_metadata=final_metadata,
        giggso_vault_id=giggso_vault_id,  # Store vault ID in dedicated column
        file_size=datasource_data.file_size,
        file_type=datasource_data.file_type,
        file_url=datasource_data.file_url,
        channel_id=datasource_data.channel_id,
        added_by=user.id,
        is_embedding_required=datasource_data.is_embedding_required or False,
        embedding_status=1 if (datasource_data.is_embedding_required or False) else 0
    )
    
    db.add(datasource)
    # Flush to ensure the record is sent to the database before commit
    # This is important for Oracle and other databases that require explicit flushing
    await db.flush()
    await db.commit()
    await db.refresh(datasource)
    
    # Verify vault record still exists after datasource creation
    # This ensures the vault record commit persisted and wasn't rolled back
    if vault_unique_id:
        vault_verify_stmt = select(GiggsoVault).where(
            GiggsoVault.vault_unique_id == vault_unique_id
        )
        vault_verify_result = await db.execute(vault_verify_stmt)
        vault_verified = vault_verify_result.scalar_one_or_none()
        
        if not vault_verified:
            print(f"ERROR: Vault record {vault_unique_id} not found after datasource creation!")
            print(f"ERROR: This indicates the vault record commit was rolled back or did not persist")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Critical error: Vault record was lost after datasource creation. Vault ID: {vault_unique_id}"
            )
        else:
            print(f"✅ Verified vault record still exists after datasource creation: {vault_unique_id}")
    
    # Log success message with vault ID if available
    if vault_unique_id:
        logger.debug(f"Successfully stored datasource in backend. Vault ID: {vault_unique_id}")
    
    # Trigger embedding if required
    if datasource.is_embedding_required and vault_unique_id and datasource.giggso_vault_id:
        try:
            # Get vault_unique_id from gg_vault table
            vault_stmt = select(GiggsoVault).where(GiggsoVault.giggso_vault_id == datasource.giggso_vault_id)
            vault_result = await db.execute(vault_stmt)
            vault_record = vault_result.scalar_one_or_none()
            
            if vault_record and vault_record.vault_unique_id:
                # Determine embedd_type based on file type, storage type, and provider
                from app.services.ml_service import get_embedd_type_from_file_type
                embedd_type = get_embedd_type_from_file_type(
                    file_type=datasource.file_type,
                    storage_type=datasource.storage_type,
                    provider=datasource.provider
                )
                
                # Extract table_name from datasource metadata (for database datasources)
                table_name = None
                if datasource.datasource_metadata and isinstance(datasource.datasource_metadata, dict):
                    table_name = datasource.datasource_metadata.get("tableName")
                
                # Get completed embeddings for this channel
                embedded_vault_unique_ids = await get_completed_embeddings_by_channel(str(datasource.channel_id), db)
                
                # Extract JWT token from Authorization header
                auth_header = request.headers.get("Authorization")
                jwt_token = None
                if auth_header and auth_header.startswith("Bearer "):
                    jwt_token = auth_header.split(" ")[1]
                
                logger.info(f"Triggering embedding for datasource {datasource.id}, embedd_type: {embedd_type}")
                
                # Fetch OpenAI vault token (gpt_token) for company to send to ML API
                openai_vault_token = await get_openai_vault_token_for_company(db, str(user.company_id))
                # Call ML API to request embedding processing
                table_names = extract_table_names_from_datasources([datasource]) if table_name is None else None
                result = await ml_service.request_embedding_processing(
                    vault_unique_ids=[vault_record.vault_unique_id],
                    user_id=str(user.id),
                    company_id=str(user.company_id),
                    channel_id=str(datasource.channel_id),
                    embedded_vault_unique_ids=embedded_vault_unique_ids,
                    jwt_token=jwt_token,
                    embedd_type=embedd_type,
                    table_name=table_name,
                    table_names=table_names,
                    openai_vault_token=openai_vault_token
                )
                
                # Emit socket event based on ML API response
                socket_service = get_socket_service()
                if socket_service.is_socket_connected():
                    ml_status = 2 if result.get("success") else 3
                    socket_event_data = {
                        "type": 16,
                        "data": {
                            "channelId": str(datasource.channel_id),
                            "status": ml_status,
                            "datasourceId": str(datasource.id)
                        }
                    }
                    socket_service.emit("datasource_event", socket_event_data)
            else:
                logger.warning(f"Vault record not found for giggso_vault_id: {datasource.giggso_vault_id}")
        except Exception as e:
            logger.error(f"Error triggering embedding for datasource {datasource.id}: {e}", exc_info=True)
    
    return DatasourceResponse(
        id=str(datasource.id),
        name=datasource.name,
        filename=datasource.filename,
        storage_type=datasource.storage_type,
        provider=datasource.provider,
        app_type=datasource.app_type,
        config=datasource.config,
        datasource_metadata=sanitize_datasource_metadata(datasource.datasource_metadata),
        giggso_vault_id=str(datasource.giggso_vault_id) if datasource.giggso_vault_id else None,
        file_size=datasource.file_size,
        file_type=datasource.file_type,
        file_url=datasource.file_url,
        channel_id=str(datasource.channel_id),
        workspace_id=str(channel.workspace_id),
        company_id=str(channel.company_id),
        added_by=str(datasource.added_by),
        is_active=datasource.is_active,
        is_connected=datasource.is_connected,
        is_processed=datasource.is_processed,
        processing_status=datasource.processing_status,
        error_message=datasource.error_message,
        last_processed_at=datasource.last_processed_at,
        processing_time=datasource.processing_time,
        record_count=datasource.record_count,
        is_embedding_required=datasource.is_embedding_required,
        embedding_status=datasource.embedding_status,
        created_at=datasource.created_at,
        updated_at=datasource.updated_at
    )


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    isValidationRequired: bool = Form(True),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """Upload a single file to the system"""
    user = await get_current_user_required(request)
    
    # Validate file
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File name is required"
        )
    
    # Get company information
    company_stmt = select(Company).where(Company.id == user.company_id)
    company_result = await db.execute(company_stmt)
    company = company_result.scalar_one_or_none()
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    # Get file storage service
    storage_service = get_file_storage_service()
    
    try:
        # Read file content
        file_content = await file.read()
        
        # Validate file content before uploading (if validation is required)
        if isValidationRequired and not validate_file_content(file_content, file.filename):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File validation failed - no valid section headers found"
            )
        
        # Generate structured path
        file_extension = os.path.splitext(file.filename)[1]
        base_filename = os.path.splitext(file.filename)[0]
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        # Use structured path for datasource files
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
        
        return FileUploadResponse(
            filename=file.filename,
            storage_path=upload_result["storage_path"],
            file_url=upload_result["file_url"],
            file_size=len(file_content),
            file_type=file.content_type or "application/octet-stream",
            provider=upload_result["provider"]
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )


@router.post("/upload/bulk", response_model=FileUploadBulkResponse)
async def upload_files_bulk(
    files: List[UploadFile] = File(...),
    isValidationRequired: bool = Form(True),
    kind: Optional[str] = Form(None),
    workspace_id: Optional[str] = Form(None),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """Upload multiple files to the system.

    Additive Aryx integration: pass kind="aryx" together with workspace_id
    (a Shay workspace UUID already bridged to Aryx) to ALSO start Aryx
    knowledge-graph ingestion for each successfully-uploaded file, using the
    same bytes already read for the storage upload — no re-read, no
    duplicate network transfer of the file. This runs ALONGSIDE the existing
    storage upload below, never instead of it: the storage-upload result is
    always computed and appended first, exactly as before; the Aryx result
    (or a per-file error) is then attached as an additional aryx_ingestion
    key on that same entry.

    Omitting kind (or any value other than "aryx") is byte-for-byte
    identical to the endpoint's behavior before this change — no existing
    caller is affected.
    """
    user = await get_current_user_required(request)

    # Get company information
    company_stmt = select(Company).where(Company.id == user.company_id)
    company_result = await db.execute(company_stmt)
    company = company_result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # --- Additive Aryx setup — resolved once for the whole batch, only when
    # kind="aryx" was actually requested. Any failure here becomes a per-file
    # aryx_ingestion.error below rather than a hard failure of the upload
    # (which must still succeed for callers not opting into this feature).
    aryx_workspace_id: Optional[int] = None
    aryx_setup_error: Optional[str] = None
    if kind == "aryx":
        if not workspace_id:
            aryx_setup_error = "workspace_id is required when kind='aryx'"
        else:
            try:
                target_workspace = await _get_workspace_or_404(db, workspace_id)
                await require_active_workspace_role(db, user.id, uuid.UUID(str(target_workspace.id)))
                aryx_workspace_id = await _resolve_aryx_workspace_id_for_datasources(workspace_id)
            except HTTPException as exc:
                aryx_setup_error = str(exc.detail)

    # Get file storage service
    storage_service = get_file_storage_service()

    uploaded_files = []
    failed_files = []

    for file in files:
        try:
            # Validate file
            if not file.filename:
                failed_files.append({
                    "filename": "unknown",
                    "error": "File name is required"
                })
                continue

            # Read file content
            file_content = await file.read()

            # Validate file content before uploading (if validation is required)
            if isValidationRequired and not validate_file_content(file_content, file.filename):
                failed_files.append({
                    "filename": file.filename,
                    "error": "File validation failed - no valid section headers found"
                })
                continue

            # Generate structured path
            file_extension = os.path.splitext(file.filename)[1]
            base_filename = os.path.splitext(file.filename)[0]
            current_date = datetime.now().strftime("%Y-%m-%d")

            # Use structured path for datasource files
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

            uploaded_files.append(uploaded_entry)

        except Exception as e:
            failed_files.append({
                "filename": file.filename,
                "error": str(e)
            })

    return FileUploadBulkResponse(
        uploaded_files=uploaded_files,
        failed_files=failed_files,
        total_uploaded=len(uploaded_files),
        total_failed=len(failed_files)
    )


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
):
    """Create a datasource from uploaded file"""
    user = await get_current_user_required(request)
    
    # Parse datasource_metadata if provided
    parsed_metadata = None
    if datasource_metadata:
        try:
            import json
            parsed_metadata = json.loads(datasource_metadata)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON in datasource_metadata"
            )
    
    # Get channel
    stmt = select(Channel).where(Channel.id == channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )
    
    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )
    
    # Check for duplicate datasource in the same channel (if name provided)
    if name:
        existing_datasource_stmt = select(Datasource).where(
            and_(
                Datasource.name == name,
                Datasource.channel_id == channel_id
            )
        )
        existing_datasource_result = await db.execute(existing_datasource_stmt)
        existing_datasource = existing_datasource_result.scalars().first()
        
        if existing_datasource:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Datasource with name '{name}' already exists in this channel"
            )
    
    # Validate file
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File name is required"
        )
    
    # Get company information
    company_stmt = select(Company).where(Company.id == user.company_id)
    company_result = await db.execute(company_stmt)
    company = company_result.scalar_one_or_none()
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    # Get file storage service
    storage_service = get_file_storage_service()
    
    try:
        # Read file content
        file_content = await file.read()
        
        # Validate file content before uploading (if validation is required)
        if isValidationRequired and not validate_file_content(file_content, file.filename):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File validation failed - no valid section headers found"
            )
        
        # Generate structured path
        file_extension = os.path.splitext(file.filename)[1]
        base_filename = os.path.splitext(file.filename)[0]
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        # Use structured path for datasource files
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
        datasource_name = name
        if not datasource_name:
            # Remove extension and replace underscores/hyphens with spaces
            base_filename = os.path.splitext(file.filename)[0]
            datasource_name = base_filename.replace('_', ' ').replace('-', ' ').title()
        
        # Determine storage type and provider from upload result
        storage_type = "cloud" if upload_result["provider"] in ["aws", "azure", "oracle"] else "local"
        provider = upload_result["provider"]
        
        # Build config with provider-specific details
        config = {
            "file_path": upload_result["storage_path"],
            "original_filename": file.filename
        }
        
        # Add provider-specific configuration details
        if provider == "aws":
            config.update({
                "bucket_name": upload_result.get("bucket_name"),
                "region": upload_result.get("region")
            })
        elif provider == "azure":
            config.update({
                "container_name": upload_result.get("container_name"),
                "account_name": upload_result.get("account_name")
            })
        elif provider == "oracle":
            config.update({
                "bucket_name": upload_result.get("bucket_name"),
                "namespace": upload_result.get("namespace"),
                "compartment_id": upload_result.get("compartment_id")
            })
        
        # Generate metadata structure
        metadata = generate_datasource_metadata(
            filename=file.filename,
            storage_type=storage_type,
            channel_id=channel_id,
            workspace_id=str(channel.workspace_id),
            user_id=str(user.id),
            file_size=len(file_content),
            file_type=file.content_type or "application/octet-stream",
            provider=provider,
            app_type=None,
            log_type=log_type,
            config=config,
            file_url=upload_result["file_url"]
        )
        
        # Clean the metadata to remove null, empty, and default values
        cleaned_metadata = clean_metadata(metadata)
        
        # Enhance metadata with vault-specific fields AFTER cleaning
        from app.services.vault_data_builder import enhance_datasource_metadata
        
        enhanced_metadata = await enhance_datasource_metadata(
            existing_metadata=cleaned_metadata,
            storage_type=storage_type,
            provider=provider,
            config=config,
            db=db,
            channel_id=channel_id
        )
        
        # Handle vault integration for datasource metadata
        vault_unique_id = None
        if enhanced_metadata:
            # Vault integration is REQUIRED for ALL datasource types to ensure data security
            # This includes both cloud datasources (with sensitive credentials) and local files
            vault_required = True
            
            try:
                vault_result = await handle_vault_integration(
                    datasource_metadata=enhanced_metadata,
                    user_id=str(user.id),
                    company_id=str(channel.company_id),
                    db=db,
                    required=vault_required
                )
                vault_unique_id = vault_result["vault_unique_id"] if vault_result else None
                giggso_vault_id = vault_result["giggso_vault_id"] if vault_result else None
            except HTTPException as e:
                # Re-raise HTTPException for required vault integration
                raise e
            except Exception as e:
                # For unexpected errors, log and fail
                print(f"Unexpected error during vault integration: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to integrate with vault service"
                )
        
        # Store enhanced metadata directly in database (with vault integration for backup)
        final_metadata = enhanced_metadata.copy()
        if vault_unique_id:
            final_metadata["vault_unique_id"] = str(vault_unique_id)
        
        # Create datasource
        datasource = Datasource(
            id=str(uuid.uuid4()),
            name=datasource_name,
            filename=file.filename,
            storage_type=storage_type,
            provider=provider,
            app_type=None,
            log_type=log_type,
            config=config,
            datasource_metadata=final_metadata,
            file_size=len(file_content),
            file_type=file.content_type or "application/octet-stream",
            file_url=upload_result["file_url"],
            channel_id=channel_id,
            added_by=user.id,
            giggso_vault_id=giggso_vault_id  # Set the vault ID
        )
        
        db.add(datasource)
        await db.commit()
        await db.refresh(datasource)
        
        return DatasourceResponse(
            id=str(datasource.id),
            name=datasource.name,
            filename=datasource.filename,
            storage_type=datasource.storage_type,
            provider=datasource.provider,
            app_type=datasource.app_type,
            config=datasource.config,
            datasource_metadata=sanitize_datasource_metadata(datasource.datasource_metadata),
            giggso_vault_id=str(datasource.giggso_vault_id) if datasource.giggso_vault_id else None,
            file_size=datasource.file_size,
            file_type=datasource.file_type,
            file_url=datasource.file_url,
            channel_id=str(datasource.channel_id),
            workspace_id=str(channel.workspace_id),
            company_id=str(channel.company_id),
            added_by=str(datasource.added_by),
            is_active=datasource.is_active,
            is_connected=datasource.is_connected,
            is_processed=datasource.is_processed,
            processing_status=datasource.processing_status,
            error_message=datasource.error_message,
            last_processed_at=datasource.last_processed_at,
            processing_time=datasource.processing_time,
            record_count=datasource.record_count,
            created_at=datasource.created_at,
            updated_at=datasource.updated_at
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create datasource from upload: {str(e)}"
        )


@router.post("/from-upload/bulk", response_model=DatasourceBulkResponse)
async def create_datasources_from_upload_bulk(
    datasources_data: DatasourceFromUploadBulk,
    files: List[UploadFile] = File(...),
    isValidationRequired: bool = Form(True),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """Create multiple datasources from uploaded files"""
    user = await get_current_user_required(request)
    
    created_datasources = []
    failed_datasources = []
    
    # Validate that number of files matches number of datasources
    if len(files) != len(datasources_data.datasources):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Number of files must match number of datasources"
        )
    
    # Get company information
    company_stmt = select(Company).where(Company.id == user.company_id)
    company_result = await db.execute(company_stmt)
    company = company_result.scalar_one_or_none()
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    # Get file storage service
    storage_service = get_file_storage_service()
    
    for i, (datasource_data, file) in enumerate(zip(datasources_data.datasources, files)):
        try:
            # Get channel
            stmt = select(Channel).where(Channel.id == datasource_data.channel_id)
            result = await db.execute(stmt)
            channel = result.scalar_one_or_none()
            
            if not channel:
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "Channel not found"
                })
                continue
            
            # Check permissions
            if not channel.is_accessible_by_user(user.company_id, user.role):
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "Access denied to channel"
                })
                continue
            
            # Check for duplicate datasource in the same channel
            existing_datasource_stmt = select(Datasource).where(
                and_(
                    Datasource.name == datasource_data.name,
                    Datasource.channel_id == datasource_data.channel_id
                )
            )
            existing_datasource_result = await db.execute(existing_datasource_stmt)
            existing_datasource = existing_datasource_result.scalars().first()
            
            if existing_datasource:
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": f"Datasource with name '{datasource_data.name}' already exists in this channel"
                })
                continue
            
            # Validate file
            if not file.filename:
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "File name is required"
                })
                continue
            
            # Read file content
            file_content = await file.read()
            
            # Validate file content before uploading (if validation is required)
            if isValidationRequired and not validate_file_content(file_content, file.filename):
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "File validation failed - no valid section headers found"
                })
                continue
            
            # Generate structured path
            file_extension = os.path.splitext(file.filename)[1]
            base_filename = os.path.splitext(file.filename)[0]
            current_date = datetime.now().strftime("%Y-%m-%d")
            
            # Use structured path for datasource files
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
                # Remove extension and replace underscores/hyphens with spaces
                base_filename = os.path.splitext(file.filename)[0]
                datasource_name = base_filename.replace('_', ' ').replace('-', ' ').title()
            
            # Determine storage type and provider from upload result
            storage_type = "cloud" if upload_result["provider"] in ["aws", "azure", "oracle"] else "local"
            provider = upload_result["provider"]
            
            # Build config with provider-specific details
            config = {
                "file_path": upload_result["storage_path"],
                "original_filename": file.filename
            }
            
            # Add provider-specific configuration details
            if provider == "aws":
                config.update({
                    "bucket_name": upload_result.get("bucket_name"),
                    "region": upload_result.get("region")
                })
            elif provider == "azure":
                config.update({
                    "container_name": upload_result.get("container_name"),
                    "account_name": upload_result.get("account_name")
                })
            elif provider == "oracle":
                config.update({
                    "bucket_name": upload_result.get("bucket_name"),
                    "namespace": upload_result.get("namespace"),
                    "compartment_id": upload_result.get("compartment_id")
                })
            
            # Generate metadata structure
            metadata = generate_datasource_metadata(
                filename=file.filename,
                storage_type=storage_type,
                channel_id=datasource_data.channel_id,
                workspace_id=str(channel.workspace_id),
                user_id=str(user.id),
                file_size=len(file_content),
                file_type=file.content_type or "application/octet-stream",
                provider=provider,
                app_type=None,
                log_type=datasource_data.log_type,
                config=config,
                file_url=upload_result["file_url"]
            )
            
            # Clean the metadata to remove null, empty, and default values
            cleaned_metadata = clean_metadata(metadata)
            
            # Enhance metadata with vault-specific fields AFTER cleaning
            from app.services.vault_data_builder import enhance_datasource_metadata
            
            enhanced_metadata = await enhance_datasource_metadata(
                existing_metadata=cleaned_metadata,
                storage_type=storage_type,
                provider=provider,
                config=config,
                db=db,
                channel_id=datasource_data.channel_id
            )
            
            # Handle vault integration for datasource metadata
            vault_unique_id = None
            if enhanced_metadata:
                # Vault integration is REQUIRED for ALL datasource types to ensure data security
                # This includes both cloud datasources (with sensitive credentials) and local files
                vault_required = True
                
                try:
                    vault_result = await handle_vault_integration(
                        datasource_metadata=enhanced_metadata,
                        user_id=str(user.id),
                        company_id=str(channel.company_id),
                        db=db,
                        required=vault_required
                    )
                    vault_unique_id = vault_result["vault_unique_id"] if vault_result else None
                    giggso_vault_id = vault_result["giggso_vault_id"] if vault_result else None
                    
                    # If vault integration failed, we cannot proceed with datasource creation
                    if not vault_unique_id:
                        failed_datasources.append({
                            "name": datasource_data.name,
                            "error": "Vault integration failed. Cannot create datasource without secure storage."
                        })
                        continue
                        
                except HTTPException as e:
                    # Vault integration failed - add to failed datasources
                    failed_datasources.append({
                        "name": datasource_data.name,
                        "error": f"Vault integration failed: {e.detail}"
                    })
                    continue
                except Exception as e:
                    # For unexpected errors, log and fail
                    print(f"Unexpected error during vault integration: {str(e)}")
                    failed_datasources.append({
                        "name": datasource_data.name,
                        "error": "Failed to integrate with vault service"
                    })
                    continue
            
            # Store enhanced metadata directly in database (with vault integration for backup)
            final_metadata = enhanced_metadata.copy()
            if vault_unique_id:
                final_metadata["vault_unique_id"] = str(vault_unique_id)
            
            # Create datasource
            datasource = Datasource(
                id=str(uuid.uuid4()),
                name=datasource_name,
                filename=file.filename,
                storage_type=storage_type,
                provider=provider,
                app_type=datasource_data.app_type,
                log_type=datasource_data.log_type,
                config=config,
                datasource_metadata=final_metadata,
                giggso_vault_id=giggso_vault_id,  # Store vault ID in dedicated column
                file_size=len(file_content),
                file_type=file.content_type or "application/octet-stream",
                file_url=upload_result["file_url"],
                channel_id=datasource_data.channel_id,
                added_by=user.id
            )
            
            db.add(datasource)
            await db.commit()
            await db.refresh(datasource)
            
            created_datasources.append({
                "id": str(datasource.id),
                "name": datasource.name,
                "filename": datasource.filename,
                "storage_type": datasource.storage_type,
                "provider": datasource.provider,
                "app_type": datasource.app_type,
                "config": datasource.config,
                "datasource_metadata": sanitize_datasource_metadata(datasource.datasource_metadata),
                "giggso_vault_id": str(datasource.giggso_vault_id) if datasource.giggso_vault_id else None,
                "file_size": datasource.file_size,
                "file_type": datasource.file_type,
                "file_url": datasource.file_url,
                "channel_id": str(datasource.channel_id),
                "workspace_id": str(channel.workspace_id),
                "company_id": str(channel.company_id),
                "added_by": str(datasource.added_by),
                "is_active": datasource.is_active,
                "is_connected": datasource.is_connected,
                "is_processed": datasource.is_processed,
                "processing_status": datasource.processing_status,
                "error_message": datasource.error_message,
                "last_processed_at": datasource.last_processed_at,
                "processing_time": datasource.processing_time,
                "record_count": datasource.record_count,
                "is_embedding_required": datasource.is_embedding_required,
                "embedding_status": datasource.embedding_status,
                "created_at": datasource.created_at,
                "updated_at": datasource.updated_at
            })
            
        except Exception as e:
            failed_datasources.append({
                "name": datasource_data.name,
                "error": str(e)
            })
    
    return DatasourceBulkResponse(
        created_datasources=created_datasources,
        failed_datasources=failed_datasources,
        total_created=len(created_datasources),
        total_failed=len(failed_datasources)
    )


@router.post("/bulk", response_model=DatasourceBulkResponse)
async def create_datasources_bulk(
    bulk_data: DatasourceBulkCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Create multiple datasources in bulk"""
    user = await get_current_user_required(request)
    
    created_datasources = []
    failed_datasources = []
    
    for datasource_data in bulk_data.datasources:
        try:
            # Get channel
            stmt = select(Channel).where(Channel.id == datasource_data.channel_id)
            result = await db.execute(stmt)
            channel = result.scalar_one_or_none()
            
            if not channel:
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "Channel not found"
                })
                continue
            
            # Check permissions
            if not channel.is_accessible_by_user(user.company_id, user.role):
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "Access denied to channel"
                })
                continue
            
            # Check for duplicate datasource in the same channel
            existing_datasource_stmt = select(Datasource).where(
                and_(
                    Datasource.name == datasource_data.name,
                    Datasource.channel_id == datasource_data.channel_id
                )
            )
            existing_datasource_result = await db.execute(existing_datasource_stmt)
            existing_datasource = existing_datasource_result.scalars().first()
            
            if existing_datasource:
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": f"Datasource with name '{datasource_data.name}' already exists in this channel"
                })
                continue
            
            # Validate storage type specific requirements
            if datasource_data.storage_type == "cloud" and not datasource_data.provider:
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "Provider is required for cloud storage type"
                })
                continue
            
            if datasource_data.storage_type == "app" and not datasource_data.app_type:
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "App type is required for app storage type"
                })
                continue
            # Handle app_provider mapping for app storage
            if datasource_data.storage_type == "app":
                # Map app_provider to provider for app storage
                if datasource_data.app_provider and not datasource_data.provider:
                    datasource_data.provider = datasource_data.app_provider
                elif not datasource_data.app_provider and not datasource_data.provider:
                    failed_datasources.append({
                        "name": datasource_data.name,
                        "error": "app_provider is required for app storage type"
                    })
                    continue

            # Auto-generate name from filename if not provided
            datasource_name = datasource_data.name
            if not datasource_name:
                # Get filename (either provided or extract from URL)
                filename = datasource_data.filename
                if not filename and datasource_data.file_url:
                    # Extract filename from URL
                    filename = os.path.basename(datasource_data.file_url.split('?')[0])  # Remove query params
                    if not filename:
                        filename = "cloud_file"  # Fallback name
                
                if filename:
                    # Remove extension and replace underscores/hyphens with spaces
                    base_filename = os.path.splitext(filename)[0]
                    datasource_name = base_filename.replace('_', ' ').replace('-', ' ').title()
                else:
                    # Handle app storage type with no filename
                    if datasource_data.storage_type == "app":
                        app_type = getattr(datasource_data, 'app_type', 'unknown')
                        datasource_name = f"{app_type.title()} Datasource"
                    else:
                        datasource_name = "Cloud Datasource"  # Default name
            filename = datasource_data.filename
            if not filename and datasource_data.file_url:
                # Extract filename from URL
                filename = os.path.basename(datasource_data.file_url.split('?')[0])  # Remove query params
                if not filename:
                    filename = "cloud_file"  # Fallback name
            
            # Handle app storage type with no filename - generate meaningful filename first
            if not filename and datasource_data.storage_type == "app":
                # Try to create a meaningful filename from connection_settings
                filename = generate_app_filename(datasource_data)
            # Generate metadata structure
            metadata = generate_datasource_metadata(
                filename=filename or "app_file",
                storage_type=datasource_data.storage_type,
                channel_id=datasource_data.channel_id,
                workspace_id=str(channel.workspace_id),
                user_id=str(user.id),
                file_size=datasource_data.file_size or 0,  # Fallback for app storage
                file_type=datasource_data.file_type or "application/octet-stream",  # Fallback for app storage
                provider=datasource_data.provider,
                app_type=datasource_data.app_type,
                log_type=datasource_data.log_type,
                config=datasource_data.config.dict() if datasource_data.config else None,
                file_url=datasource_data.file_url,
                is_embedding_required=datasource_data.is_embedding_required or False
            )
            
            # Get filename (either provided or extract from URL)
            filename = datasource_data.filename
            if not filename and datasource_data.file_url:
                # Extract filename from URL
                filename = os.path.basename(datasource_data.file_url.split('?')[0])  # Remove query params
                if not filename:
                    filename = "cloud_file"  # Fallback name
                                       
            # Handle app storage type with no filename
            if not filename and datasource_data.storage_type == "app":
                # Try to create a meaningful filename from connection_settings
                filename = generate_app_filename(datasource_data)
            # Clean the metadata to remove null, empty, and default values
            cleaned_metadata = clean_metadata(metadata)
            
            # Enhance metadata with vault-specific fields AFTER cleaning
            from app.services.vault_data_builder import enhance_datasource_metadata
            
            enhanced_metadata = await enhance_datasource_metadata(
                existing_metadata=cleaned_metadata,
                storage_type=datasource_data.storage_type,
                provider=datasource_data.provider,
                config=datasource_data.config.dict() if datasource_data.config else None,
                app_type=getattr(datasource_data, 'app_type', None),
                db=db,
                channel_id=datasource_data.channel_id,
                location=getattr(datasource_data, 'location', None),
                accessToken=getattr(datasource_data, 'accessToken', None)
            )
            
            # Handle vault integration for datasource metadata
            vault_unique_id = None
            if enhanced_metadata:
                # Vault integration is REQUIRED for ALL datasource types to ensure data security
                # This includes both cloud datasources (with sensitive credentials) and local files
                vault_required = True
                
                try:
                    vault_result = await handle_vault_integration(
                        datasource_metadata=enhanced_metadata,
                        user_id=str(user.id),
                        company_id=str(channel.company_id),
                        db=db,
                        required=vault_required
                    )
                    vault_unique_id = vault_result["vault_unique_id"] if vault_result else None
                    giggso_vault_id = vault_result["giggso_vault_id"] if vault_result else None
                    
                    # If vault integration failed, we cannot proceed with datasource creation
                    if not vault_unique_id:
                        failed_datasources.append({
                            "name": datasource_data.name,
                            "error": "Vault integration failed. Cannot create datasource without secure storage."
                        })
                        continue
                        
                except HTTPException as e:
                    # Vault integration failed - add to failed datasources
                    failed_datasources.append({
                        "name": datasource_data.name,
                        "error": f"Vault integration failed: {e.detail}"
                    })
                    continue
                except Exception as e:
                    # For unexpected errors, log and fail
                    print(f"Unexpected error during vault integration: {str(e)}")
                    failed_datasources.append({
                        "name": datasource_data.name,
                        "error": "Failed to integrate with vault service"
                    })
                    continue
            
            # Store enhanced metadata directly in database (with vault integration for backup)
            final_metadata = enhanced_metadata.copy()
            if vault_unique_id:
                final_metadata["vault_unique_id"] = str(vault_unique_id)
            
            # Create datasource
            datasource = Datasource(
                id=str(uuid.uuid4()),
                name=datasource_name,
                filename=filename,
                storage_type=datasource_data.storage_type,
                provider=datasource_data.provider,
                app_type=datasource_data.app_type,
                log_type=datasource_data.log_type,
                config=datasource_data.config.dict() if datasource_data.config else None,
                datasource_metadata=final_metadata,
                giggso_vault_id=giggso_vault_id,  # Store vault ID in dedicated column
                file_size=datasource_data.file_size or 0,  # Fallback for app storage
                file_type=datasource_data.file_type or "application/octet-stream",  # Fallback for app storage
                file_url=datasource_data.file_url,
                channel_id=datasource_data.channel_id,
                added_by=user.id,
                is_embedding_required=datasource_data.is_embedding_required or False,
                embedding_status=1 if (datasource_data.is_embedding_required or False) else 0
            )
            
            db.add(datasource)
            await db.commit()
            await db.refresh(datasource)
            
            created_datasources.append({
                "id": str(datasource.id),
                "name": datasource.name,
                "filename": datasource.filename,
                "storage_type": datasource.storage_type,
                "provider": datasource.provider,
                "app_type": datasource.app_type,
                "config": datasource.config,
                "datasource_metadata": sanitize_datasource_metadata(datasource.datasource_metadata),
                "giggso_vault_id": str(datasource.giggso_vault_id) if datasource.giggso_vault_id else None,
                "file_size": datasource.file_size,
                "file_type": datasource.file_type,
                "file_url": datasource.file_url,
                "channel_id": str(datasource.channel_id),
                "workspace_id": str(channel.workspace_id),
                "company_id": str(channel.company_id),
                "added_by": str(datasource.added_by),
                "is_active": datasource.is_active,
                "is_connected": datasource.is_connected,
                "is_processed": datasource.is_processed,
                "processing_status": datasource.processing_status,
                "error_message": datasource.error_message,
                "last_processed_at": datasource.last_processed_at,
                "processing_time": datasource.processing_time,
                "record_count": datasource.record_count,
                "is_embedding_required": datasource.is_embedding_required,
                "embedding_status": datasource.embedding_status,
                "created_at": datasource.created_at,
                "updated_at": datasource.updated_at,
                # Additive: None for every datasource without an aryx.discovery_id
                # in its metadata — existing (non-Aryx) callers see no change.
                "aryx_ingestion_status": await _aryx_ingestion_status_for(datasource.datasource_metadata),
            })

        except Exception as e:
            failed_datasources.append({
                "name": datasource_data.name,
                "error": str(e)
            })

    # Check if any datasources require embedding processing
    embedding_required_datasources = [
        ds for ds in created_datasources
        if ds.get("is_embedding_required", False)
    ]
    
    if embedding_required_datasources:
        # Extract giggso_vault_ids and get corresponding vault_unique_ids
        giggso_vault_ids = []
        for ds in embedding_required_datasources:
            if ds.get("giggso_vault_id"):
                giggso_vault_ids.append(ds["giggso_vault_id"])
        
        vault_unique_ids = []  # Initialize vault_unique_ids outside the if block
        vault_records = []  # Initialize vault_records outside the if block
        
        if giggso_vault_ids:
            # Query gg_vault table to get vault_unique_ids
            stmt = select(GiggsoVault).where(GiggsoVault.giggso_vault_id.in_(giggso_vault_ids))
            result = await db.execute(stmt)
            vault_records = result.scalars().all()
            
            # Extract vault_unique_ids
            vault_unique_ids = [record.vault_unique_id for record in vault_records if record.vault_unique_id]
            
            logger.info("=" * 80)
            logger.info("🔍 VAULT ID CONVERSION")
            logger.info("=" * 80)
            logger.info(f"📊 Found {len(embedding_required_datasources)} datasources requiring embedding")
            logger.info(f"🔑 giggso_vault_ids: {giggso_vault_ids}")
            logger.info(f"📦 vault_unique_ids: {vault_unique_ids}")
            logger.info("=" * 80)
        
        if vault_unique_ids:
            # Get channel_id from the first datasource that requires embedding
            first_datasource = embedding_required_datasources[0]
            channel_id = first_datasource.get("channel_id")
            
            # Classify each datasource by embedd_type and group them
            from app.services.ml_service import get_embedd_type_from_file_type
            
            # Create a mapping: datasource -> embedd_type -> giggso_vault_id -> vault_unique_id
            # First, create a mapping from giggso_vault_id to vault_unique_id
            vault_id_mapping = {}
            for ds in embedding_required_datasources:
                giggso_vault_id = ds.get("giggso_vault_id")
                if giggso_vault_id:
                    # Find corresponding vault_unique_id
                    for record in vault_records:
                        # Convert both to strings for comparison to handle UUID vs string mismatches
                        if str(record.giggso_vault_id) == str(giggso_vault_id):
                            vault_id_mapping[str(giggso_vault_id)] = record.vault_unique_id
                            break
            
            logger.debug(f"🔍 Vault ID Mapping created: {len(vault_id_mapping)} mappings")
            logger.debug(f"   Mapping keys: {list(vault_id_mapping.keys())}")
            logger.debug(f"   Vault records count: {len(vault_records)}")
            logger.debug(f"   Embedding required datasources count: {len(embedding_required_datasources)}")
            
            # Group datasources by embedd_type
            textual_datasources = []
            tabular_datasources = []
            
            for ds in embedding_required_datasources:
                # Determine embedd_type for this datasource
                embedd_type = get_embedd_type_from_file_type(
                    file_type=ds.get("file_type"),
                    storage_type=ds.get("storage_type"),
                    provider=ds.get("provider")
                )
                
                # Extract base type (remove provider suffix if any)
                base_type = embedd_type.split("_")[0]
                
                # Group by base type
                if base_type == "tabular":
                    tabular_datasources.append({
                        "datasource": ds,
                        "giggso_vault_id": ds.get("giggso_vault_id"),
                        "embedd_type": embedd_type
                    })
                else:
                    # Default to textual for unknown types or textual files
                    textual_datasources.append({
                        "datasource": ds,
                        "giggso_vault_id": ds.get("giggso_vault_id"),
                        "embedd_type": embedd_type
                    })
            
            logger.info("=" * 80)
            logger.info("📊 FILE CLASSIFICATION FOR BULK EMBEDDING")
            logger.info("=" * 80)
            logger.info(f"📄 Textual files: {len(textual_datasources)}")
            logger.info(f"📊 Tabular files: {len(tabular_datasources)}")
            logger.info("=" * 80)
            
            # Get completed embeddings for this channel
            embedded_vault_unique_ids = await get_completed_embeddings_by_channel(channel_id, db)

            # Extract JWT token from Authorization header
            auth_header = request.headers.get("Authorization")
            jwt_token = None
            if auth_header and auth_header.startswith("Bearer "):
                jwt_token = auth_header.split(" ")[1]
            
            # Fetch OpenAI vault token (gpt_token) for company to send to ML API
            openai_vault_token = await get_openai_vault_token_for_company(db, str(user.company_id))
            
            # Process textual files group
            if textual_datasources:
                textual_vault_unique_ids = [
                    vault_id_mapping[str(ds["giggso_vault_id"])]
                    for ds in textual_datasources
                    if ds["giggso_vault_id"] and str(ds["giggso_vault_id"]) in vault_id_mapping
                ]
                
                logger.debug(f"📄 Textual vault_unique_ids: {textual_vault_unique_ids} (from {len(textual_datasources)} textual datasources)")
                
                if textual_vault_unique_ids:
                    textual_ds_list = [ds["datasource"] for ds in textual_datasources]
                    
                    # Extract table_name from first textual datasource metadata that has it
                    table_name = None
                    for ds in textual_datasources:
                        metadata = ds["datasource"].get("datasource_metadata")
                        if metadata and isinstance(metadata, dict):
                            table_name = metadata.get("tableName")
                            if table_name:
                                break
                    
                    try:
                        table_names = extract_table_names_from_datasources(textual_ds_list) if len(textual_ds_list) > 1 else None
                        logger.info(f"🚀 Calling ML API for {len(textual_vault_unique_ids)} textual file(s) with embedd_type='textual'")
                        
                        result = await ml_service.request_embedding_processing(
                            vault_unique_ids=textual_vault_unique_ids,
                            user_id=str(user.id),
                            company_id=str(user.company_id),
                            channel_id=channel_id,
                            embedded_vault_unique_ids=embedded_vault_unique_ids,
                            jwt_token=jwt_token,
                            embedd_type="textual",
                            table_name=table_name,
                            table_names=table_names,
                            openai_vault_token=openai_vault_token
                        )
                        
                        # Emit socket event based on ML API response
                        socket_service = get_socket_service()
                        if socket_service.is_socket_connected():
                            ml_status = 2 if result.get("success") else 3  # 2 = success, 3 = failure
                            
                            # Emit socket event for each textual datasource
                            for ds in textual_datasources:
                                datasource_id = ds["datasource"].get("id")
                                if datasource_id:
                                    socket_event_data = {
                                        "type": 16,
                                        "data": {
                                            "channelId": channel_id,
                                            "status": ml_status,
                                            "datasourceId": datasource_id
                                        }
                                    }
                                    
                                    try:
                                        await socket_service.emit("shay_realtime", socket_event_data)
                                        logger.info(f"✅ Emitted socket event for textual datasource {datasource_id}: status={ml_status}")
                                    except Exception as socket_error:
                                        logger.error(f"❌ Failed to emit socket event for datasource {datasource_id}: {socket_error}")
                        
                        if result.get("success"):
                            logger.info(f"✅ ML API call successful for {len(textual_vault_unique_ids)} textual file(s)")
                        else:
                            logger.error(f"❌ ML API call failed for textual files: {result.get('message', 'Unknown error')}")
                            
                    except Exception as e:
                        logger.error(f"❌ Error calling ML API for textual files: {e}")
                        
                        # Emit socket event for failure
                        socket_service = get_socket_service()
                        if socket_service.is_socket_connected():
                            for ds in textual_datasources:
                                datasource_id = ds["datasource"].get("id")
                                if datasource_id:
                                    try:
                                        await socket_service.emit("shay_realtime", {
                                            "type": 16,
                                            "data": {
                                                "channelId": channel_id,
                                                "status": 3,  # failure
                                                "datasourceId": datasource_id
                                            }
                                        })
                                    except Exception:
                                        pass
            
            # Process tabular files group
            if tabular_datasources:
                tabular_vault_unique_ids = [
                    vault_id_mapping[str(ds["giggso_vault_id"])]
                    for ds in tabular_datasources
                    if ds["giggso_vault_id"] and str(ds["giggso_vault_id"]) in vault_id_mapping
                ]
                
                logger.debug(f"📊 Tabular vault_unique_ids: {tabular_vault_unique_ids} (from {len(tabular_datasources)} tabular datasources)")
                
                if tabular_vault_unique_ids:
                    tabular_ds_list = [ds["datasource"] for ds in tabular_datasources]
                    
                    # Extract table_name from first tabular datasource metadata that has it
                    table_name = None
                    for ds in tabular_datasources:
                        metadata = ds["datasource"].get("datasource_metadata")
                        if metadata and isinstance(metadata, dict):
                            table_name = metadata.get("tableName")
                            if table_name:
                                break
                    
                    try:
                        table_names = extract_table_names_from_datasources(tabular_ds_list) if len(tabular_ds_list) > 1 else None
                        logger.info(f"🚀 Calling ML API for {len(tabular_vault_unique_ids)} tabular file(s) with embedd_type='tabular'")
                        
                        result = await ml_service.request_embedding_processing(
                            vault_unique_ids=tabular_vault_unique_ids,
                            user_id=str(user.id),
                            company_id=str(user.company_id),
                            channel_id=channel_id,
                            embedded_vault_unique_ids=embedded_vault_unique_ids,
                            jwt_token=jwt_token,
                            embedd_type="tabular",
                            table_name=table_name,
                            table_names=table_names,
                            openai_vault_token=openai_vault_token
                        )
                        
                        # Emit socket event based on ML API response
                        socket_service = get_socket_service()
                        if socket_service.is_socket_connected():
                            ml_status = 2 if result.get("success") else 3  # 2 = success, 3 = failure
                            
                            # Emit socket event for each tabular datasource
                            for ds in tabular_datasources:
                                datasource_id = ds["datasource"].get("id")
                                if datasource_id:
                                    socket_event_data = {
                                        "type": 16,
                                        "data": {
                                            "channelId": channel_id,
                                            "status": ml_status,
                                            "datasourceId": datasource_id
                                        }
                                    }
                                    
                                    try:
                                        await socket_service.emit("shay_realtime", socket_event_data)
                                        logger.info(f"✅ Emitted socket event for tabular datasource {datasource_id}: status={ml_status}")
                                    except Exception as socket_error:
                                        logger.error(f"❌ Failed to emit socket event for datasource {datasource_id}: {socket_error}")
                        
                        if result.get("success"):
                            logger.info(f"✅ ML API call successful for {len(tabular_vault_unique_ids)} tabular file(s)")
                        else:
                            logger.error(f"❌ ML API call failed for tabular files: {result.get('message', 'Unknown error')}")
                            
                    except Exception as e:
                        logger.error(f"❌ Error calling ML API for tabular files: {e}")
                        
                        # Emit socket event for failure
                        socket_service = get_socket_service()
                        if socket_service.is_socket_connected():
                            for ds in tabular_datasources:
                                datasource_id = ds["datasource"].get("id")
                                if datasource_id:
                                    try:
                                        await socket_service.emit("shay_realtime", {
                                            "type": 16,
                                            "data": {
                                                "channelId": channel_id,
                                                "status": 3,  # failure
                                                "datasourceId": datasource_id
                                            }
                                        })
                                    except Exception:
                                        pass
    
    logger.info(f"📊 [INTERNAL-BULK] Completed - Created: {len(created_datasources)}, Failed: {len(failed_datasources)}")
    if failed_datasources:
        logger.warning(f"⚠️ [INTERNAL-BULK] Failed datasources: {failed_datasources}")
    
    return DatasourceBulkResponse(
        created_datasources=created_datasources,
        failed_datasources=failed_datasources,
        total_created=len(created_datasources),
        total_failed=len(failed_datasources)
    )


def verify_internal_api_key(request: Request) -> None:
    """Verify internal API key from request headers"""
    api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is required. Provide X-API-Key header or Bearer token."
        )
    
    expected_api_key = settings.ML_API_KEY
    if not expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key not configured. Set ML_API_KEY environment variable."
        )
    
    if api_key != expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )


@router.post("/internal/bulk", response_model=DatasourceBulkResponse)
async def create_datasources_bulk_internal(
    bulk_data: DatasourceBulkCreateInternal,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Create multiple datasources in bulk (internal API - thread-level, API key authentication)"""
    logger.info("=" * 80)
    logger.info("🚀 [INTERNAL-BULK] Starting internal bulk API call")
    logger.info(f"📦 Received {len(bulk_data.datasources)} datasource(s)")
    logger.info("=" * 80)
    
    try:
        # Verify API key
        verify_internal_api_key(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying API key: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"API key verification failed: {str(e)}")

    created_datasources = []
    failed_datasources = []
    skipped_datasources = []  # Duplicates (same filename in same thread) - not failures

    try:
        for datasource_data in bulk_data.datasources:
            try:
                # Convert thread_id to UUID
                try:
                    thread_uuid = uuid.UUID(datasource_data.thread_id)
                except (ValueError, TypeError) as e:
                    failed_datasources.append({"name": datasource_data.name or "Unknown", "error": f"Invalid thread_id format: {datasource_data.thread_id}"})
                    continue

                # Get thread
                thread_stmt = select(Thread).where(Thread.id == thread_uuid)
                thread_result = await db.execute(thread_stmt)
                thread = thread_result.scalar_one_or_none()

                if not thread:
                    failed_datasources.append({"name": datasource_data.name or "Unknown", "error": "Thread not found"})
                    continue

                # Get channel from thread
                channel_stmt = select(Channel).where(Channel.id == thread.channel_id)
                channel_result = await db.execute(channel_stmt)
                channel = channel_result.scalar_one_or_none()

                if not channel:
                    failed_datasources.append({"name": datasource_data.name or "Unknown", "error": "Channel not found for thread"})
                    continue

                # Get user from channel's connected email account (AppAccount)
                # For email attachments, use the user who connected the email account to the channel
                user = None
                try:
                    from app.models.app_account import AppAccount
                    # Get the active email AppAccount for this channel
                    app_account_stmt = select(AppAccount).where(
                        and_(
                            AppAccount.channel_id == thread.channel_id,
                            AppAccount.api_key == "email",
                            AppAccount.is_active == True
                        )
                    ).order_by(AppAccount.created_at.desc()).limit(1)
                    app_account_result = await db.execute(app_account_stmt)
                    app_account = app_account_result.scalar_one_or_none()
                    
                    if app_account and app_account.connected_by:
                        # Use the user who connected the email account
                        user_stmt = select(User).where(User.id == app_account.connected_by)
                        user_result = await db.execute(user_stmt)
                        user = user_result.scalar_one_or_none()
                        logger.info(f"✅ Using connected email account user for attachment: user_id={app_account.connected_by}")
                except Exception as e:
                    logger.warning(f"Could not get user from AppAccount: {str(e)}")
                
                # Fallback: Get first active user from channel's company if no AppAccount found
                if not user:
                    user_stmt = select(User).where(and_(User.company_id == channel.company_id, User.is_active == True)).limit(1)
                    user_result = await db.execute(user_stmt)
                    user = user_result.scalar_one_or_none()
                    logger.info(f"⚠️ Using fallback: first active user from company for attachment")

                if not user:
                    failed_datasources.append({"name": datasource_data.name or "Unknown", "error": "No active user found for channel's company"})
                    continue

                # Resolve filename early (needed for duplicate check when name not provided)
                filename = datasource_data.filename
                if not filename and datasource_data.file_url:
                    filename = os.path.basename(datasource_data.file_url.split('?')[0])  # Remove query params
                    if not filename:
                        filename = "cloud_file"  # Fallback name

                # Skip .ics attachments in internal/bulk API (not supported)
                # Check both explicit filename and file_url path so we never process .ics from either source
                fn_lower = (filename or "").strip().lower()
                is_ics = fn_lower.endswith(".ics")
                if not is_ics and datasource_data.file_url:
                    path_part = datasource_data.file_url.split("?")[0].rstrip("/")
                    if path_part:
                        last_segment = path_part.split("/")[-1]
                        is_ics = last_segment.lower().endswith(".ics")
                if is_ics:
                    skip_name = datasource_data.name or filename or "Unknown"
                    skipped_datasources.append({
                        "name": skip_name,
                        "reason": "unsupported_extension",
                        "message": "Attachments with .ics extension are not supported in bulk API",
                    })
                    continue  # Do not create datasource for .ics attachments

                # Auto-generate name from filename if not provided (same logic used when creating)
                datasource_name = datasource_data.name
                if not datasource_name:
                    if filename:
                        base_filename = os.path.splitext(filename)[0]
                        datasource_name = base_filename.replace('_', ' ').replace('-', ' ').title()
                    else:
                        if getattr(datasource_data, 'storage_type', None) == "app":
                            app_type = getattr(datasource_data, 'app_type', 'unknown')
                            datasource_name = f"{app_type.title()} Datasource"
                        else:
                            datasource_name = "Cloud Datasource"  # Default name

                # Check for duplicate ONLY within the same thread: use (filename, thread_id) for precision.
                # Same filename in SAME thread = duplicate (skip). Same filename in DIFFERENT thread = process.
                # Filename is the actual file identity; name can collide across different files (e.g. Report.pdf vs Report.docx).
                filename_for_check = (filename or "").strip() or None
                duplicate_check_key = filename_for_check if filename_for_check else datasource_name
                if duplicate_check_key:
                    # Match by filename when available (more precise); fallback to name for app-type datasources
                    if filename_for_check:
                        duplicate_stmt = select(Datasource).where(
                            and_(
                                Datasource.filename == filename_for_check,
                                Datasource.channel_id == thread.channel_id,
                                Datasource.datasource_metadata.isnot(None),
                                Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
                                Datasource.datasource_metadata.op("->>")(literal("thread_id", type_=String())) == literal(str(thread_uuid), type_=String())
                            )
                        ).limit(1)
                    else:
                        duplicate_stmt = select(Datasource).where(
                            and_(
                                Datasource.name == datasource_name,
                                Datasource.channel_id == thread.channel_id,
                                Datasource.datasource_metadata.isnot(None),
                                Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
                                Datasource.datasource_metadata.op("->>")(literal("thread_id", type_=String())) == literal(str(thread_uuid), type_=String())
                            )
                        ).limit(1)
                    duplicate_result = await db.execute(duplicate_stmt)
                    existing_datasource = duplicate_result.scalar_one_or_none()

                    if existing_datasource:
                        # Duplicate (same file in same thread) - skip, do not count as failed
                        logger.info(
                            f"⏭️ Skipping duplicate datasource: {datasource_name} (filename={filename_for_check or 'N/A'} "
                            f"already exists in thread {thread_uuid})"
                        )
                        skipped_datasources.append({
                            "name": datasource_name,
                            "reason": "already_exists",
                            "message": f"Datasource '{datasource_name}' already exists in this thread (skipped)"
                        })
                        continue
                
                # Get filename (either provided or extract from URL)
                filename = datasource_data.filename
                if not filename and datasource_data.file_url:
                    # Extract filename from URL
                    filename = os.path.basename(datasource_data.file_url.split('?')[0])  # Remove query params
                    if not filename:
                        filename = "cloud_file"  # Fallback name
                
                # Handle app storage type with no filename - generate meaningful filename first
                if not filename and datasource_data.storage_type == "app":
                    # Try to create a meaningful filename from connection_settings
                    filename = generate_app_filename(datasource_data)
                
                # Generate metadata structure (use thread's channel_id)
                metadata = generate_datasource_metadata(
                    filename=filename or "app_file",
                    storage_type=datasource_data.storage_type,
                    channel_id=str(thread.channel_id),
                    workspace_id=str(thread.workspace_id),
                    user_id=str(user.id),
                    file_size=datasource_data.file_size or 0,  # Fallback for app storage
                    file_type=datasource_data.file_type or "application/octet-stream",  # Fallback for app storage
                    provider=datasource_data.provider,
                    app_type=datasource_data.app_type,
                    log_type=datasource_data.log_type,
                    config=datasource_data.config.dict() if datasource_data.config else None,
                    file_url=datasource_data.file_url,
                    is_embedding_required=datasource_data.is_embedding_required or False
                )
                
                # Add thread_id to metadata for thread-level association
                metadata["thread_id"] = str(thread_uuid)
                # Ensure company_id is in metadata for embedding processing
                if "company_id" not in metadata:
                    metadata["company_id"] = str(channel.company_id)
                
                # Clean the metadata to remove null, empty, and default values
                cleaned_metadata = clean_metadata(metadata)
                
                # For internal/bulk API: vault_storage_type and file_path for email attachments (S3 or local)
                vault_storage_type = datasource_data.storage_type
                file_path = None
                if datasource_data.storage_type == "local" and datasource_data.file_url:
                    # Email backend sent storage_type=local (FILE_UPLOAD_ENV=local): extract path from file_url for vault
                    try:
                        from urllib.parse import urlparse, unquote
                        parsed_url = urlparse(datasource_data.file_url)
                        file_path = unquote(parsed_url.path.lstrip("/"))
                        logger.info(f"[INTERNAL-BULK] Local storage: file_path from file_url: {file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to extract file_path from local file_url: {e}")
                elif datasource_data.storage_type == "cloud" and datasource_data.provider == "s3" and datasource_data.file_url:
                    # Extract file_path from S3 URL (e.g., https://bucket.s3.amazonaws.com/path/to/file -> path/to/file)
                    try:
                        from urllib.parse import urlparse, unquote
                        parsed_url = urlparse(datasource_data.file_url)
                        # Get the path and remove leading slash
                        file_path = parsed_url.path.lstrip('/')
                        # URL decode the path to handle special characters
                        file_path = unquote(file_path)
                        # If URL contains bucket name in hostname (e.g., bucket.s3.amazonaws.com), remove it from path if present
                        if parsed_url.hostname and '.s3.' in parsed_url.hostname:
                            bucket_name = parsed_url.hostname.split('.')[0]
                            # Remove bucket name prefix if it exists in the path
                            if file_path.startswith(bucket_name + '/'):
                                file_path = file_path[len(bucket_name) + 1:]
                        # Treat as local storage for vault purposes
                        vault_storage_type = "local"
                        logger.info(f"[INTERNAL-BULK] Treating cloud S3 file as local storage. Extracted file_path: {file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to extract file_path from file_url: {e}")
                        # Continue with original storage_type if extraction fails
                
                # Enhance metadata with vault-specific fields AFTER cleaning
                enhanced_metadata = await enhance_datasource_metadata(
                    existing_metadata=cleaned_metadata,
                    storage_type=vault_storage_type,  # Use vault_storage_type (may be "local" for email attachments)
                    provider=datasource_data.provider,
                    config=datasource_data.config.dict() if datasource_data.config else None,
                    app_type=getattr(datasource_data, 'app_type', None),
                    db=db,
                    channel_id=str(thread.channel_id),
                    location=getattr(datasource_data, 'location', None),
                    accessToken=getattr(datasource_data, 'accessToken', None)
                )
                if enhanced_metadata:
                    enhanced_metadata["thread_id"] = str(thread_uuid)
                    enhanced_metadata["company_id"] = str(channel.company_id)  # Ensure company_id is in enhanced metadata
                    
                    # For email attachments treated as local storage: ensure databaseType matches storageType
                    if vault_storage_type == "local":
                        enhanced_metadata["databaseType"] = "local"
                        # Add file_path to credentials if extracted from file_url (for S3/local storage)
                        if file_path:
                            if "credentials" not in enhanced_metadata:
                                enhanced_metadata["credentials"] = {}
                            enhanced_metadata["credentials"]["file_path"] = file_path
                        # Add file_url so Giggso-AI-ML can fetch directly (FILE_UPLOAD_ENV=local: LOCAL_FILES_URL + path)
                        if datasource_data.file_url:
                            enhanced_metadata["file_url"] = datasource_data.file_url

                # Handle vault integration for datasource metadata
                vault_unique_id = None
                giggso_vault_id = None
                if enhanced_metadata:
                    vault_required = True
                    try:
                        vault_result = await handle_vault_integration(
                            datasource_metadata=enhanced_metadata,
                            user_id=str(user.id),
                            company_id=str(channel.company_id),
                            db=db,
                            required=vault_required
                        )
                        vault_unique_id = vault_result["vault_unique_id"] if vault_result else None
                        giggso_vault_id = vault_result["giggso_vault_id"] if vault_result else None

                        if not vault_unique_id:
                            failed_datasources.append({"name": datasource_data.name or "Unknown", "error": "Vault integration failed. Cannot create datasource without secure storage."})
                            continue
                    except HTTPException as e:
                        failed_datasources.append({"name": datasource_data.name or "Unknown", "error": f"Vault integration failed: {e.detail}"})
                        continue
                    except Exception as e:
                        logger.error(f"Unexpected error during vault integration: {str(e)}", exc_info=True)
                        failed_datasources.append({"name": datasource_data.name or "Unknown", "error": "Failed to integrate with vault service"})
                        continue

                final_metadata = enhanced_metadata.copy()
                if vault_unique_id:
                    final_metadata["vault_unique_id"] = str(vault_unique_id)

                # Create datasource
                datasource = Datasource(
                    id=str(uuid.uuid4()),
                    name=datasource_name,
                    filename=filename,
                    storage_type=datasource_data.storage_type,
                    provider=datasource_data.provider,
                    app_type=datasource_data.app_type,
                    log_type=datasource_data.log_type,
                    config=datasource_data.config.dict() if datasource_data.config else None,
                    datasource_metadata=final_metadata,
                    giggso_vault_id=giggso_vault_id,
                    file_size=datasource_data.file_size or 0,
                    file_type=datasource_data.file_type or "application/octet-stream",
                    file_url=datasource_data.file_url,
                    channel_id=thread.channel_id,
                    added_by=user.id,
                    is_embedding_required=datasource_data.is_embedding_required or False,
                    embedding_status=1 if (datasource_data.is_embedding_required or False) else 0
                )

                db.add(datasource)
                await db.commit()
                await db.refresh(datasource)
                
                logger.info(f"✅ Created datasource: {datasource_name} (id={datasource.id}, thread_id={thread_uuid})")

                created_datasources.append({
                    "id": str(datasource.id),
                    "name": datasource.name,
                    "filename": datasource.filename,
                    "storage_type": datasource.storage_type,
                    "provider": datasource.provider,
                    "app_type": datasource.app_type,
                    "config": datasource.config,
                    "datasource_metadata": sanitize_datasource_metadata(datasource.datasource_metadata),
                    "giggso_vault_id": str(datasource.giggso_vault_id) if datasource.giggso_vault_id else None,
                    "file_size": datasource.file_size,
                    "file_type": datasource.file_type,
                    "file_url": datasource.file_url,
                    "channel_id": str(datasource.channel_id),
                    "workspace_id": str(thread.workspace_id),
                    "company_id": str(channel.company_id),
                    "added_by": str(datasource.added_by),
                    "is_active": datasource.is_active,
                    "is_connected": datasource.is_connected,
                    "is_processed": datasource.is_processed,
                    "processing_status": datasource.processing_status,
                    "error_message": datasource.error_message,
                    "last_processed_at": datasource.last_processed_at,
                    "processing_time": datasource.processing_time,
                    "record_count": datasource.record_count,
                    "is_embedding_required": datasource.is_embedding_required,
                    "embedding_status": datasource.embedding_status,
                    "created_at": datasource.created_at,
                    "updated_at": datasource.updated_at
                })

            except Exception as e:
                logger.error(f"Error processing datasource in internal bulk API: {str(e)}", exc_info=True)
                failed_datasources.append({"name": datasource_data.name or "Unknown", "error": str(e)})

        # Check if any datasources require embedding processing
        embedding_required_datasources = [ds for ds in created_datasources if ds.get("is_embedding_required", False)]

        if embedding_required_datasources:
            giggso_vault_ids = []
            for ds in embedding_required_datasources:
                if ds.get("giggso_vault_id"):
                    giggso_vault_ids.append(ds["giggso_vault_id"])

            vault_unique_ids = []
            vault_records = []
            if giggso_vault_ids:
                stmt = select(GiggsoVault).where(GiggsoVault.giggso_vault_id.in_(giggso_vault_ids))
                result = await db.execute(stmt)
                vault_records = result.scalars().all()
                vault_unique_ids = [record.vault_unique_id for record in vault_records if record.vault_unique_id]

                logger.info("=" * 80)
                logger.info("🔍 VAULT ID CONVERSION (INTERNAL API)")
                logger.info("=" * 80)
                logger.info(f"📊 Found {len(embedding_required_datasources)} datasources requiring embedding")
                logger.info(f"🔑 giggso_vault_ids: {giggso_vault_ids}")
                logger.info(f"📦 vault_unique_ids: {vault_unique_ids}")
                logger.info("=" * 80)

            if vault_unique_ids:
                first_datasource = embedding_required_datasources[0]
                channel_id = first_datasource.get("channel_id")
                user_id = first_datasource.get("added_by")
                company_id = first_datasource.get("company_id")

                if not user_id or not company_id:
                    logger.error(f"❌ Cannot proceed with embedding - missing user_id or company_id")
                    logger.error(f"   user_id: {user_id}, company_id: {company_id}")
                else:
                    # Classify each datasource by embedd_type and group them
                    from app.services.ml_service import get_embedd_type_from_file_type
                    
                    # Create a mapping from giggso_vault_id to vault_unique_id
                    vault_id_mapping = {}
                    for ds in embedding_required_datasources:
                        giggso_vault_id = ds.get("giggso_vault_id")
                        if giggso_vault_id:
                            # Find corresponding vault_unique_id
                            for record in vault_records:
                                # Convert both to strings for comparison to handle UUID vs string mismatches
                                if str(record.giggso_vault_id) == str(giggso_vault_id):
                                    vault_id_mapping[str(giggso_vault_id)] = record.vault_unique_id
                                    break
                    
                    logger.debug(f"🔍 Vault ID Mapping created (Internal): {len(vault_id_mapping)} mappings")
                    logger.debug(f"   Mapping keys: {list(vault_id_mapping.keys())}")
                    
                    # Group datasources by embedd_type
                    textual_datasources = []
                    tabular_datasources = []
                    
                    for ds in embedding_required_datasources:
                        # Determine embedd_type for this datasource
                        embedd_type = get_embedd_type_from_file_type(
                            file_type=ds.get("file_type"),
                            storage_type=ds.get("storage_type"),
                            provider=ds.get("provider")
                        )
                        
                        # Extract base type (remove provider suffix if any)
                        base_type = embedd_type.split("_")[0]
                        
                        # Group by base type
                        if base_type == "tabular":
                            tabular_datasources.append({
                                "datasource": ds,
                                "giggso_vault_id": ds.get("giggso_vault_id"),
                                "embedd_type": embedd_type
                            })
                        else:
                            # Default to textual for unknown types or textual files
                            textual_datasources.append({
                                "datasource": ds,
                                "giggso_vault_id": ds.get("giggso_vault_id"),
                                "embedd_type": embedd_type
                            })
                    
                    logger.info("=" * 80)
                    logger.info("📊 FILE CLASSIFICATION FOR BULK EMBEDDING (INTERNAL API)")
                    logger.info("=" * 80)
                    logger.info(f"📄 Textual files: {len(textual_datasources)}")
                    logger.info(f"📊 Tabular files: {len(tabular_datasources)}")
                    logger.info("=" * 80)
                    
                    # Internal/bulk = thread-level: extract thread_id from first datasource metadata (all have thread_id)
                    thread_id_for_embedding = None
                    first_ds_meta = embedding_required_datasources[0].get("datasource_metadata") or {}
                    if isinstance(first_ds_meta, dict) and first_ds_meta.get("thread_id"):
                        thread_id_for_embedding = first_ds_meta.get("thread_id")
                        logger.info(f"🧵 Thread-level embedding scope for internal/bulk: thread_id={thread_id_for_embedding}")
                    
                    # Use thread-level completed embeddings when thread_id present; else channel-level
                    if thread_id_for_embedding:
                        embedded_vault_unique_ids = await get_completed_embeddings_by_thread(thread_id_for_embedding, db)
                    else:
                        embedded_vault_unique_ids = await get_completed_embeddings_by_channel(channel_id, db)
                    jwt_token = settings.ML_API_KEY if settings.ML_API_KEY else None
                    # Fetch OpenAI vault token (gpt_token) for company to send to ML API
                    openai_vault_token = await get_openai_vault_token_for_company(db, company_id)

                    # Process textual files group
                    if textual_datasources:
                        textual_vault_unique_ids = [
                            vault_id_mapping[str(ds["giggso_vault_id"])]
                            for ds in textual_datasources
                            if ds["giggso_vault_id"] and str(ds["giggso_vault_id"]) in vault_id_mapping
                        ]
                        
                        logger.debug(f"📄 Textual vault_unique_ids (Internal): {textual_vault_unique_ids}")
                        
                        if textual_vault_unique_ids:
                            textual_ds_list = [ds["datasource"] for ds in textual_datasources]
                            
                            # Extract table_name from first textual datasource metadata that has it
                            table_name = None
                            for ds in textual_datasources:
                                metadata = ds["datasource"].get("datasource_metadata")
                                if metadata and isinstance(metadata, dict):
                                    table_name = metadata.get("tableName")
                                    if table_name:
                                        break
                            
                            try:
                                table_names = extract_table_names_from_datasources(textual_ds_list) if len(textual_ds_list) > 1 else None
                                logger.info(f"🚀 Calling ML API for {len(textual_vault_unique_ids)} textual file(s) with embedd_type='textual'")
                                
                                result = await ml_service.request_embedding_processing(
                                    vault_unique_ids=textual_vault_unique_ids,
                                    user_id=user_id,
                                    company_id=company_id,
                                    channel_id=channel_id,
                                    embedded_vault_unique_ids=embedded_vault_unique_ids,
                                    jwt_token=jwt_token,
                                    embedd_type="textual",
                                    table_name=table_name,
                                    table_names=table_names,
                                    thread_id=thread_id_for_embedding,
                                    openai_vault_token=openai_vault_token
                                )
                                
                                # Emit socket event based on ML API response
                                socket_service = get_socket_service()
                                if socket_service.is_socket_connected():
                                    ml_status = 2 if result.get("success") else 3
                                    
                                    # Emit socket event for each textual datasource
                                    for ds in textual_datasources:
                                        datasource_id = ds["datasource"].get("id")
                                        if datasource_id:
                                            socket_event_data = {"type": 16, "data": {"channelId": channel_id, "status": ml_status, "datasourceId": datasource_id}}
                                            try:
                                                await socket_service.emit("shay_realtime", socket_event_data)
                                                logger.info(f"✅ Emitted socket event for textual datasource {datasource_id}: status={ml_status}")
                                            except Exception as socket_error:
                                                logger.error(f"❌ Failed to emit socket event for datasource {datasource_id}: {socket_error}")
                                
                                if result.get("success"):
                                    logger.info(f"✅ ML API call successful for {len(textual_vault_unique_ids)} textual file(s)")
                                else:
                                    logger.error(f"❌ ML API call failed for textual files: {result.get('message', 'Unknown error')}")
                                    
                            except Exception as e:
                                logger.error(f"❌ Error calling ML API for textual files: {e}")
                                
                                # Emit socket event for failure
                                socket_service = get_socket_service()
                                if socket_service.is_socket_connected():
                                    for ds in textual_datasources:
                                        datasource_id = ds["datasource"].get("id")
                                        if datasource_id:
                                            try:
                                                await socket_service.emit("shay_realtime", {
                                                    "type": 16,
                                                    "data": {
                                                        "channelId": channel_id,
                                                        "status": 3,  # failure
                                                        "datasourceId": datasource_id
                                                    }
                                                })
                                            except Exception:
                                                pass
                    
                    # Process tabular files group
                    if tabular_datasources:
                        tabular_vault_unique_ids = [
                            vault_id_mapping[str(ds["giggso_vault_id"])]
                            for ds in tabular_datasources
                            if ds["giggso_vault_id"] and str(ds["giggso_vault_id"]) in vault_id_mapping
                        ]
                        
                        logger.debug(f"📊 Tabular vault_unique_ids (Internal): {tabular_vault_unique_ids}")
                        
                        if tabular_vault_unique_ids:
                            tabular_ds_list = [ds["datasource"] for ds in tabular_datasources]
                            
                            # Extract table_name from first tabular datasource metadata that has it
                            table_name = None
                            for ds in tabular_datasources:
                                metadata = ds["datasource"].get("datasource_metadata")
                                if metadata and isinstance(metadata, dict):
                                    table_name = metadata.get("tableName")
                                    if table_name:
                                        break
                            
                            try:
                                table_names = extract_table_names_from_datasources(tabular_ds_list) if len(tabular_ds_list) > 1 else None
                                logger.info(f"🚀 Calling ML API for {len(tabular_vault_unique_ids)} tabular file(s) with embedd_type='tabular'")
                                
                                result = await ml_service.request_embedding_processing(
                                    vault_unique_ids=tabular_vault_unique_ids,
                                    user_id=user_id,
                                    company_id=company_id,
                                    channel_id=channel_id,
                                    embedded_vault_unique_ids=embedded_vault_unique_ids,
                                    jwt_token=jwt_token,
                                    embedd_type="tabular",
                                    table_name=table_name,
                                    table_names=table_names,
                                    thread_id=thread_id_for_embedding,
                                    openai_vault_token=openai_vault_token
                                )
                                
                                # Emit socket event based on ML API response
                                socket_service = get_socket_service()
                                if socket_service.is_socket_connected():
                                    ml_status = 2 if result.get("success") else 3
                                    
                                    # Emit socket event for each tabular datasource
                                    for ds in tabular_datasources:
                                        datasource_id = ds["datasource"].get("id")
                                        if datasource_id:
                                            socket_event_data = {"type": 16, "data": {"channelId": channel_id, "status": ml_status, "datasourceId": datasource_id}}
                                            try:
                                                await socket_service.emit("shay_realtime", socket_event_data)
                                                logger.info(f"✅ Emitted socket event for tabular datasource {datasource_id}: status={ml_status}")
                                            except Exception as socket_error:
                                                logger.error(f"❌ Failed to emit socket event for datasource {datasource_id}: {socket_error}")
                                
                                if result.get("success"):
                                    logger.info(f"✅ ML API call successful for {len(tabular_vault_unique_ids)} tabular file(s)")
                                else:
                                    logger.error(f"❌ ML API call failed for tabular files: {result.get('message', 'Unknown error')}")
                                    
                            except Exception as e:
                                logger.error(f"❌ Error calling ML API for tabular files: {e}")
                                
                                # Emit socket event for failure
                                socket_service = get_socket_service()
                                if socket_service.is_socket_connected():
                                    for ds in tabular_datasources:
                                        datasource_id = ds["datasource"].get("id")
                                        if datasource_id:
                                            try:
                                                await socket_service.emit("shay_realtime", {
                                                    "type": 16,
                                                    "data": {
                                                        "channelId": channel_id,
                                                        "status": 3,  # failure
                                                        "datasourceId": datasource_id
                                                    }
                                                })
                                            except Exception:
                                                pass
    except Exception as e:
        logger.error(f"❌ [INTERNAL-BULK] Unhandled error in internal bulk API: {str(e)}", exc_info=True)
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return DatasourceBulkResponse(
            created_datasources=created_datasources if 'created_datasources' in locals() else [],
            failed_datasources=(failed_datasources if 'failed_datasources' in locals() else []) + [{"name": "Unknown", "error": f"Internal server error: {str(e)}"}]
        )

    logger.info(
        f"📊 [INTERNAL-BULK] Completed - Created: {len(created_datasources)}, "
        f"Failed: {len(failed_datasources)}, Skipped (duplicates): {len(skipped_datasources)}"
    )
    if failed_datasources:
        logger.warning(f"⚠️ [INTERNAL-BULK] Failed datasources: {failed_datasources}")
    if skipped_datasources:
        logger.info(f"⏭️ [INTERNAL-BULK] Skipped (duplicates in same thread): {skipped_datasources}")

    return DatasourceBulkResponse(
        created_datasources=created_datasources,
        failed_datasources=failed_datasources,
        total_created=len(created_datasources),
        total_failed=len(failed_datasources)
    )


@router.get("/environment", response_model=Dict[str, Any])
async def get_environment_config():
    """Get current environment configuration for debugging vault settings"""
    from app.services.vault_data_builder import get_environment_info
    return get_environment_info()

@router.get("/", response_model=DatasourceListWithRelations)
async def list_datasources(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    channel_id: Optional[str] = None,
    thread_id: Optional[str] = Query(None, description="Filter by thread ID. When set, returns only thread-level datasources for this thread. When omitted, channel-level list excludes thread-level (e.g. email attachment) datasources."),
    storage_type: Optional[str] = Query(None, description="Filter by storage type: local, cloud, db, app"),
    data_source_type: Optional[str] = Query(None, description="Alias for storage_type. Filter by data source type: local, cloud, db, app"),
    provider: Optional[str] = None,
    app_type: Optional[str] = None,
    processing_status: Optional[str] = None,
    is_connected: Optional[bool] = Query(None, description="Filter by connection status. True for connected, False for disconnected"),
    search: Optional[str] = None
):
    """List datasources with filtering and pagination
    
    Supports filtering by data source type (storage_type or data_source_type):
    - local: Local file uploads
    - cloud: Cloud storage (S3, Azure, etc.)
    - db: Database connections
    - app: App-based sources (Google Drive, SharePoint, etc.)
    
    Thread-level vs channel-level: Attachment datasources from email sync are stored as
    thread-level (datasource_metadata.thread_id set). When listing by channel without
    thread_id, only channel-level datasources are returned. Pass thread_id to get
    datasources for a specific thread (e.g. email attachments in that thread).
    """
    user = await get_current_user_required(request)
    
    # If channel_id is provided, check channel access first
    if channel_id:
        await check_channel_access(db, user, channel_id)
    
    # Build base query - filter by user's company and only channels user is a member of (gg_channel_members)
    query = (
        select(Datasource)
        .join(Datasource.channel)
        .where(Channel.company_id == user.company_id)
        .join(
            ChannelMember,
            and_(
                ChannelMember.channel_id == Datasource.channel_id,
                ChannelMember.user_id == user.id,
                ChannelMember.is_active == True,
            ),
        )
    )
    
    # Exclude database datasources without a tableName (incomplete database connections)
    # Database datasources should have a tableName in config or datasource_metadata
    query = query.where(
        or_(
            Datasource.storage_type != "database",
            and_(
                Datasource.storage_type == "database",
                or_(
                    and_(
                        Datasource.config.op("?")(literal("tableName", type_=String())),
                        Datasource.config.op("->>")(literal("tableName", type_=String())).isnot(None),
                        Datasource.config.op("->>")(literal("tableName", type_=String())) != literal("", type_=String())
                    ),
                    and_(
                        Datasource.datasource_metadata.op("?")(literal("tableName", type_=String())),
                        Datasource.datasource_metadata.op("->>")(literal("tableName", type_=String())).isnot(None),
                        Datasource.datasource_metadata.op("->>")(literal("tableName", type_=String())) != literal("", type_=String())
                    )
                )
            )
        )
    )
    
    # Thread-level vs channel-level: attachment datasources from email sync have
    # datasource_metadata.thread_id set. When listing by channel without thread_id,
    # exclude thread-level so channel view shows only channel-level datasources.
    if thread_id:
        # Return only datasources for this thread (e.g. email attachments in thread)
        try:
            thread_uuid = uuid.UUID(thread_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid thread_id format: {thread_id}"
            )
        await check_channel_access_by_thread(db, user, thread_id)
        query = query.where(
            and_(
                Datasource.datasource_metadata.isnot(None),
                Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
                Datasource.datasource_metadata.op("->>")(literal("thread_id", type_=String())) == literal(str(thread_uuid), type_=String())
            )
        )
        # Include all thread-level datasources (any embedding status) so new local/S3 attachments show immediately
        # Embedding can complete in background; no filter by embedding_status here
    else:
        # Exclude thread-level datasources so channel list shows only channel-level
        query = query.where(
            or_(
                Datasource.datasource_metadata.is_(None),
                ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
            )
        )
    
    # Apply filters
    if channel_id:
        # Convert channel_id to UUID if it's a string
        channel_uuid = channel_id
        if isinstance(channel_id, str):
            try:
                channel_uuid = uuid.UUID(channel_id)
            except (ValueError, AttributeError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid channel_id format: {channel_id}"
                )
        query = query.where(Datasource.channel_id == channel_uuid)
    
    # Use data_source_type if provided, otherwise use storage_type
    type_filter = data_source_type if data_source_type else storage_type
    if type_filter:
        query = query.where(Datasource.storage_type == type_filter)
    
    if provider:
        query = query.where(Datasource.provider == provider)
    
    if app_type:
        query = query.where(Datasource.app_type == app_type)
    
    if processing_status:
        query = query.where(Datasource.processing_status == processing_status)
    
    if is_connected is not None:
        query = query.where(Datasource.is_connected == is_connected)
    
    if search:
        search_filter = or_(
            Datasource.name.ilike(f"%{search}%"),
            Datasource.filename.ilike(f"%{search}%")
        )
        query = query.where(search_filter)
    
    # Get total count - same as main query: company + channel membership
    count_query = (
        select(func.count(Datasource.id))
        .join(Datasource.channel)
        .where(Channel.company_id == user.company_id)
        .join(
            ChannelMember,
            and_(
                ChannelMember.channel_id == Datasource.channel_id,
                ChannelMember.user_id == user.id,
                ChannelMember.is_active == True,
            ),
        )
    )
    
    # Apply same filter to exclude database datasources without tableName
    count_query = count_query.where(
        or_(
            Datasource.storage_type != "database",
            and_(
                Datasource.storage_type == "database",
                or_(
                    and_(
                        Datasource.config.op("?")(literal("tableName", type_=String())),
                        Datasource.config.op("->>")(literal("tableName", type_=String())).isnot(None),
                        Datasource.config.op("->>")(literal("tableName", type_=String())) != literal("", type_=String())
                    ),
                    and_(
                        Datasource.datasource_metadata.op("?")(literal("tableName", type_=String())),
                        Datasource.datasource_metadata.op("->>")(literal("tableName", type_=String())).isnot(None),
                        Datasource.datasource_metadata.op("->>")(literal("tableName", type_=String())) != literal("", type_=String())
                    )
                )
            )
        )
    )
    
    # Apply same thread-level vs channel-level logic to count query
    if thread_id:
        count_query = count_query.where(
            and_(
                Datasource.datasource_metadata.isnot(None),
                Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
                Datasource.datasource_metadata.op("->>")(literal("thread_id", type_=String())) == literal(str(thread_uuid), type_=String())
            )
        )
        # No embedding filter for count: include all thread-level (matches main query)
    else:
        count_query = count_query.where(
            or_(
                Datasource.datasource_metadata.is_(None),
                ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
            )
        )
    
    # Apply same filters to count query
    if channel_id:
        count_query = count_query.where(Datasource.channel_id == channel_uuid)
    
    if type_filter:
        count_query = count_query.where(Datasource.storage_type == type_filter)
    
    if provider:
        count_query = count_query.where(Datasource.provider == provider)
    
    if app_type:
        count_query = count_query.where(Datasource.app_type == app_type)
    
    if processing_status:
        count_query = count_query.where(Datasource.processing_status == processing_status)
    
    if is_connected is not None:
        count_query = count_query.where(Datasource.is_connected == is_connected)
    
    if search:
        search_filter = or_(
            Datasource.name.ilike(f"%{search}%"),
            Datasource.filename.ilike(f"%{search}%")
        )
        count_query = count_query.where(search_filter)
    
    # Execute count query
    count_result = await db.execute(count_query)
    total_count = count_result.scalar()
    
    # Apply pagination and ordering (tie-break by id so "latest" is deterministic for same created_at)
    query = query.order_by(desc(Datasource.created_at), desc(Datasource.id))
    
    # For thread-level queries: deduplicate by filename; prefer embedding-completed when present, else latest
    # Same file can appear in multiple emails; return one row per filename so no duplicates
    if thread_id:
        result = await db.execute(query)
        all_datasources = result.scalars().all()
        # Sort: embedding_status==2 (completed) first, then by created_at desc, then id desc
        # So per filename we keep: completed row if any, else the latest row
        def _thread_ds_sort_key(ds):
            ts = ds.created_at.timestamp() if ds.created_at else 0
            return (0 if (ds.embedding_status == 2) else 1, -ts, str(ds.id or ""))

        all_datasources_sorted = sorted(all_datasources, key=_thread_ds_sort_key)
        seen_filenames = {}
        unique_datasources = []
        for ds in all_datasources_sorted:
            filename_key = (ds.filename or ds.name or "unknown").strip() or "unknown"
            if filename_key not in seen_filenames:
                seen_filenames[filename_key] = True
                unique_datasources.append(ds)

        total_count = len(unique_datasources)
        start_idx = (page - 1) * size
        end_idx = start_idx + size
        datasources = unique_datasources[start_idx:end_idx]
    else:
        # For channel-level queries: apply pagination normally
        query = query.offset((page - 1) * size).limit(size)
        result = await db.execute(query)
        datasources = result.scalars().all()
    
    # Fetch current user's channel memberships for all channels in this page (avoids N+1)
    unique_channel_ids = list({ds.channel_id for ds in datasources if ds.channel_id})
    members_map = {}  # channel_id -> ChannelMember for current user
    if unique_channel_ids:
        members_stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id.in_(unique_channel_ids),
                ChannelMember.user_id == user.id,
                ChannelMember.is_active == True
            )
        )
        members_result = await db.execute(members_stmt)
        for member in members_result.scalars().all():
            members_map[member.channel_id] = member
    
    # Convert to response format
    datasource_responses = []
    for datasource in datasources:
        # Get channel for workspace_id and company_id
        channel_stmt = select(Channel).where(Channel.id == datasource.channel_id)
        channel_result = await db.execute(channel_stmt)
        channel = channel_result.scalar_one_or_none()
        
        # Get user who added the datasource
        added_by_user = None
        if datasource.added_by:
            # Ensure added_by is a UUID object if it's a string
            added_by_id = datasource.added_by
            if isinstance(added_by_id, str):
                try:
                    added_by_id = uuid.UUID(added_by_id)
                except (ValueError, AttributeError):
                    added_by_id = None
            
            if added_by_id:
                user_stmt = select(User).where(User.id == added_by_id)
                user_result = await db.execute(user_stmt)
                added_by_user = user_result.scalar_one_or_none()
        
        # Convert channel to dict (include is_member and member_role from gg_channel_members)
        channel_dict = None
        if channel:
            member = members_map.get(channel.id)
            is_member = member is not None
            # member_role: "admin" or "user" per gg_channel_members.role
            member_role = ("admin" if member.role == "admin" else "user") if member else None
            channel_dict = {
                "id": str(channel.id),
                "name": channel.name,
                "description": channel.description,
                "workspace_id": str(channel.workspace_id),
                "workspace_name": getattr(channel, 'workspace_name', None),
                "company_id": str(channel.company_id),
                "is_active": channel.is_active,
                "is_public": channel.is_public,
                "ai_enabled": channel.ai_enabled,
                "channel_settings": channel.channel_settings,
                "message_count": getattr(channel, 'message_count', 0),
                "last_message_at": getattr(channel, 'last_message_at', None),
                "created_at": channel.created_at,
                "updated_at": channel.updated_at,
                "is_member": is_member,
                "member_role": member_role
            }
        
        # Convert user to dict
        user_dict = None
        if added_by_user:
            user_dict = {
                "user_id": str(added_by_user.id),
                "name": added_by_user.name,
                "email_id": added_by_user.email_id,
                "avatar_url": added_by_user.avatar_url,
                "company_id": str(added_by_user.company_id),
                "role": added_by_user.role,
                "created_datetime": added_by_user.created_datetime,
                "updated_datetime": added_by_user.updated_datetime
            }
        
        datasource_responses.append({
            "id": str(datasource.id),
            "name": datasource.name,
            "filename": datasource.filename,
            "storage_type": datasource.storage_type,
            "provider": datasource.provider,
            "app_type": datasource.app_type,
            "config": datasource.config,
            "datasource_metadata": sanitize_datasource_metadata(datasource.datasource_metadata),
            "giggso_vault_id": str(datasource.giggso_vault_id) if datasource.giggso_vault_id else None,
            "file_size": datasource.file_size,
            "file_type": datasource.file_type,
            "file_url": datasource.file_url,
            "channel": channel_dict,  # Full channel object as dict
            "added_by_user": user_dict,  # Full user object as dict
            "is_active": datasource.is_active,
            "is_connected": datasource.is_connected,
            "is_processed": datasource.is_processed,
            "processing_status": datasource.processing_status,
            "error_message": datasource.error_message,
            "last_processed_at": datasource.last_processed_at,
            "processing_time": datasource.processing_time,
            "record_count": datasource.record_count,
            "is_embedding_required": datasource.is_embedding_required,
            "embedding_status": datasource.embedding_status,
            "created_at": datasource.created_at,
            "updated_at": datasource.updated_at
        })
    
    return DatasourceListWithRelations(
        datasources=datasource_responses,
        total=total_count,
        page=page,
        size=size,
        pages=(total_count + size - 1) // size
    )


@router.get("/stats", response_model=DatasourceStats)
async def get_datasource_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    channel_id: Optional[str] = None
):
    """Get datasource statistics"""
    user = await get_current_user_required(request)
    
    # Build base query - filter by user's company through channel relationship
    base_query = select(Datasource).join(Datasource.channel).where(Channel.company_id == user.company_id)
    total_query = select(func.count(Datasource.id)).join(Datasource.channel).where(Channel.company_id == user.company_id)
    
    # Apply channel filter if provided
    if channel_id:
        # Convert channel_id to UUID if it's a string
        channel_uuid = channel_id
        if isinstance(channel_id, str):
            try:
                channel_uuid = uuid.UUID(channel_id)
            except (ValueError, AttributeError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid channel_id format: {channel_id}"
                )
        base_query = base_query.where(Datasource.channel_id == channel_uuid)
        total_query = total_query.where(Datasource.channel_id == channel_uuid)
    
    # Exclude thread-level datasources (e.g. email attachments) from channel stats
    # so channel-level stats show only channel-level datasources
    base_query = base_query.where(
        or_(
            Datasource.datasource_metadata.is_(None),
            ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
        )
    )
    total_query = total_query.where(
        or_(
            Datasource.datasource_metadata.is_(None),
            ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
        )
    )
    
    # Get total count
    total_result = await db.execute(total_query)
    total_count = total_result.scalar()
    
    # Get active count
    active_query = base_query.where(and_(Datasource.is_active == True))
    active_result = await db.execute(active_query)
    active_count = len(active_result.scalars().all())
    
    # Get processed count
    processed_query = base_query.where(and_(Datasource.is_processed == True))
    processed_result = await db.execute(processed_query)
    processed_count = len(processed_result.scalars().all())
    
    # Get pending count
    pending_query = base_query.where(and_(Datasource.processing_status == "pending"))
    pending_result = await db.execute(pending_query)
    pending_count = len(pending_result.scalars().all())
    
    # Get failed count
    failed_query = base_query.where(and_(Datasource.processing_status == "failed"))
    failed_result = await db.execute(failed_query)
    failed_count = len(failed_result.scalars().all())
    
    # Get total file size
    size_query = base_query.where(and_(Datasource.file_size.isnot(None)))
    size_result = await db.execute(size_query)
    datasources_with_size = size_result.scalars().all()
    total_file_size = sum(ds.file_size for ds in datasources_with_size if ds.file_size)
    
    # Get storage type distribution

    # Use select() with columns directly for Core query (not with_entities which is ORM-only)
    storage_types_query = select(
        Datasource.storage_type,
        func.count(Datasource.id).label('count')
    ).join(Datasource.channel).where(
        Channel.company_id == user.company_id
    ).group_by(Datasource.storage_type)
    
    # Apply channel filter if provided
    if channel_id:
        storage_types_query = storage_types_query.where(Datasource.channel_id == channel_uuid)
    
    # Apply thread-level filtering
    storage_types_query = storage_types_query.where(
        or_(
            Datasource.datasource_metadata.is_(None),
            ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
        )
    )
    
    storage_types_result = await db.execute(storage_types_query)
    storage_types = {row.storage_type: row.count for row in storage_types_result}
    
    # Get provider distribution (for cloud storage)
    provider_query = base_query.where(and_(Datasource.provider.isnot(None)))
    provider_result = await db.execute(provider_query)
    providers = {}
    for datasource in provider_result.scalars().all():
        provider = datasource.provider
        providers[provider] = providers.get(provider, 0) + 1
    
    return DatasourceStats(
        total_datasources=total_count,
        active_datasources=active_count,
        processed_datasources=processed_count,
        pending_datasources=pending_count,
        failed_datasources=failed_count,
        total_file_size=total_file_size,
        storage_type_breakdown=storage_types,
        provider_breakdown=providers
    )


@router.get("/count", response_model=DatasourceTypeCountResponse)
async def get_datasource_type_count(
    request: Request,
    db: AsyncSession = Depends(get_db),
    channel_id: Optional[str] = None
):
    """Get count of connected data sources by type (local, cloud, db, app)"""
    user = await get_current_user_required(request)
    
    # Build base query - filter by user's company and connected status
    # Get counts grouped by storage_type
    count_query = select(
        Datasource.storage_type,
        func.count(Datasource.id).label('count')
    ).join(Datasource.channel).where(
        and_(
            Channel.company_id == user.company_id,
            Datasource.is_connected == True
        )
    ).group_by(Datasource.storage_type)
    
    # Apply channel filter if provided
    if channel_id:
        # Convert channel_id to UUID if it's a string
        channel_uuid = channel_id
        if isinstance(channel_id, str):
            try:
                channel_uuid = uuid.UUID(channel_id)
            except (ValueError, AttributeError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid channel_id format: {channel_id}"
                )
        count_query = count_query.where(Datasource.channel_id == channel_uuid)
    
    # Exclude thread-level datasources (e.g. email attachments) from type count
    # so channel-level count shows only channel-level datasources
    count_query = count_query.where(
        or_(
            Datasource.datasource_metadata.is_(None),
            ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
        )
    )
    
    # Execute query to get counts by type
    result = await db.execute(count_query)
    type_counts = {row.storage_type: row.count for row in result}
    
    # Define the data source types to include in response
    data_source_types = ["local", "cloud", "app", "db"]
    
    counts = []
    total_connected = 0
    
    # Build response with counts for each type (0 if not found)
    for ds_type in data_source_types:
        count = type_counts.get(ds_type, 0)
        total_connected += count
        counts.append(DatasourceTypeCount(type=ds_type, count=count))
    
    return DatasourceTypeCountResponse(
        counts=counts,
        total_connected=total_connected
    )





@router.get("/{datasource_id}", response_model=DatasourceResponse)
async def get_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific datasource by ID"""
    user = await get_current_user_required(request)
    
    # Get datasource with channel
    stmt = select(Datasource).where(Datasource.id == datasource_id)
    result = await db.execute(stmt)
    datasource = result.scalar_one_or_none()
    
    if not datasource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datasource not found"
        )
    
    # Check permissions through channel
    if not datasource.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to datasource"
        )
    
    # Get channel for workspace_id and company_id
    channel_stmt = select(Channel).where(Channel.id == datasource.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()
    
    return DatasourceResponse(
        id=str(datasource.id),
        name=datasource.name,
        filename=datasource.filename,
        storage_type=datasource.storage_type,
        provider=datasource.provider,
        app_type=datasource.app_type,
        config=datasource.config,
        datasource_metadata=sanitize_datasource_metadata(datasource.datasource_metadata),
        file_size=datasource.file_size,
        file_type=datasource.file_type,
        file_url=datasource.file_url,
        channel_id=str(datasource.channel_id),
        workspace_id=str(channel.workspace_id) if channel else None,
        company_id=str(channel.company_id) if channel else None,
        added_by=str(datasource.added_by),
        is_active=datasource.is_active,
        is_connected=datasource.is_connected,
        is_processed=datasource.is_processed,
        processing_status=datasource.processing_status,
        error_message=datasource.error_message,
        last_processed_at=datasource.last_processed_at,
        processing_time=datasource.processing_time,
        record_count=datasource.record_count,
        # Pre-existing bug, unrelated to the Aryx integration: these two
        # fields are required (non-Optional) on DatasourceResponse but were
        # never passed here, so this endpoint 500'd on every call before this
        # fix — discovered only because it blocked testing aryx_ingestion_status
        # below. Values match how every other endpoint in this file populates them.
        is_embedding_required=datasource.is_embedding_required,
        embedding_status=datasource.embedding_status,
        created_at=datasource.created_at,
        updated_at=datasource.updated_at,
        # Additive: None for every datasource without an aryx.discovery_id
        # in its metadata — existing (non-Aryx) callers see no change. This
        # is the real "poll by ID" endpoint, so it's the one that reflects
        # LIVE status on every call, not just a snapshot at creation time.
        aryx_ingestion_status=await _aryx_ingestion_status_for(datasource.datasource_metadata)
    )


@router.get("/{datasource_id}/download")
async def download_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    view: bool = Query(False, description="If true, use inline disposition for browser display; else attachment for download"),
    s3: bool = Query(False, description="If true, download from S3 using credentials from vault (datasource must have giggso_vault_id)"),
    azure: bool = Query(False, description="If true, download from Azure Blob using credentials from vault (datasource must have giggso_vault_id)"),
    gcp: bool = Query(False, description="If true, download from GCP Cloud Storage using credentials from vault (datasource must have giggso_vault_id)")
):
    """
    Download or view datasource file content. One API for all sources:
    - Tabular files (Excel, CSV, etc.): view or download. Files in our S3/local storage are
      streamed with correct Content-Type (e.g. text/csv, spreadsheet) so browsers can display them.
    - Google Drive (and other app) datasources: view or download via redirect to the external
      view URL (webViewLink/webContentLink or file_url) so the same API works for Drive-added docs.
    - S3-stored files: files uploaded through the app (stored in our S3) are streamed and support
      both view (inline) and download (attachment); external S3 file_url is served via redirect.
    - When s3=1: credentials are taken from vault (using datasource_id -> giggso_vault_id); file is downloaded from S3 and streamed.
    - When azure=1: credentials are taken from vault (using datasource_id -> giggso_vault_id); file is downloaded from Azure Blob and streamed.
    - When gcp=1: credentials are taken from vault (using datasource_id -> giggso_vault_id); file is downloaded from GCP Cloud Storage and streamed.
    - Database datasources (Oracle, Redshift, MySQL, etc.): no file; returns 404 with clear message.
    Use view=1 for in-browser display (e.g. PDF, CSV, Excel), or omit for download.
    """
    user = await get_current_user_required(request)
    
    # Get datasource
    stmt = select(Datasource).where(Datasource.id == datasource_id)
    result = await db.execute(stmt)
    datasource = result.scalar_one_or_none()
    
    if not datasource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datasource not found"
        )
    
    # Check permissions
    if not datasource.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to datasource"
        )
    
    # Case: s3=true — download from S3 using vault credentials (datasource_id -> vault -> S3 creds)
    if s3:
        if not datasource.giggso_vault_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Datasource has no vault integration; cannot download from S3 with vault credentials."
            )
        vault_creds = await get_vault_credentials_for_datasource(datasource, db)
        if not vault_creds:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vault record or credentials not found for this datasource."
            )
        file_content = await download_from_s3_with_vault_credentials(datasource, vault_creds, db)
        if not file_content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Could not download file from S3 (check vault credentials and datasource bucket/key or file_url)."
            )
        media_type = get_media_type_for_download(datasource)
        filename = datasource.filename or "datasource_file"
        disposition = "inline" if view else "attachment"
        return Response(
            content=file_content,
            media_type=media_type,
            headers={"Content-Disposition": f'{disposition}; filename="{filename}"'}
        )
    
    # Case: azure=true — download from Azure Blob using vault credentials (datasource_id -> vault -> Azure creds)
    if azure:
        if not datasource.giggso_vault_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Datasource has no vault integration; cannot download from Azure with vault credentials."
            )
        vault_creds = await get_vault_credentials_for_datasource(datasource, db)
        if not vault_creds:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vault record or credentials not found for this datasource."
            )
        file_content = await download_from_azure_with_vault_credentials(datasource, vault_creds, db)
        if not file_content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Could not download file from Azure (check vault credentials and datasource container/blob or file_url)."
            )
        media_type = get_media_type_for_download(datasource)
        filename = datasource.filename or "datasource_file"
        disposition = "inline" if view else "attachment"
        return Response(
            content=file_content,
            media_type=media_type,
            headers={"Content-Disposition": f'{disposition}; filename="{filename}"'}
        )
    
    # Case: gcp=true — download from GCP Cloud Storage using vault credentials (datasource_id -> vault -> GCP creds)
    if gcp:
        if not datasource.giggso_vault_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Datasource has no vault integration; cannot download from GCP with vault credentials."
            )
        vault_creds = await get_vault_credentials_for_datasource(datasource, db)
        if not vault_creds:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vault record or credentials not found for this datasource."
            )
        file_content = await download_from_gcp_with_vault_credentials(datasource, vault_creds, db)
        if not file_content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Could not download file from GCP (check vault credentials and datasource bucket/blob or file_url)."
            )
        media_type = get_media_type_for_download(datasource)
        filename = datasource.filename or "datasource_file"
        disposition = "inline" if view else "attachment"
        return Response(
            content=file_content,
            media_type=media_type,
            headers={"Content-Disposition": f'{disposition}; filename="{filename}"'}
        )
    
    # Case 1: File stored in our storage (manual upload via upload/from-upload/bulk)
    storage_file_path = get_storage_file_path_for_deletion(datasource)
    if storage_file_path:
        try:
            storage_service = get_file_storage_service()
            file_content = await storage_service.download_file(storage_file_path)
        except Exception as e:
            logger.error(f"Failed to download datasource file {datasource_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File not found or failed to download: {str(e)}"
            )
        # Content type for view: use correct media type for tabular (Excel, CSV) and others
        media_type = get_media_type_for_download(datasource)
        filename = datasource.filename or "datasource_file"
        disposition = "inline" if view else "attachment"
        return Response(
            content=file_content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'{disposition}; filename="{filename}"'
            }
        )
    
    # Case 2: External view/download URL (cloud storage, app integrations e.g. Google Drive, SharePoint)
    external_url = get_external_view_url_for_datasource(datasource)
    if external_url:
        if "application/json" in (request.headers.get("accept") or "").lower():
            return JSONResponse(status_code=200, content={"url": external_url})
        return RedirectResponse(url=external_url, status_code=302)
    
    # Case 3: Database datasources (Oracle, Redshift, MySQL, PostgreSQL, SQL Server, MongoDB, DynamoDB, Snowflake)
    # No file to view or download; only table/collection references
    if datasource.storage_type == "database" or (
        getattr(datasource, "provider", None) and datasource.provider in DATASOURCE_DATABASE_PROVIDERS
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Database datasources (e.g. Oracle, Redshift, MySQL, PostgreSQL, SQL Server, MongoDB, DynamoDB, Snowflake) do not have a viewable or downloadable file; they reference tables or collections."
        )
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No downloadable file found for this datasource"
    )


@router.put("/{datasource_id}", response_model=DatasourceResponse)
async def update_datasource(
    datasource_id: str,
    datasource_data: DatasourceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Update a specific datasource"""
    user = await get_current_user_required(request)
    
    # Get datasource
    stmt = select(Datasource).where(Datasource.id == datasource_id)
    result = await db.execute(stmt)
    datasource = result.scalar_one_or_none()
    
    if not datasource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datasource not found"
        )
    
    # Check permissions through channel
    if not datasource.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to datasource"
        )
    
    # Update fields if provided
    if datasource_data.name is not None:
        datasource.name = datasource_data.name
    
    if datasource_data.storage_type is not None:
        datasource.storage_type = datasource_data.storage_type
    
    if datasource_data.provider is not None:
        datasource.provider = datasource_data.provider
    
    if datasource_data.app_type is not None:
        datasource.app_type = datasource_data.app_type
    
    if datasource_data.log_type is not None:
        datasource.log_type = datasource_data.log_type
    
    if datasource_data.config is not None:
        # Update config directly (no vault integration for config updates)
        datasource.config = datasource_data.config.dict()
    
    if datasource_data.datasource_metadata is not None:
        datasource.datasource_metadata = datasource_data.datasource_metadata
    
    if datasource_data.is_active is not None:
        datasource.is_active = datasource_data.is_active
    
    if datasource_data.is_connected is not None:
        datasource.is_connected = datasource_data.is_connected
    
    await db.commit()
    await db.refresh(datasource)
    
    # Get channel for workspace_id and company_id
    channel_stmt = select(Channel).where(Channel.id == datasource.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()
    
    return DatasourceResponse(
        id=str(datasource.id),
        name=datasource.name,
        filename=datasource.filename,
        storage_type=datasource.storage_type,
        provider=datasource.provider,
        app_type=datasource.app_type,
        config=datasource.config,
        datasource_metadata=sanitize_datasource_metadata(datasource.datasource_metadata),
        file_size=datasource.file_size,
        file_type=datasource.file_type,
        file_url=datasource.file_url,
        channel_id=str(datasource.channel_id),
        workspace_id=str(channel.workspace_id) if channel else None,
        company_id=str(channel.company_id) if channel else None,
        added_by=str(datasource.added_by),
        is_active=datasource.is_active,
        is_connected=datasource.is_connected,
        is_processed=datasource.is_processed,
        processing_status=datasource.processing_status,
        error_message=datasource.error_message,
        last_processed_at=datasource.last_processed_at,
        processing_time=datasource.processing_time,
        record_count=datasource.record_count,
        created_at=datasource.created_at,
        updated_at=datasource.updated_at
    )


@router.delete("/{datasource_id}")
async def delete_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Delete a specific datasource"""
    user = await get_current_user_required(request)
    
    # Get datasource
    stmt = select(Datasource).where(Datasource.id == datasource_id)
    result = await db.execute(stmt)
    datasource = result.scalar_one_or_none()
    
    if not datasource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datasource not found"
        )
    
    # Check permissions through channel
    if not datasource.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to datasource"
        )
    
    if datasource.is_embedding_required and datasource.giggso_vault_id:
        try:
            # Get vault_unique_id from gg_vault table
            vault_stmt = select(GiggsoVault).where(GiggsoVault.giggso_vault_id == datasource.giggso_vault_id)
            vault_result = await db.execute(vault_stmt)
            vault_record = vault_result.scalar_one_or_none()
            
            if not vault_record or not vault_record.vault_unique_id:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Vault record not found for datasource. Cannot delete embeddings."
                )
            
            # Determine embedding type based on file type, storage type, and provider
            from app.services.ml_service import get_embedd_type_from_file_type
            embedding_type = get_embedd_type_from_file_type(
                file_type=datasource.file_type,
                storage_type=datasource.storage_type,
                provider=datasource.provider
            )
            
            # Extract JWT token from Authorization header (if available)
            auth_header = request.headers.get("Authorization")
            jwt_token = None
            if auth_header and auth_header.startswith("Bearer "):
                jwt_token = auth_header.split(" ")[1]
            
            logger.info(f"Deleting embeddings for datasource {datasource_id}, embedding_type: {embedding_type}")
            
            # Call ML API to delete embeddings
            delete_result = await ml_service.delete_embeddings(
                channel_id=str(datasource.channel_id),
                data_sources_vault_tokens=[vault_record.vault_unique_id],
                embedding_type=embedding_type,
                jwt_token=jwt_token
            )
            
            # If delete embeddings API call failed, fail the entire deletion
            if not delete_result.get("success", False):
                error_message = delete_result.get("error") or delete_result.get("message", "Unknown error")
                logger.error(f"Failed to delete embeddings for datasource {datasource_id}: {error_message}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to delete embeddings: {error_message}"
                )
            
            logger.info(f"Successfully deleted embeddings for datasource {datasource_id}")
            
        except HTTPException:
            # Re-raise HTTPException (already formatted)
            raise
        except Exception as e:
            logger.error(f"Error deleting embeddings for datasource {datasource_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete embeddings: {str(e)}"
            )
    
    await db.delete(datasource)
    await db.commit()
    
    return {"message": "Datasource deleted successfully"}


@router.post("/process", response_model=DatasourceProcessingResponse)
async def process_datasources(
    processing_request: DatasourceProcessingRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Process datasources in background"""
    user = await get_current_user_required(request)
    
    # Get datasource
    stmt = select(Datasource).where(Datasource.id == processing_request.datasource_id)
    result = await db.execute(stmt)
    datasource = result.scalar_one_or_none()
    
    if not datasource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datasource not found"
        )
    
    # Check permissions through channel
    if not datasource.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to datasource"
        )
    
    # Add background task
    background_tasks.add_task(
        process_datasource_background,
        processing_request.datasource_id
    )
    
    return DatasourceProcessingResponse(
        datasource_id=processing_request.datasource_id,
        status="processing_started",
        message="Datasource processing started in background"
    )


async def process_datasource_background(datasource_id: str):
    """Background task to process datasource"""
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get datasource
            stmt = select(Datasource).where(Datasource.id == datasource_id)
            result = await db.execute(stmt)
            datasource = result.scalar_one_or_none()
            
            if not datasource:
                return
            
            # Mark as processing
            datasource.mark_processing_started()
            await db.commit()
            
            # Close session before long operation
            await db.close()
            
            # Simulate processing (replace with actual processing logic)
            await asyncio.sleep(5)
            
            # Create new session for final operations
            async with AsyncSessionLocal() as db:
                stmt = select(Datasource).where(Datasource.id == datasource_id)
                result = await db.execute(stmt)
                datasource = result.scalar_one_or_none()
                
                if datasource:
                    # Mark as completed
                    datasource.mark_processing_completed(record_count=100, processing_time=5000)
                    await db.commit()
            
        except Exception as e:
            # Create new session for error handling
            async with AsyncSessionLocal() as db:
                stmt = select(Datasource).where(Datasource.id == datasource_id)
                result = await db.execute(stmt)
                datasource = result.scalar_one_or_none()
                
                if datasource:
                    datasource.mark_processing_failed(str(e))
                    await db.commit()


async def process_embedding_background(
    vault_unique_ids: List[str], 
    user_id: str, 
    company_id: str, 
    db
):
    """Background task to process embedding for datasources"""
    import logging
    from sqlalchemy import select
    from app.models.datasource import Datasource
    from app.models.giggso_vault import GiggsoVault
    from app.services.ml_service import get_embedd_type_from_file_type
    
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 80)
    logger.info("🚀 STARTING EMBEDDING BACKGROUND PROCESSING")
    logger.info("=" * 80)
    logger.info(f"📋 Vault Unique IDs: {vault_unique_ids}")
    logger.info(f"👤 User ID: {user_id}")
    logger.info(f"🏢 Company ID: {company_id}")
    logger.info(f"📊 Total Datasources: {len(vault_unique_ids)}")
    logger.info("=" * 80)
    
    try:
        # Get file types, storage types, and providers from datasources to determine embedd_type
        embedd_type = "textual"  # Default
        datasources = []
        
        if vault_unique_ids:
            # Query datasources by vault_unique_ids to get file types, storage types, and providers
            stmt = select(Datasource).join(GiggsoVault, Datasource.giggso_vault_id == GiggsoVault.giggso_vault_id).where(
                GiggsoVault.vault_unique_id.in_(vault_unique_ids)
            )
            result = await db.execute(stmt)
            datasources = result.scalars().all()
            
            if datasources:
                # Determine embedd_type for each datasource
                embedd_types = []
                for ds in datasources:
                    embedd_type_item = get_embedd_type_from_file_type(
                        file_type=ds.file_type,
                        storage_type=ds.storage_type,
                        provider=ds.provider
                    )
                    embedd_types.append(embedd_type_item)
                
                if embedd_types:
                    # Extract base types (remove provider suffix for comparison)
                    base_types = [et.split("_")[0] for et in embedd_types]
                    
                    if all(bt == "tabular" for bt in base_types):
                        # All are tabular - check if they're all database with same provider
                        database_datasources = [ds for ds in datasources if ds.storage_type == "database" and ds.provider]
                        if len(database_datasources) == len(datasources):
                            # All are database datasources
                            providers = [ds.provider.lower() for ds in database_datasources if ds.provider]
                            if len(set(providers)) == 1:
                                # All same database provider
                                embedd_type = f"tabular_{providers[0]}"
                            else:
                                # Mixed database providers - use first one
                                embedd_type = f"tabular_{providers[0]}" if providers else "tabular"
                        else:
                            # Mixed tabular types (files + databases or different providers)
                            embedd_type = "tabular"
                    else:
                        # Default to textual if mixed types or any textual files
                        embedd_type = "textual"
                
                logger.debug(f"Determined embedd_type: {embedd_type} based on {len(datasources)} datasources")
                
                # Extract table_name from first datasource metadata that has it (for database datasources)
                table_name = None
                for ds in datasources:
                    if ds.datasource_metadata and isinstance(ds.datasource_metadata, dict):
                        table_name = ds.datasource_metadata.get("tableName")
                        if table_name:
                            break
        
        # Fetch OpenAI vault token (gpt_token) for company to send to ML API
        openai_vault_token = await get_openai_vault_token_for_company(db, company_id)
        # Call ML API to request embedding processing
        logger.info("🔄 Calling ML API for embedding processing...")
        table_names = extract_table_names_from_datasources(datasources) if len(datasources) > 1 else None
        result = await ml_service.request_embedding_processing(
            vault_unique_ids=vault_unique_ids,
            user_id=user_id,
            company_id=company_id,
            channel_id="",  # Background task doesn't have channel_id context
            embedded_vault_unique_ids=[],
            embedd_type=embedd_type,
            table_name=table_name,
            table_names=table_names,
            openai_vault_token=openai_vault_token
        )
        
        logger.info("=" * 80)
        logger.info("📥 ML API CALL RESULT")
        logger.info("=" * 80)
        logger.info(f"✅ Success: {result['success']}")
        logger.info(f"📝 Message: {result['message']}")
        if 'data' in result:
            logger.info(f"📊 Data: {result['data']}")
        if 'error' in result:
            logger.info(f"❌ Error: {result['error']}")
        logger.info("=" * 80)
        
        if result["success"]:
            logger.info(f"✅ Successfully requested embedding processing for {len(vault_unique_ids)} datasources")
        else:
            logger.error(f"❌ Failed to request embedding processing: {result['message']}")
            logger.info("🔄 Status update to failed is handled by ML team via webhook...")
            # TODO: Status update to failed is handled by ML team via webhook
            # await update_embedding_status_batch(vault_unique_ids, 3, db)
            
    except Exception as e:
        logger.error("=" * 80)
        logger.error("💥 EMBEDDING BACKGROUND PROCESSING ERROR")
        logger.error("=" * 80)
        logger.error(f"❌ Error: {str(e)}")
        logger.error(f"🔍 Error Type: {type(e).__name__}")
        logger.error("🔄 Status update to failed is handled by ML team via webhook...")
        logger.error("=" * 80)
        # TODO: Status update to failed is handled by ML team via webhook
        # await update_embedding_status_batch(vault_unique_ids, 3, db)


def sanitize_datasource_metadata(metadata: dict) -> dict:
    """Remove sensitive credentials from datasource metadata for API responses"""
    if not metadata:
        return metadata
    
    # Create a copy to avoid modifying the original
    sanitized = metadata.copy()
    
    # Remove sensitive credential fields
    if 'credentials' in sanitized:
        credentials = sanitized['credentials'].copy() if sanitized['credentials'] else {}
        # Remove sensitive fields but keep structure
        sensitive_fields = ['access_key', 'secret_key', 'secret_access_key', 'password', 'token']
        for field in sensitive_fields:
            if field in credentials:
                del credentials[field]
        
        # Remove sensitive fields from additional_config if it exists
        if 'additional_config' in credentials and isinstance(credentials['additional_config'], dict):
            additional_config = credentials['additional_config'].copy()
            # Remove sensitive OAuth credentials
            sensitive_config_fields = ['client_id', 'client_secret', 'secret_key']
            for field in sensitive_config_fields:
                if field in additional_config:
                    del additional_config[field]
            credentials['additional_config'] = additional_config
        
        sanitized['credentials'] = credentials
    
    # Remove other potentially sensitive fields
    sensitive_metadata_fields = ['giggsoToken', 'api_key', 'private_key']
    for field in sensitive_metadata_fields:
        if field in sanitized:
            sanitized[field] = "***REDACTED***"
    
    return sanitized


async def get_openai_vault_token_for_company(db: AsyncSession, company_id: str) -> Optional[str]:
    """
    Fetch vault_unique_id from gg_vault for the company and vault_type='gpt_token'.
    Used as openaiVaultToken when calling the ML API (/shay/email/embeddings).
    """
    try:
        company_uuid = uuid.UUID(company_id) if isinstance(company_id, str) else company_id
    except (ValueError, TypeError):
        return None
    stmt = (
        select(GiggsoVault.vault_unique_id)
        .where(
            GiggsoVault.company_id == company_uuid,
            GiggsoVault.vault_type == "gpt_token",
        )
        .order_by(GiggsoVault.created_datetime.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return row if row else None


async def get_completed_embeddings_by_channel(channel_id: str, db: AsyncSession) -> List[str]:
    """Get vault_unique_ids of datasources with completed embeddings in a channel (channel-level scope)"""
    try:
        # Find datasources with completed embeddings (status = 2) in the channel
        # Exclude thread-level datasources (have thread_id in metadata) - those use thread scope
        stmt = select(GiggsoVault.vault_unique_id).join(
            Datasource, GiggsoVault.giggso_vault_id == Datasource.giggso_vault_id
        ).where(
            and_(
                Datasource.channel_id == channel_id,
                Datasource.embedding_status == 2,  # 2 = completed
                Datasource.is_embedding_required == True,
                # Channel-level: no thread_id in metadata, or metadata null
                or_(
                    Datasource.datasource_metadata.is_(None),
                    ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
                )
            )
        )
        result = await db.execute(stmt)
        vault_unique_ids = result.scalars().all()
        
        logger.info(f"Found {len(vault_unique_ids)} completed channel-level embeddings for channel {channel_id}")
        return list(vault_unique_ids)
        
    except Exception as e:
        logger.error(f"Error getting completed embeddings for channel {channel_id}: {e}")
        return []


async def get_completed_embeddings_by_thread(thread_id: str, db: AsyncSession) -> List[str]:
    """Get vault_unique_ids of datasources with completed embeddings in a thread (thread-level scope)"""
    try:
        # Find datasources with completed embeddings (status = 2) in this specific thread
        stmt = select(GiggsoVault.vault_unique_id).join(
            Datasource, GiggsoVault.giggso_vault_id == Datasource.giggso_vault_id
        ).where(
            and_(
                Datasource.embedding_status == 2,  # 2 = completed
                Datasource.is_embedding_required == True,
                Datasource.datasource_metadata.isnot(None),
                Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
                Datasource.datasource_metadata.op("->>")(literal("thread_id", type_=String())) == literal(str(thread_id), type_=String())
            )
        )
        result = await db.execute(stmt)
        vault_unique_ids = result.scalars().all()
        
        logger.info(f"Found {len(vault_unique_ids)} completed thread-level embeddings for thread {thread_id}")
        return list(vault_unique_ids)
        
    except Exception as e:
        logger.error(f"Error getting completed embeddings for thread {thread_id}: {e}")
        return []


async def update_embedding_status_batch(vault_unique_ids: List[str], status: int, db: AsyncSession):
    """Update embedding status for a batch of datasources by vault_unique_id"""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 80)
    logger.info("🔄 UPDATING EMBEDDING STATUS BATCH")
    logger.info("=" * 80)
    logger.info(f"📋 Vault Unique IDs: {vault_unique_ids}")
    logger.info(f"📊 Status: {status} ({'Not Required' if status == 0 else 'In Progress' if status == 1 else 'Completed' if status == 2 else 'Failed'})")
    logger.info("=" * 80)
    
    try:
        # Find datasources by vault_unique_id in metadata
        logger.info("🔍 Finding datasources by vault_unique_id in metadata...")
        stmt = select(Datasource).where(
            Datasource.datasource_metadata.op("->>")(literal("vault_unique_id", type_=String())).in_(vault_unique_ids)
        )
        result = await db.execute(stmt)
        datasources = result.scalars().all()
        
        logger.info(f"📊 Found {len(datasources)} datasources to update")
        
        # Update embedding status
        for datasource in datasources:
            old_status = datasource.embedding_status
            datasource.embedding_status = status
            if status == 3:  # Failed
                datasource.error_message = "Embedding processing failed"
            logger.info(f"📝 Updated datasource {datasource.id}: {old_status} -> {status}")
        
        await db.commit()
        logger.info(f"✅ Successfully updated embedding status to {status} for {len(datasources)} datasources")
        
    except Exception as e:
        logger.error("=" * 80)
        logger.error("💥 ERROR UPDATING EMBEDDING STATUS")
        logger.error("=" * 80)
        logger.error(f"❌ Error: {str(e)}")
        logger.error(f"🔍 Error Type: {type(e).__name__}")
        logger.error("🔄 Rolling back database transaction...")
        logger.error("=" * 80)
        await db.rollback()


@router.post("/bulk-connection", response_model=DatasourceBulkConnectionResponse)
async def bulk_manage_datasource_connections(
    connection_request: DatasourceConnectionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Bulk connect or disconnect multiple datasources
    
    This unified endpoint handles both connection and disconnection operations
    for multiple datasources in a single request, with optimized permission checking
    and batch processing.
    """
    user = await get_current_user_required(request)
    action = connection_request.action.lower()
    
    # Validate action
    if action not in ["connect", "disconnect"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid action. Must be 'connect' or 'disconnect'"
        )
    
    # Get all datasources in a single query for efficiency
    stmt = select(Datasource).where(Datasource.id.in_(connection_request.datasource_ids))
    result = await db.execute(stmt)
    datasources = result.scalars().all()
    
    # Check if all datasources exist
    found_ids = {str(ds.id) for ds in datasources}
    missing_ids = set(connection_request.datasource_ids) - found_ids
    
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Datasources not found: {', '.join(missing_ids)}"
        )
    
    successful_operations = []
    failed_operations = []
    
    # Process each datasource
    for datasource in datasources:
        try:
            # Check permissions through channel
            if not datasource.is_accessible_by_user(user.company_id, user.role):
                failed_operations.append({
                    "datasource_id": str(datasource.id),
                    "error": "Access denied to datasource",
                    "status_code": 403
                })
                continue
            
            # Check current connection status
            if action == "connect":
                if datasource.is_connected:
                    failed_operations.append({
                        "datasource_id": str(datasource.id),
                        "error": "Datasource is already connected",
                        "status_code": 400
                    })
                    continue
                # Connect the datasource
                datasource.is_connected = True
                message = "Datasource connected successfully"
            else:  # disconnect
                if not datasource.is_connected:
                    failed_operations.append({
                        "datasource_id": str(datasource.id),
                        "error": "Datasource is already disconnected",
                        "status_code": 400
                    })
                    continue
                # Disconnect the datasource
                datasource.is_connected = False
                message = "Datasource disconnected successfully"
            
            # Update timestamp
            datasource.updated_at = datetime.utcnow()
            
            # Add to successful operations
            successful_operations.append(DatasourceConnectionResponse(
                datasource_id=str(datasource.id),
                is_connected=datasource.is_connected,
                message=message,
                updated_at=datasource.updated_at
            ))
            
        except Exception as e:
            failed_operations.append({
                "datasource_id": str(datasource.id),
                "error": str(e),
                "status_code": 500
            })
    
    # Commit all changes if there are successful operations
    if successful_operations:
        await db.commit()
    
    # Build response
    total_successful = len(successful_operations)
    total_failed = len(failed_operations)
    
    response_message = f"Successfully {action}ed {total_successful} datasource(s)"
    if total_failed > 0:
        response_message += f", {total_failed} operation(s) failed"
    
    return DatasourceBulkConnectionResponse(
        successful_operations=successful_operations,
        failed_operations=failed_operations,
        total_successful=total_successful,
        total_failed=total_failed,
        action_performed=action,
        message=response_message
    )


@router.post("/{datasource_id}/connect", response_model=DatasourceConnectionResponse)
async def connect_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Connect a datasource to the topic level (Legacy single operation endpoint)"""
    user = await get_current_user_required(request)
    
    # Get datasource
    stmt = select(Datasource).where(Datasource.id == datasource_id)
    result = await db.execute(stmt)
    datasource = result.scalar_one_or_none()
    
    if not datasource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datasource not found"
        )
    
    # Check permissions through channel
    if not datasource.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to datasource"
        )
    
    # Check if datasource is already connected
    if datasource.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Datasource is already connected"
        )
    
    # Connect the datasource
    datasource.is_connected = True
    datasource.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(datasource)
    
    return DatasourceConnectionResponse(
        datasource_id=str(datasource.id),
        is_connected=datasource.is_connected,
        message="Datasource connected successfully",
        updated_at=datasource.updated_at
    )


@router.post("/{datasource_id}/disconnect", response_model=DatasourceConnectionResponse)
async def disconnect_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Disconnect a datasource from the topic level (Legacy single operation endpoint)"""
    user = await get_current_user_required(request)
    
    # Get datasource
    stmt = select(Datasource).where(Datasource.id == datasource_id)
    result = await db.execute(stmt)
    datasource = result.scalar_one_or_none()
    
    if not datasource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datasource not found"
        )
    
    # Check permissions through channel
    if not datasource.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to datasource"
        )
    
    # Check if datasource is already disconnected
    if not datasource.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Datasource is already disconnected"
        )
    
    # Disconnect the datasource
    datasource.is_connected = False
    datasource.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(datasource)
    
    return DatasourceConnectionResponse(
        datasource_id=str(datasource.id),
        is_connected=datasource.is_connected,
        message="Datasource disconnected successfully",
        updated_at=datasource.updated_at
    )


@router.get("/{datasource_id}/connection-status", response_model=DatasourceConnectionResponse)
async def get_datasource_connection_status(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get the connection status of a datasource"""
    user = await get_current_user_required(request)
    
    # Get datasource
    stmt = select(Datasource).where(Datasource.id == datasource_id)
    result = await db.execute(stmt)
    datasource = result.scalar_one_or_none()
    
    if not datasource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datasource not found"
        )
    
    # Check permissions through channel
    if not datasource.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to datasource"
        )
    
    status_message = "connected" if datasource.is_connected else "disconnected"
    
    return DatasourceConnectionResponse(
        datasource_id=str(datasource.id),
        is_connected=datasource.is_connected,
        message=f"Datasource is {status_message}",
        updated_at=datasource.updated_at
    )


@router.get("/embedding-status/{channel_id}", response_model=EmbeddingStatusResponse)
async def get_embedding_status_by_channel(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    thread_id: Optional[str] = Query(
        None,
        description="Filter by thread ID. When set, returns embedding status only for thread-level datasources (e.g. email attachments in that thread). When omitted, returns channel-level datasources only."
    )
):
    """Get embedding status for datasources in a channel. Pass thread_id to get status for thread-level datasources (email attachments) only."""
    user = await get_current_user_required(request)
    
    # Check channel access - user must be super admin or channel member
    await check_channel_access(db, user, channel_id)
    
    # Get channel
    stmt = select(Channel).where(Channel.id == channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )
    
    # When thread_id is passed: return only thread-level datasources for that thread (e.g. email attachments)
    # Same behaviour as GET /datasources/?channel_id=...&thread_id=...
    if thread_id:
        try:
            thread_uuid = uuid.UUID(thread_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid thread_id format: {thread_id}"
            )
        await check_channel_access_by_thread(db, user, thread_id)
        # For thread-level datasources: get all datasources for the thread, then filter to keep only latest per filename
        stmt = select(Datasource).where(
            and_(
                Datasource.channel_id == channel_id,
                Datasource.datasource_metadata.isnot(None),
                Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
                Datasource.datasource_metadata.op("->>")(literal("thread_id", type_=String())) == literal(str(thread_uuid), type_=String())
            )
        ).order_by(desc(Datasource.created_at))  # Order by created_at DESC to get latest first
        result = await db.execute(stmt)
        all_datasources = result.scalars().all()
        
        # Group by filename and keep only the latest one (first in DESC order)
        seen_filenames = {}
        datasources = []
        for ds in all_datasources:
            filename_key = ds.filename or ds.name or "unknown"  # Use filename as key, fallback to name
            if filename_key not in seen_filenames:
                seen_filenames[filename_key] = True
                datasources.append(ds)  # Keep only the first (latest) occurrence
    else:
        # Get only channel-level datasources (exclude thread-level e.g. email attachments)
        # Thread-level datasources have datasource_metadata.thread_id set
        stmt = select(Datasource).where(
            and_(
                Datasource.channel_id == channel_id,
                or_(
                    Datasource.datasource_metadata.is_(None),
                    ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
                )
            )
        )
        result = await db.execute(stmt)
        datasources = result.scalars().all()

    # Categorize datasources by embedding status
    total_datasources = len(datasources)
    embedding_required = 0
    in_progress = 0
    completed = 0
    failed = 0
    not_required = 0
    
    datasource_list = []
    
    for ds in datasources:
        if ds.is_embedding_required:
            embedding_required += 1
        
        if ds.embedding_status == 0:
            not_required += 1
        elif ds.embedding_status == 1:
            in_progress += 1
        elif ds.embedding_status == 2:
            completed += 1
        elif ds.embedding_status == 3:
            failed += 1
        
        datasource_list.append({
            "id": str(ds.id),
            "name": ds.name,
            "filename": ds.filename,
            "is_embedding_required": ds.is_embedding_required,
            "embedding_status": ds.embedding_status,
            "error_message": ds.error_message,
            "created_at": ds.created_at,
            "updated_at": ds.updated_at
        })
    
    return EmbeddingStatusResponse(
        channel_id=channel_id,
        total_datasources=total_datasources,
        embedding_required=embedding_required,
        in_progress=in_progress,
        completed=completed,
        failed=failed,
        not_required=not_required,
        datasources=datasource_list
    )


@router.post("/embedding/webhook", response_model=MLWebhookResponse)
async def ml_embedding_webhook(
    webhook_data: MLWebhookRequest,
    db: AsyncSession = Depends(get_db)
):
    """Webhook endpoint for ML team to report embedding completion status"""
    try:
        # TODO: Temporarily commented out status update logic
        # Update embedding status for the provided vault_unique_ids
        # vault_unique_ids = webhook_data.vaultUniqueIds
        # status = 2 if webhook_data.status == "success" else 3  # 2=completed, 3=failed
        
        # # Find datasources by vault_unique_id in metadata
        # # We need to search in the datasource_metadata JSONB field
        # stmt = select(Datasource).where(
        #     Datasource.datasource_metadata['vault_unique_id'].astext.in_(vault_unique_ids)
        # )
        # result = await db.execute(stmt)
        # datasources = result.scalars().all()
        
        # processed_count = 0
        # failed_count = 0
        
        # for datasource in datasources:
        #     try:
        #         datasource.embedding_status = status
        #         if status == 3:  # Failed
        #             datasource.error_message = webhook_data.error_message or "Embedding processing failed"
        #         else:  # Success
        #             datasource.error_message = None
        #         processed_count += 1
        #     except Exception as e:
        #         print(f"Error updating datasource {datasource.id}: {str(e)}")
        #         failed_count += 1
        
        # await db.commit()
        
        # message = f"Successfully updated {processed_count} datasources"
        # if failed_count > 0:
        #     message += f", {failed_count} updates failed"
        
        # return MLWebhookResponse(
        #     message=message,
        #     processed_count=processed_count,
        #     failed_count=failed_count
        # )
        
        # Temporary response while status update is disabled
        return MLWebhookResponse(
            message="Webhook received but status update is temporarily disabled",
            processed_count=0,
            failed_count=0
        )
        
    except Exception as e:
        print(f"Error in ML webhook: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process webhook: {str(e)}"
        )




@router.post("/embedding/regenerate/{datasource_id}", response_model=RegenerateEmbeddingResponse)
async def regenerate_embedding(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Regenerate embedding for a specific datasource"""
    try:
        # Get current user from authentication
        user = await get_current_user_required(request)
        current_user_id = str(user.id)
        current_company_id = str(user.company_id)
        
        # Find the datasource
        stmt = select(Datasource).where(Datasource.id == datasource_id)
        result = await db.execute(stmt)
        datasource = result.scalar_one_or_none()
        
        if not datasource:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Datasource not found"
            )
        
        # Check if user has access to this datasource
        if str(datasource.added_by) != current_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to regenerate embedding for this datasource"
            )
        
        # Check if datasource has vault integration
        if not datasource.giggso_vault_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Datasource does not have vault integration. Cannot regenerate embedding."
            )
        
        # Get vault_unique_id from gg_vault table
        vault_stmt = select(GiggsoVault).where(GiggsoVault.giggso_vault_id == datasource.giggso_vault_id)
        vault_result = await db.execute(vault_stmt)
        vault_record = vault_result.scalar_one_or_none()
        
        if not vault_record or not vault_record.vault_unique_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Vault record not found. Cannot regenerate embedding."
            )
        
        # Update embedding status to "in progress"
        datasource.embedding_status = 1  # 1 = in progress
        await db.commit()
        
        logger.info("=" * 80)
        logger.info("🔄 REGENERATING EMBEDDING")
        logger.info("=" * 80)
        logger.info(f"📋 Datasource ID: {datasource_id}")
        logger.info(f"🔑 giggso_vault_id: {datasource.giggso_vault_id}")
        logger.info(f"📦 vault_unique_id: {vault_record.vault_unique_id}")
        logger.info(f"👤 User ID: {current_user_id}")
        logger.info(f"🏢 Company ID: {current_company_id}")
        logger.info("=" * 80)
        
        # Determine embedd_type based on file type
        from app.services.ml_service import get_embedd_type_from_file_type
        embedd_type = get_embedd_type_from_file_type(
            file_type=datasource.file_type,
            storage_type=datasource.storage_type,
            provider=datasource.provider
        )
        
        logger.debug(f"Determined embedd_type: {embedd_type} for file_type: {datasource.file_type}, storage_type: {datasource.storage_type}, provider: {datasource.provider}")
        
        # Extract table_name from datasource metadata (for database datasources)
        table_name = None
        if datasource.datasource_metadata and isinstance(datasource.datasource_metadata, dict):
            table_name = datasource.datasource_metadata.get("tableName")
        
        # Get completed embeddings for this channel
        embedded_vault_unique_ids = await get_completed_embeddings_by_channel(str(datasource.channel_id), db)
        
        # Extract JWT token from Authorization header
        auth_header = request.headers.get("Authorization")
        jwt_token = None
        if auth_header and auth_header.startswith("Bearer "):
            jwt_token = auth_header.split(" ")[1]
        
        # Fetch OpenAI vault token (gpt_token) for company to send to ML API
        openai_vault_token = await get_openai_vault_token_for_company(db, current_company_id)
        # Call ML service directly
        try:
            table_names = extract_table_names_from_datasources([datasource]) if table_name is None else None
            result = await ml_service.request_embedding_processing(
                vault_unique_ids=[vault_record.vault_unique_id],
                user_id=current_user_id,
                company_id=current_company_id,
                channel_id=str(datasource.channel_id),
                embedded_vault_unique_ids=embedded_vault_unique_ids,
                jwt_token=jwt_token,
                embedd_type=embedd_type,
                table_name=table_name,
                table_names=table_names,
                openai_vault_token=openai_vault_token
            )
            
            # Emit socket event based on ML API response
            socket_service = get_socket_service()
            if socket_service.is_socket_connected():
                # Determine status based on ML API response
                ml_status = 2 if result.get("success") else 3  # 2 = success, 3 = failure
                
                socket_event_data = {
                    "type": 16,
                    "data": {
                        "channelId": str(datasource.channel_id),
                        "status": ml_status,
                        "datasourceId": datasource_id
                    }
                }
                
                try:
                    await socket_service.emit("shay_realtime", socket_event_data)
                    logger.info(f"✅ Emitted socket event for datasource {datasource_id}: status={ml_status}")
                except Exception as socket_error:
                    logger.error(f"❌ Failed to emit socket event for datasource {datasource_id}: {socket_error}")
            
            if result.get("success"):
                logger.info("✅ ML API call successful - embedding processing initiated")
            else:
                logger.error(f"❌ ML API call failed: {result.get('message', 'Unknown error')}")
                # TODO: Status update to failed is handled by ML team via webhook
                # datasource.embedding_status = 3  # 3 = failed
                # await db.commit()
                
        except Exception as e:
            logger.error(f"❌ Error calling ML API: {e}")
            
            # Emit socket event for failure
            socket_service = get_socket_service()
            if socket_service.is_socket_connected():
                socket_event_data = {
                    "type": 16,
                    "data": {
                        "channelId": str(datasource.channel_id),
                        "status": 3,  # 3 = failure
                        "datasourceId": datasource_id
                    }
                }
                
                try:
                    await socket_service.emit("shay_realtime", socket_event_data)
                    logger.info(f"✅ Emitted socket event for datasource {datasource_id}: status=3 (failure)")
                except Exception as socket_error:
                    logger.error(f"❌ Failed to emit socket event for datasource {datasource_id}: {socket_error}")
            
            # TODO: Status update to failed is handled by ML team via webhook
            # datasource.embedding_status = 3  # 3 = failed
            # await db.commit()
        
        return RegenerateEmbeddingResponse(
            success=True,
            message="Embedding regeneration initiated successfully",
            datasource_id=datasource_id,
            embedding_status=1,
            status_description="in_progress"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Regenerate embedding error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to regenerate embedding: {str(e)}"
        )

 