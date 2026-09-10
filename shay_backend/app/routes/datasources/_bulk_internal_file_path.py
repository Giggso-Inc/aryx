"""
vault_storage_type / file_path resolution for internal/bulk (email
attachment) datasources: local storage extracts the path straight from
file_url; cloud/S3 is treated as local for vault purposes with its file_path
extracted from the S3 URL.

Private module: used only by _bulk_internal_create_item.py.
"""

import logging
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)


def resolve_vault_storage_type_and_file_path(datasource_data):
    """Return (vault_storage_type, file_path) for internal/bulk vault enhancement."""
    vault_storage_type = datasource_data.storage_type
    file_path = None
    if datasource_data.storage_type == "local" and datasource_data.file_url:
        # Email backend sent storage_type=local (FILE_UPLOAD_ENV=local): extract path from file_url for vault
        try:
            parsed_url = urlparse(datasource_data.file_url)
            file_path = unquote(parsed_url.path.lstrip("/"))
            logger.info(f"[INTERNAL-BULK] Local storage: file_path from file_url: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to extract file_path from local file_url: {e}")
    elif datasource_data.storage_type == "cloud" and datasource_data.provider == "s3" and datasource_data.file_url:
        # Extract file_path from S3 URL (e.g., https://bucket.s3.amazonaws.com/path/to/file -> path/to/file)
        try:
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

    return vault_storage_type, file_path
