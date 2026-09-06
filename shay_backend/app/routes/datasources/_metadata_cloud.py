"""
Metadata-dict builder for storage_type="cloud" (aws/azure/oracle/gcp) datasources.

Private module: called only by _metadata_generator.generate_datasource_metadata.
Split out verbatim from the original monolithic function so each storage-type
branch can live in its own file; the dict contents/keys are unchanged.

The per-provider location/credential derivation is further extracted to
_metadata_cloud_location.py (Raven style-compliance, wave B4) — what remains
here is the single literal dict of ~60 fixed metadata keys, which stays
together to avoid any silent key/value drift versus the original.
"""

from typing import Any, Dict, Optional

from ._metadata_cloud_location import derive_cloud_location_and_credentials


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
    local_files = []
    location, access_key, access_token = derive_cloud_location_and_credentials(provider, config, file_url)

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
