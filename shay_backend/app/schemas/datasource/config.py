"""
Shared datasource storage-config model.

Split out of the former app/schemas/datasource/core.py during Phase 5b
file-size compliance work. See app/schemas/datasource/__init__.py for the
full package layout and re-export list.
"""

from typing import Optional, Dict, Any

from pydantic import BaseModel


class DatasourceConfig(BaseModel):
    """Configuration for different storage types"""

    # For cloud storage
    bucket_name: Optional[str] = None
    region: Optional[str] = None
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    secret_access_key: Optional[str] = None  # For Azure

    # For GCP Cloud Storage
    file_path: Optional[str] = None  # GCP file path within bucket
    service_account_json: Optional[str] = None  # GCP service account JSON (base64 encoded or raw JSON string)
    project_id: Optional[str] = None  # GCP project ID

    # For app storage
    app_id: Optional[str] = None
    folder_id: Optional[str] = None
    file_id: Optional[str] = None
    connection_id: Optional[str] = None  # ID of app_account to fetch refresh_token from
    connection_settings: Optional[Dict[str, Any]] = None  # For app storage (Google Drive, etc.)

    # For local storage
    file_path: Optional[str] = None

    # For database storage
    username: Optional[str] = None
    password: Optional[str] = None
    hostname: Optional[str] = None
    port: Optional[str] = None
    databaseName: Optional[str] = None
    schemaName: Optional[str] = None
    tableName: Optional[str] = None
    collectionName: Optional[str] = None
    serviceName: Optional[str] = None
    accountId: Optional[str] = None
    warehouse: Optional[str] = None
    regionName: Optional[str] = None
    accessKeyId: Optional[str] = None
    secretAccessKey: Optional[str] = None

    # Additional configuration
    additional_config: Optional[Dict[str, Any]] = None
