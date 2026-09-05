"""
GCP Cloud Storage download-with-vault-credentials helper for datasource downloads.

Private module: used by processing.py's download endpoint.
"""

import base64
import json as _json
import logging
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


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
