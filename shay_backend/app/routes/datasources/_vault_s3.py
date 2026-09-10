"""
S3 download-with-vault-credentials helper for datasource downloads.

Private module: used by processing.py's download endpoint.
"""

import logging
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


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
