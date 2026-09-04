"""
Datasource create/update request schemas and the shared storage config model.

Split out of the former app/schemas/datasource.py during Phase 5a
file-size compliance work. See app/schemas/datasource/__init__.py for the
full package layout and re-export list.
"""

from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, field_validator


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


class DatasourceCreate(BaseModel):
    """Single datasource creation request"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    filename: Optional[str] = Field(None, max_length=500)
    storage_type: str = Field(..., pattern="^(local|cloud|app|database)$")
    provider: Optional[str] = None  # s3, azure, etc.
    app_provider: Optional[str] = None  # pipedream, etc. for app storage
    app_type: Optional[str] = None  # googleDrive, sharePoint, etc.
    config: Optional[DatasourceConfig] = None
    datasource_metadata: Optional[Dict[str, Any]] = None
    channel_id: str
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    file_url: Optional[str] = None
    location: Optional[str] = Field(None, description="Cloud storage location URL (for cloud storage type)")
    accessToken: Optional[str] = Field(None, description="Access token for cloud storage (for cloud storage type)")
    log_type: Optional[str] = Field(None, description="Type of log (e.g., android, kubernetes, python)")
    is_embedding_required: Optional[bool] = Field(False, description="Whether embedding is required for this datasource")

    @field_validator('filename')
    @classmethod
    def validate_filename(cls, v, info) -> Optional[str]:
        """Validate filename based on storage type"""
        storage_type = info.data.get('storage_type')

        # For local storage, filename is required
        if storage_type == 'local' and not v:
            raise ValueError('filename is required for local storage')

        # For cloud storage, filename is optional (can be extracted from URL)
        if storage_type == 'cloud' and not v:
            # Check if we have file_url to extract filename
            file_url = info.data.get('file_url')
            if not file_url:
                raise ValueError('Either filename or file_url is required for cloud storage')

        # For app storage, filename is optional (will be handled in code)
        # No validation needed - empty/null filenames are handled in the bulk API

        return v


class DatasourceBulkCreate(BaseModel):
    """Bulk datasource creation request"""
    datasources: List[DatasourceCreate] = Field(..., min_items=1, max_items=100)


class DatasourceCreateInternal(BaseModel):
    """Single datasource creation request for internal API (thread-level)"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    filename: Optional[str] = Field(None, max_length=500)
    storage_type: str = Field(..., pattern="^(local|cloud|app|database)$")
    provider: Optional[str] = None  # s3, azure, etc.
    app_provider: Optional[str] = None  # pipedream, etc. for app storage
    app_type: Optional[str] = None  # googleDrive, sharePoint, etc.
    config: Optional[DatasourceConfig] = None
    datasource_metadata: Optional[Dict[str, Any]] = None
    thread_id: str  # Thread ID instead of channel_id
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    file_url: Optional[str] = None
    location: Optional[str] = Field(None, description="Cloud storage location URL (for cloud storage type)")
    accessToken: Optional[str] = Field(None, description="Access token for cloud storage (for cloud storage type)")
    log_type: Optional[str] = Field(None, description="Type of log (e.g., android, kubernetes, python)")
    is_embedding_required: Optional[bool] = Field(False, description="Whether embedding is required for this datasource")

    @field_validator('filename')
    @classmethod
    def validate_filename(cls, v, info) -> Optional[str]:
        """Validate filename based on storage type"""
        storage_type = info.data.get('storage_type')

        # For local storage, filename is required
        if storage_type == 'local' and not v:
            raise ValueError('filename is required for local storage')

        # For cloud storage, filename is optional (can be extracted from URL)
        if storage_type == 'cloud' and not v:
            # Check if we have file_url to extract filename
            file_url = info.data.get('file_url')
            if not file_url:
                raise ValueError('Either filename or file_url is required for cloud storage')

        # For app storage, filename is optional (will be handled in code)
        # No validation needed - empty/null filenames are handled in the bulk API

        return v


class DatasourceBulkCreateInternal(BaseModel):
    """Bulk datasource creation request for internal API (thread-level)"""
    datasources: List[DatasourceCreateInternal] = Field(..., min_items=1, max_items=100)


class DatasourceUpdate(BaseModel):
    """Datasource update request"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    log_type: Optional[str] = Field(None, description="Type of log (e.g., android, kubernetes, python)")
    is_active: Optional[bool] = None
    is_connected: Optional[bool] = None
    config: Optional[DatasourceConfig] = None
    datasource_metadata: Optional[Dict[str, Any]] = None
