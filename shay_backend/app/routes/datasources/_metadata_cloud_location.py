"""
Per-provider (aws/azure/oracle/gcp) location-string + credential derivation
for cloud-storage datasource metadata.

Private module: called only by _metadata_cloud.build_cloud_metadata. Split
out of that file (Raven style-compliance, wave B4) — this branch-per-provider
logic is independent of the metadata dict literal it feeds, so extracting it
does not risk any key/value drift in the dict itself.
"""

from typing import Any, Dict, Optional, Tuple


def derive_cloud_location_and_credentials(
    provider: Optional[str],
    config: Optional[Dict[str, Any]],
    file_url: Optional[str],
) -> Tuple[str, str, str]:
    """Return (location, access_key, access_token) for a cloud-storage datasource."""
    access_key = ""
    access_token = ""
    location = ""

    # Extract location based on provider
    if provider == "aws":
        if config and "bucket_name" in config and "file_path" in config:
            location = f"s3://{config['bucket_name']}/{config['file_path']}"
        elif config and "file_url" in config:
            # Extract S3 path from URL
            cfg_file_url = config.get("file_url", "")
            if "s3.amazonaws.com" in cfg_file_url:
                # Convert S3 URL to s3:// format
                location = cfg_file_url.replace("https://", "s3://").replace(".s3.amazonaws.com/", "/")
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

    return location, access_key, access_token
