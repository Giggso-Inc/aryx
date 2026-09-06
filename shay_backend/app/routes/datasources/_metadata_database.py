"""
Metadata-dict builder for storage_type="database" datasources.

Private module: called only by _metadata_generator.generate_datasource_metadata.
Split out verbatim from the original monolithic function so each storage-type
branch can live in its own file; the dict contents/keys are unchanged.

The config-field extraction is further extracted to
_metadata_database_config.py (Raven style-compliance, wave B4) — what
remains here is the single literal dict of ~60 fixed metadata keys, which
stays together to avoid any silent key/value drift versus the original.
"""

from typing import Any, Dict, Optional

from ._metadata_database_config import extract_database_config_fields


def build_database_metadata(
    *,
    filename: str,
    channel_id: str,
    workspace_id: str,
    user_id: str,
    file_size: int,
    provider: Optional[str],
    log_type: Optional[str],
    config: Optional[Dict[str, Any]],
    is_embedding_required: bool,
    unique_filename: str,
    giggs_token: str,
) -> Dict[str, Any]:
    """Build the raw (uncleaned) metadata dict for a database-storage datasource."""
    # For database storage (MySQL, PostgreSQL, SQL Server, Oracle, MongoDB, DynamoDB, Redshift, Snowflake)
    # Provider contains the database type (mysql, postgresql, sqlserver, oracle, mongodb, dynamodb, redshift, snowflake)
    database_type = provider or "mysql"  # Default to mysql if not specified
    f = extract_database_config_fields(config)

    metadata = {
        "accessKey": "",
        "accessKeyId": f["access_key_id"] if database_type == "dynamodb" else None,
        "accessToken": "",
        "accountId": f["account_id"] if database_type == "snowflake" else "",
        "app": [],
        "appType": None,
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
        "databaseName": f["database_name"],
        "databaseType": database_type,  # mysql, postgresql, sqlserver, oracle, mongodb, dynamodb, redshift, snowflake
        "logFile": False,  # Databases are not log files
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
        "fileFormat": "",
        "fileNameAndPath": [],
        "fileOwnerId": None,
        "giggsoToken": giggs_token,
        "giggsoTokens": [],
        "googleDriveFiles": [],
        "workspaceChannelFlg": 1,
        "hostname": f["hostname"],
        "indexColumnName": None,
        "indexColumnType": None,
        "isSummary": None,
        "isValidate": 1,
        "level": None,
        "localFileInfos": None,
        "localFiles": [],
        "location": "",
        "maxCount": 10,
        "minCount": 0,
        "monitoringId": None,
        "multiSelect": 0,
        "objectName": None,
        "objectNames": None,
        "password": f["password"],
        "port": f["port"],
        "recordProcessType": None,
        "regenerateEmbeddings": 0,
        "regionName": f["region_name"] if database_type == "dynamodb" else None,
        "userId": user_id,
        "restrictedURLs": None,
        "scheduleEmbeddingDelay": None,
        "scheduleEmbeddingDelayTime": 0,
        "scheduleEmbeddingFlg": 0,
        "scheduleEmbeddingTimeUnit": None,
        "schemaName": f["schema_name"],
        "secretAccessKey": f["secret_access_key"] if database_type == "dynamodb" else None,
        "secretKey": None,
        "serviceName": f["service_name"] if database_type == "oracle" else None,
        "siteName": None,
        "size": file_size or 0,
        "startFrom": 0,
        "storageProvider": database_type,
        "storageType": "database",
        "tableId": "",
        "tableName": f["table_name"] if f["table_name"] else (f["collection_name"] if database_type == "mongodb" else ""),
        "tableNames": None,
        "threadId": 0,
        "topicLevelFlg": 1,
        "update": None,
        "url": None,
        "useCaseType": None,
        "username": f["username"],
        "validatedId": None,
        "warehouse": f["warehouse"] if database_type == "snowflake" else "",
        "workspaceId": workspace_id,
        "channelId": channel_id,
        "filename": filename or "",
        "unique_filename": unique_filename if filename else ""
    }

    # Add collectionName for MongoDB
    if database_type == "mongodb" and f["collection_name"]:
        metadata["collectionName"] = f["collection_name"]

    return metadata
