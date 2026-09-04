"""
Shared helpers for datasource routes.

Private module: these are implementation details used by the sibling
``app.routes.datasources`` submodules (crud, upload, bulk, processing,
connections, embedding). Anything imported from outside this package
(e.g. app/routes/gg_datasources.py) is re-exported from
``app/routes/datasources/__init__.py``.
"""

import base64
import json as _json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

from fastapi import HTTPException, status
from sqlalchemy import String, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import literal

from app.models.datasource import Datasource
from app.models.giggso_vault import GiggsoVault
from app.routes.aryx import call_aryx_job_status
from app.services.vault_service import vault_service

logger = logging.getLogger(__name__)


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


async def update_embedding_status_batch(vault_unique_ids: List[str], status: int, db: AsyncSession) -> None:
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
