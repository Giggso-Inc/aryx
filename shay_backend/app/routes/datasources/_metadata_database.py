"""
Metadata-dict builder for storage_type="database" datasources.

Private module: called only by _metadata_generator.generate_datasource_metadata.
Split out verbatim from the original monolithic function so each storage-type
branch can live in its own file; the dict contents/keys are unchanged.

Stated exception (162 lines): this is one literal dict of ~60 fixed
metadata keys plus the config-field extraction that feeds it; splitting the
single dict literal further would mean assembling it from fragments across
files, increasing the risk of a silent key/value drift versus the original.
"""

from typing import Any, Dict, Optional


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

    # Extract database credentials from config
    db_username = ""
    db_password = ""
    db_hostname = ""
    db_port = ""
    db_database_name = ""
    db_schema_name = ""
    db_table_name = ""
    db_collection_name = ""
    db_service_name = ""
    db_account_id = ""
    db_warehouse = ""
    db_region_name = ""
    db_access_key_id = ""
    db_secret_access_key = ""

    if config:
        db_username = config.get("username") or config.get("user") or ""
        db_password = config.get("password") or config.get("pass") or ""
        db_hostname = config.get("hostname") or config.get("host") or config.get("endpoint") or ""
        db_port = str(config.get("port", "")) if config.get("port") else ""
        db_database_name = config.get("databaseName") or config.get("database") or config.get("dbname") or ""
        db_schema_name = config.get("schemaName") or config.get("schema") or ""
        db_table_name = config.get("tableName") or ""
        db_collection_name = config.get("collectionName") or ""
        db_service_name = config.get("serviceName") or config.get("service") or ""
        db_account_id = config.get("accountId") or config.get("account") or ""
        db_warehouse = config.get("warehouse") or ""
        db_region_name = config.get("regionName") or config.get("region") or ""
        db_access_key_id = config.get("accessKeyId") or config.get("access_key_id") or ""
        db_secret_access_key = config.get("secretAccessKey") or config.get("secret_access_key") or ""

    metadata = {
        "accessKey": "",
        "accessKeyId": db_access_key_id if database_type == "dynamodb" else None,
        "accessToken": "",
        "accountId": db_account_id if database_type == "snowflake" else "",
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
        "databaseName": db_database_name,
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
        "hostname": db_hostname,
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
        "password": db_password,
        "port": db_port,
        "recordProcessType": None,
        "regenerateEmbeddings": 0,
        "regionName": db_region_name if database_type == "dynamodb" else None,
        "userId": user_id,
        "restrictedURLs": None,
        "scheduleEmbeddingDelay": None,
        "scheduleEmbeddingDelayTime": 0,
        "scheduleEmbeddingFlg": 0,
        "scheduleEmbeddingTimeUnit": None,
        "schemaName": db_schema_name,
        "secretAccessKey": db_secret_access_key if database_type == "dynamodb" else None,
        "secretKey": None,
        "serviceName": db_service_name if database_type == "oracle" else None,
        "siteName": None,
        "size": file_size or 0,
        "startFrom": 0,
        "storageProvider": database_type,
        "storageType": "database",
        "tableId": "",
        "tableName": db_table_name if db_table_name else (db_collection_name if database_type == "mongodb" else ""),
        "tableNames": None,
        "threadId": 0,
        "topicLevelFlg": 1,
        "update": None,
        "url": None,
        "useCaseType": None,
        "username": db_username,
        "validatedId": None,
        "warehouse": db_warehouse if database_type == "snowflake" else "",
        "workspaceId": workspace_id,
        "channelId": channel_id,
        "filename": filename or "",
        "unique_filename": unique_filename if filename else ""
    }

    # Add collectionName for MongoDB
    if database_type == "mongodb" and db_collection_name:
        metadata["collectionName"] = db_collection_name

    return metadata
