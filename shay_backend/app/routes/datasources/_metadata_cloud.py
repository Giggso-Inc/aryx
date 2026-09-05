"""
Metadata-dict builder for storage_type="cloud" (aws/azure/oracle/gcp) datasources.

Private module: called only by _metadata_generator.generate_datasource_metadata.
Split out verbatim from the original monolithic function so each storage-type
branch can live in its own file; the dict contents/keys are unchanged.

Stated exception (179 lines): same rationale as _metadata_database.py — one
literal dict of ~60 fixed metadata keys, plus the per-provider (aws/azure/
oracle/gcp) location-string derivation that feeds it; fragmenting the dict
literal itself would risk a silent key/value drift versus the original.
"""

from typing import Any, Dict, Optional


def build_cloud_metadata(
    *,
    filename: str,
    channel_id: str,
    workspace_id: str,
    user_id: str,
    file_size: int,
    file_type: str,
    provider: Optional[str],
    app_type: Optional[str],
    log_type: Optional[str],
    config: Optional[Dict[str, Any]],
    file_url: Optional[str],
    is_embedding_required: bool,
    file_format: str,
    unique_filename: str,
    giggs_token: str,
) -> Dict[str, Any]:
    """Build the raw (uncleaned) metadata dict for a cloud-storage datasource."""
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
    return metadata
