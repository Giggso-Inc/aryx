"""
Azure Blob download-with-vault-credentials helper for datasource downloads.

Private module: used by processing.py's download endpoint.
"""

import logging
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


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
