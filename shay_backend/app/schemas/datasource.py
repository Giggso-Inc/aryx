"""
Datasource schemas for request/response validation
"""

from datetime import datetime
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
    def validate_filename(cls, v, info):
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
    def validate_filename(cls, v, info):
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


class DatasourceResponse(BaseModel):
    """Datasource response schema"""
    id: str
    name: str
    filename: str
    storage_type: str
    provider: Optional[str] = None
    app_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    datasource_metadata: Optional[Dict[str, Any]] = None
    giggso_vault_id: Optional[str] = None  # Reference to gg_vault table (UUID)
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    file_url: Optional[str] = None
    log_type: Optional[str] = None
    channel_id: str
    workspace_id: str
    company_id: str
    added_by: str
    is_active: bool
    is_connected: bool
    is_processed: bool
    processing_status: str
    error_message: Optional[str] = None
    last_processed_at: Optional[datetime] = None
    processing_time: Optional[int] = None
    record_count: int
    is_embedding_required: bool
    embedding_status: int
    created_at: datetime
    updated_at: datetime
    aryx_ingestion_status: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Present only when this datasource's datasource_metadata carries an "
            "aryx.discovery_id (linked via a kind='aryx' upload) — live Aryx job "
            "status merged in at read time: {status, stage, pct, detail, ...} "
            "(same shape as Aryx's GET /admin/jobs/{id}). None for every datasource "
            "without that linkage — additive, backward compatible."
        ),
    )

    class Config:
        from_attributes = True


class DatasourceList(BaseModel):
    """Datasource list response schema"""
    datasources: List[DatasourceResponse]
    total: int
    page: int
    size: int


class DatasourceStats(BaseModel):
    """Datasource statistics response schema"""
    total_datasources: int
    active_datasources: int
    processed_datasources: int
    pending_datasources: int
    failed_datasources: int
    total_file_size: int
    storage_type_breakdown: Dict[str, int]
    provider_breakdown: Dict[str, int]


class DatasourceTypeCount(BaseModel):
    """Count response for a specific data source type"""
    type: str  # local, cloud, db, app
    count: int


class DatasourceTypeCountResponse(BaseModel):
    """Response schema for data source type count API"""
    counts: List[DatasourceTypeCount]
    total_connected: int


class DatasourceProcessingRequest(BaseModel):
    """Request to process datasources"""
    datasource_ids: List[str] = Field(..., min_items=1, max_items=50)


class DatasourceProcessingResponse(BaseModel):
    """Response for datasource processing"""
    message: str
    processed_count: int
    failed_count: int
    processing_jobs: List[str]


# Storage type specific schemas
class LocalDatasourceCreate(BaseModel):
    """Local storage datasource creation"""
    name: str = Field(..., min_length=1, max_length=255)
    filename: str = Field(..., min_length=1, max_length=500)
    file_path: str
    channel_id: str
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    log_type: Optional[str] = Field(None, description="Type of log (e.g., android, kubernetes, python)")


class CloudDatasourceCreate(BaseModel):
    """Cloud storage datasource creation"""
    name: str = Field(..., min_length=1, max_length=255)
    filename: str = Field(..., min_length=1, max_length=500)
    provider: str = Field(..., pattern="^(local|s3|azure|gcp|oracle)$")
    bucket_name: str
    region: Optional[str] = None
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    channel_id: str
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    file_url: Optional[str] = None
    log_type: Optional[str] = Field(None, description="Type of log (e.g., android, kubernetes, python)")


class AppDatasourceCreate(BaseModel):
    """App-based datasource creation"""
    name: str = Field(..., min_length=1, max_length=255)
    filename: str = Field(..., min_length=1, max_length=500)
    app_type: str = Field(..., pattern="^(googleDrive|sharePoint|dropbox|oneDrive)$")
    app_id: str
    folder_id: Optional[str] = None
    file_id: Optional[str] = None
    channel_id: str
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    file_url: Optional[str] = None
    log_type: Optional[str] = Field(None, description="Type of log (e.g., android, kubernetes, python)")


class DatasourceBulkResponse(BaseModel):
    """Bulk datasource creation response"""
    created_datasources: List[DatasourceResponse]
    failed_datasources: List[Dict[str, Any]]
    total_created: int
    total_failed: int 


# File upload schemas
class FileUploadResponse(BaseModel):
    """Response for file upload"""
    filename: str
    file_size: int
    file_type: str
    file_url: str
    storage_path: str
    provider: str
    aryx_ingestion: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Present only when the bulk-upload call passed kind='aryx' for this "
            "file — {'discovery_id': ...} on success or {'error': ...} on failure. "
            "None for every existing (non-Aryx) upload — additive, backward compatible."
        ),
    )


class FileUploadBulkResponse(BaseModel):
    """Response for bulk file upload"""
    uploaded_files: List[FileUploadResponse]
    failed_files: List[Dict[str, Any]]
    total_uploaded: int
    total_failed: int


class DatasourceFromUpload(BaseModel):
    """Create datasource from uploaded file"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    channel_id: str
    log_type: Optional[str] = Field(None, description="Type of log (e.g., android, kubernetes, python)")
    datasource_metadata: Optional[Dict[str, Any]] = None


class DatasourceFromUploadBulk(BaseModel):
    """Create multiple datasources from uploaded files"""
    datasources: List[DatasourceFromUpload] = Field(..., min_items=1, max_items=100)


class DatasourceConnectionResponse(BaseModel):
    """Response for datasource connection operations"""
    datasource_id: str
    is_connected: bool
    message: str
    updated_at: datetime


class DatasourceConnectionRequest(BaseModel):
    """Request for datasource connection operations"""
    datasource_ids: List[str] = Field(..., min_items=1, max_items=100, description="List of datasource IDs to connect/disconnect")
    action: str = Field(..., pattern="^(connect|disconnect)$", description="Action to perform: connect or disconnect")


class DatasourceBulkConnectionResponse(BaseModel):
    """Response for bulk datasource connection operations"""
    successful_operations: List[DatasourceConnectionResponse]
    failed_operations: List[Dict[str, Any]]
    total_successful: int
    total_failed: int
    action_performed: str
    message: str


class DatasourceWithRelationsResponse(BaseModel):
    """Datasource response schema with full user and channel objects"""
    id: str
    name: str
    filename: str
    storage_type: str
    provider: Optional[str] = None
    app_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    datasource_metadata: Optional[Dict[str, Any]] = None
    giggso_vault_id: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    file_url: Optional[str] = None
    log_type: Optional[str] = None
    channel: Dict[str, Any]  # Full channel object as dict
    added_by_user: Dict[str, Any]  # Full user object as dict
    is_active: bool
    is_connected: bool
    is_processed: bool
    processing_status: str
    error_message: Optional[str] = None
    last_processed_at: Optional[datetime] = None
    processing_time: Optional[int] = None
    record_count: int
    is_embedding_required: bool
    embedding_status: int
    created_at: datetime
    updated_at: datetime


class DatasourceListWithRelations(BaseModel):
    """Datasource list response schema with full user and channel objects"""
    datasources: List[DatasourceWithRelationsResponse]
    total: int
    page: int
    size: int
    pages: int


# Embedding related schemas
class EmbeddingStatusResponse(BaseModel):
    """Response schema for embedding status by channel"""
    channel_id: str
    total_datasources: int
    embedding_required: int  # Count of datasources requiring embedding
    in_progress: int  # Count of datasources with embedding_status = 1
    completed: int  # Count of datasources with embedding_status = 2
    failed: int  # Count of datasources with embedding_status = 3
    not_required: int  # Count of datasources with embedding_status = 0
    datasources: List[Dict[str, Any]]  # List of datasources with their embedding status


class MLWebhookRequest(BaseModel):
    """Webhook request from ML team for embedding completion status"""
    vaultUniqueIds: List[str] = Field(..., alias="vaultUniqueIds", description="List of vault_unique_ids that were processed")
    status: str = Field(..., pattern="^(success|failed)$", description="Overall status of the embedding process")
    message: Optional[str] = Field(None, description="Status message")
    processingTime: Optional[int] = Field(None, alias="processingTime", description="Processing time in milliseconds")
    
    class Config:
        allow_population_by_field_name = True


class MLWebhookResponse(BaseModel):
    """Response for ML webhook"""
    message: str
    processed_count: int
    failed_count: int


class RegenerateEmbeddingResponse(BaseModel):
    """Response model for regenerate embedding API"""
    success: bool
    message: str
    datasource_id: str
    embedding_status: int
    status_description: str


 