#!/usr/bin/env python3
"""
Vault Data Builder Service for Datasources API
Handles transformation of API payload to vault data structure with dynamic localProvider
"""

import os
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, text
from app.models.app_account import AppAccount

logger = logging.getLogger(__name__)

def get_endpoint_url(cloud_provider: str) -> str:
    """Get endpoint URL based on cloud provider"""
    endpoints = {
        "aws": "https://s3.amazonaws.com",
        "azure": "https://storage.blob.core.windows.net",
        "gcp": "https://storage.googleapis.com",
        "oracle": "https://objectstorage.oraclecloud.com"
    }
    return endpoints.get(cloud_provider, "https://s3.amazonaws.com")

async def build_vault_credentials(
    storage_type: str,
    provider: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    app_type: Optional[str] = None,
    db: Optional[AsyncSession] = None,
    channel_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Build vault credentials based on storage type and configuration
    For local storage: localProvider = CLOUD_PROVIDER when FILE_UPLOAD_ENV=cloud
    """
    
    if storage_type == "local":
        # Import settings from config
        from app.core.config import settings
        
        # Get configuration from settings
        storage_env = settings.FILE_UPLOAD_ENV
        cloud_provider = settings.CLOUD_PROVIDER
        

        
        if storage_env == "cloud":
            # Local storage but localProvider = CLOUD_PROVIDER
            if cloud_provider == "aws":
                return {
                    "access_key": settings.AWS_ACCESS_KEY_ID,
                    "secret_access_key": settings.AWS_SECRET_ACCESS_KEY,
                    "region": settings.AWS_REGION,
                    "bucket_name": settings.AWS_BUCKET_NAME,
                    "localProvider": cloud_provider,  # "aws", "azure", "gcp", etc.
                    "additional_config": {
                        "endpoint_url": get_endpoint_url(cloud_provider),
                        "max_retries": 3,
                        "timeout": 30,
                        "environment_configured": True,
                        "cloud_provider": cloud_provider
                    }
                }
            elif cloud_provider == "azure":
                return {
                    "access_key": settings.AZURE_STORAGE_CONNECTION_STRING,
                    "secret_access_key": None,
                    "region": None,
                    "bucket_name": settings.AZURE_CONTAINER_NAME,
                    "localProvider": cloud_provider,
                    "additional_config": {
                        "endpoint_url": get_endpoint_url(cloud_provider),
                        "max_retries": 3,
                        "timeout": 30,
                        "environment_configured": True,
                        "cloud_provider": cloud_provider
                    }
                }
            elif cloud_provider == "oracle":
                return {
                    "access_key": settings.ORACLE_NAMESPACE,
                    "secret_access_key": None,
                    "region": None,
                    "bucket_name": settings.ORACLE_BUCKET_NAME,
                    "localProvider": cloud_provider,
                    "additional_config": {
                        "endpoint_url": get_endpoint_url(cloud_provider),
                        "max_retries": 3,
                        "timeout": 30,
                        "environment_configured": True,
                        "cloud_provider": cloud_provider
                    }
                }
            else:
                # Default to AWS if provider not recognized
                return {
                    "access_key": settings.AWS_ACCESS_KEY_ID,
                    "secret_access_key": settings.AWS_SECRET_ACCESS_KEY,
                    "region": settings.AWS_REGION,
                    "bucket_name": settings.AWS_BUCKET_NAME,
                    "localProvider": "aws",
                    "additional_config": {
                        "endpoint_url": get_endpoint_url("aws"),
                        "max_retries": 3,
                        "timeout": 30,
                        "environment_configured": True,
                        "cloud_provider": "aws"
                    }
                }
        else:
            # Local storage with file_system provider
            return {
                "access_key": None,
                "secret_access_key": None,
                "region": None,
                "bucket_name": None,
                "localProvider": "file_system",
                "additional_config": None
            }
    
    elif storage_type == "cloud":
        # User provides their own cloud credentials
        if not config:
            return {
                "access_key": None,
                "secret_access_key": None,
                "region": None,
                "bucket_name": None,
                "localProvider": None,
                "additional_config": None
            }
        
        # GCP-specific credentials handling
        if provider == "gcp":
            credentials = {
                "access_key": None,  # GCP uses service account JSON, not access_key
                "secret_access_key": None,  # GCP uses service account JSON, not secret_key
                "region": config.get("region"),
                "bucket_name": config.get("bucket_name"),
                "file_path": config.get("file_path"),  # GCP requires file_path in credentials
                "service_account_json": config.get("service_account_json"),  # GCP service account JSON
                "project_id": config.get("project_id"),  # GCP project ID
                "localProvider": None,  # Not applicable for cloud storage
                "additional_config": {
                    "max_retries": 3,
                    "timeout": 30,
                    "user_provided": True,
                    "provider": provider
                }
            }
        else:
            # Extract credentials from config for AWS, Azure, Oracle
            credentials = {
                "access_key": config.get("access_key"),
                "secret_access_key": config.get("secret_key") or config.get("secret_access_key"),
                "region": config.get("region") or config.get("location"),
                "bucket_name": config.get("bucket_name") or config.get("container_name"),
                "localProvider": None,  # Not applicable for cloud storage
                "additional_config": {
                    "max_retries": 3,
                    "timeout": 30,
                    "user_provided": True,
                    "provider": provider
                }
            }
        
        return credentials
    
    elif storage_type == "database":
        database_type = provider or "mysql"
        
        if not config:
            return {
                "access_key": None,
                "secret_access_key": None,
                "region": None,
                "bucket_name": None,
                "localProvider": None,
                "additional_config": None
            }
        
        # Extract database credentials based on database type
        credentials = {
            "access_key": None,
            "secret_access_key": None,
            "region": None,
            "bucket_name": None,
            "localProvider": None,
            "additional_config": {
                "database_type": database_type,
                "provider": database_type
            }
        }
        
        # Common database fields with fallback alternatives
        if config.get("username") or config.get("user"):
            credentials["username"] = config.get("username") or config.get("user")
        if config.get("password") or config.get("pass"):
            credentials["password"] = config.get("password") or config.get("pass")
        if config.get("hostname") or config.get("host") or config.get("endpoint"):
            credentials["hostname"] = config.get("hostname") or config.get("host") or config.get("endpoint")
        if config.get("port"):
            credentials["port"] = str(config.get("port"))  # Convert to string as per expected format
        if config.get("databaseName") or config.get("database") or config.get("dbname"):
            credentials["databaseName"] = config.get("databaseName") or config.get("database") or config.get("dbname")
        
        # Database-specific fields
        if config.get("schemaName") or config.get("schema"):
            credentials["schemaName"] = config.get("schemaName") or config.get("schema")
        if config.get("tableName"):
            credentials["tableName"] = config.get("tableName")
        if config.get("collectionName"):  # MongoDB
            credentials["collectionName"] = config.get("collectionName")
        if config.get("serviceName") or config.get("service"):  # Oracle
            credentials["serviceName"] = config.get("serviceName") or config.get("service")
        if config.get("accountId") or config.get("account"):  # Snowflake
            credentials["accountId"] = config.get("accountId") or config.get("account")
        if config.get("warehouse"):  # Snowflake
            credentials["warehouse"] = config.get("warehouse")
        if config.get("regionName") or config.get("region"):  # DynamoDB
            credentials["regionName"] = config.get("regionName") or config.get("region")
        if config.get("accessKeyId") or config.get("access_key_id"):  # DynamoDB
            credentials["accessKeyId"] = config.get("accessKeyId") or config.get("access_key_id")
        if config.get("secretAccessKey") or config.get("secret_access_key"):  # DynamoDB
            credentials["secretAccessKey"] = config.get("secretAccessKey") or config.get("secret_access_key")
        
        return credentials
    
    elif storage_type == "app":
        # App storage credentials (Google Drive, SharePoint, Dropbox, OneDrive)
        # Safety check: app_type must be provided for app storage
        if not app_type:
            # This should not happen in normal flow, but safety fallback
            return {
                "access_key": None,
                "secret_access_key": None,
                "region": None,
                "bucket_name": None,
                "localProvider": None,
                "additional_config": None
            }
        
        # Convert app_type to camelCase for Google Drive in additional_config (ML service requirement)
        app_type_for_config = "googleDrive" if app_type == "google_drive" else app_type
        
        credentials = {
            "access_key": None,
            "secret_access_key": None,
            "region": None,
            "bucket_name": None,
            "additional_config": {
                "app_type": app_type_for_config,
                "app_id": config.get("app_id") if config else None,
                "oauth_configured": True
            }
        }
        
        # Add app-specific information from connection_settings
        if config and config.get("connection_settings"):
            connection_settings = config.get("connection_settings")
            account = connection_settings.get("account", {}) if connection_settings else {}
            
            # Fetch refresh_token from app_accounts if secret_key is missing
            connection_id = config.get("connection_id")
            if not account.get("secret_key") and connection_id and db:
                try:
            
                    
    
                    app_account_query = text("""
                        SELECT id, app_id, channel_id, connected_by, connection_name, 
                               connection_status, connection_settings, api_key, webhook_url, 
                               callback_url, last_sync_at, sync_status, error_message, 
                               is_active, auto_sync, sync_interval, created_at, updated_at
                        FROM gg_app_accounts
                        WHERE id = :connection_id AND is_active = true
                    """)
                    result = await db.execute(app_account_query, {"connection_id": connection_id})
                    app_account_row = result.first()
                    
                    # Create a simple object to access connection_settings
                    class AppAccountProxy:
                        def __init__(self, row):
                            self.id = row[0]
                            self.channel_id = row[2]
                            self.connection_settings = row[6]
                    
                    app_account = AppAccountProxy(app_account_row) if app_account_row else None
                    
                    if app_account:
                        # Validate channel_id if provided
                        if channel_id and str(app_account.channel_id) != channel_id:
                            print(f"⚠️ Connection {connection_id} does not belong to channel {channel_id}")
                        else:
                            # Extract refresh_token from connection_settings
                            if app_account.connection_settings:
                                refresh_token = app_account.connection_settings.get("refresh_token")
                                
                                if refresh_token:
                                    # Add refresh_token as secret_key to account
                                    if not connection_settings:
                                        connection_settings = {}
                                    if "account" not in connection_settings:
                                        connection_settings["account"] = {}
                                    connection_settings["account"]["secret_key"] = refresh_token
                                    # Update account variable for later use
                                    account = connection_settings["account"]
                                    print(f"✅ Fetched refresh_token from app_account {connection_id} and added as secret_key")
                                else:
                                    print(f"⚠️ No refresh_token found in app_account {connection_id}")
                            else:
                                print(f"⚠️ No connection_settings in app_account {connection_id}")
                    else:
                        print(f"⚠️ App account not found or inactive: {connection_id}")
                except Exception as e:
                    print(f"⚠️ Error fetching refresh_token from app_account: {e}")
                    # Continue without refresh_token (non-fatal for vault)
            
            # Add account information as individual key-value pairs in additional_config
            if account:
                # Add account-level fields
                # credentials["additional_config"]["id"] = account.get("id")
                # credentials["additional_config"]["external_id"] = account.get("external_id")
                # credentials["additional_config"]["healthy"] = account.get("healthy")
                
                # Add app-level fields
                app_info = account.get("app", {})
                if app_info:
                    credentials["additional_config"]["app"] = app_info
                
                # Add Google Drive specific fields to additional_config
                if app_type == "google_drive" or app_type == "googleDrive":
                    from app.core.config import settings
                    
                    # Add file-specific fields from account
                    if account.get("file_id"):
                        credentials["additional_config"]["file_id"] = account.get("file_id")
                    if account.get("secret_key"):
                        credentials["additional_config"]["secret_key"] = account.get("secret_key")
                    if account.get("mime_type"):
                        credentials["additional_config"]["mime_type"] = account.get("mime_type")
                    if account.get("file_name"):
                        credentials["additional_config"]["file_name"] = account.get("file_name")
                    
                    # Add Google OAuth credentials from config.py
                    if settings.GOOGLE_CLIENT_ID:
                        credentials["additional_config"]["client_id"] = settings.CLIENT_ID
                    if settings.GOOGLE_CLIENT_SECRET:
                        credentials["additional_config"]["client_secret"] = settings.CLIENT_SECRET
        
        # Add provider-specific fields based on the provider from payload
        if provider == "pipedream":
            credentials["app_id"] = config.get("app_id") if config else None
        
        return credentials
    else:
        # App storage or other types
        return {
            "access_key": None,
            "secret_access_key": None,
            "region": None,
            "bucket_name": None,
            "localProvider": None,
            "additional_config": None
        }

async def enhance_datasource_metadata(
    existing_metadata: Dict[str, Any],
    storage_type: str,
    provider: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    app_type: Optional[str] = None,
    db: Optional[AsyncSession] = None,
    channel_id: Optional[str] = None,
    location: Optional[str] = None,
    accessToken: Optional[str] = None
) -> Dict[str, Any]:
    """
    Enhance existing datasource metadata with vault-specific fields
    This function modifies the existing metadata to include the new vault structure
    """
    
    # Get vault credentials
    vault_creds = await build_vault_credentials(storage_type, provider, config, app_type, db, channel_id)
    
    # Create enhanced metadata
    enhanced_metadata = existing_metadata.copy()
    
    # Add vault-specific fields
    if storage_type == "local":
        enhanced_metadata["localProvider"] = vault_creds["localProvider"]
        enhanced_metadata["storageType"] = "local"
        
        # Update credentials object
        if "credentials" not in enhanced_metadata:
            enhanced_metadata["credentials"] = {}
        
        enhanced_metadata["credentials"].update({
            "access_key": vault_creds["access_key"],
            "secret_access_key": vault_creds["secret_access_key"],
            "region": vault_creds["region"],
            "bucket_name": vault_creds["bucket_name"],
            "additional_config": vault_creds["additional_config"]
        })
        
        # Add localFiles array if not present
        if "localFiles" not in enhanced_metadata:
            filename = enhanced_metadata.get("filename") or enhanced_metadata.get("unique_filename")
            if filename:
                enhanced_metadata["localFiles"] = [filename]
        
        return enhanced_metadata
    
    elif storage_type == "cloud":
        enhanced_metadata["storageType"] = "cloud"
        enhanced_metadata["storageProvider"] = provider or "user_provided"
        enhanced_metadata["cloudProvider"] = provider or "user_provided"
        
        # Add location and accessToken to metadata if provided
        if location:
            enhanced_metadata["location"] = location
        if accessToken:
            enhanced_metadata["accessToken"] = accessToken
        
        # Update credentials object
        if "credentials" not in enhanced_metadata:
            enhanced_metadata["credentials"] = {}
        
        # GCP-specific credential structure
        if provider == "gcp":
            enhanced_metadata["credentials"].update({
                "bucket_name": vault_creds.get("bucket_name"),
                "file_path": vault_creds.get("file_path"),
                "service_account_json": vault_creds.get("service_account_json"),
                "project_id": vault_creds.get("project_id"),
                "region": vault_creds.get("region"),
                "additional_config": vault_creds.get("additional_config")
            })
        else:
            # AWS, Azure, Oracle credential structure
            enhanced_metadata["credentials"].update({
                "access_key": vault_creds["access_key"],
                "secret_access_key": vault_creds["secret_access_key"],
                "region": vault_creds["region"],
                "bucket_name": vault_creds["bucket_name"],
                "additional_config": vault_creds["additional_config"]
            })
        
        return enhanced_metadata
    elif storage_type == "app":
        # App storage (Google Drive, SharePoint, Dropbox, OneDrive)
        # Safety check: app_type must be provided for app storage
        if not app_type:
            # This should not happen in normal flow, but safety fallback
            return existing_metadata
        
        enhanced_metadata["storageType"] = "app"
        enhanced_metadata["appProvider"] = provider  # This comes from app_provider in payload
        
        # Convert app_type from snake_case to camelCase ONLY for Google Drive (ML service requirement)
        # For other app types, use the original value
        if app_type == "google_drive":
            enhanced_metadata["appType"] = "googleDrive"
        else:
            enhanced_metadata["appType"] = app_type
        
        enhanced_metadata["databaseType"] = "app"
        
        # Add app-specific fields
        if app_type == "google_drive" or app_type == "googleDrive":
            enhanced_metadata["googleDriveConfigured"] = True
        elif app_type == "sharepoint":
            enhanced_metadata["sharePointConfigured"] = True
            
            # Initialize SharePoint fields with empty strings (as per expected structure)
            enhanced_metadata["clientId"] = ""
            enhanced_metadata["clientSecret"] = ""
            enhanced_metadata["secretKey"] = ""  
            enhanced_metadata["refreshToken"] = ""
            enhanced_metadata["accessToken"] = ""
            enhanced_metadata["tenantId"] = ""
            enhanced_metadata["siteUrl"] = ""
            enhanced_metadata["filePath"] = ""
            enhanced_metadata["fileName"] = ""
            enhanced_metadata["emailId"] = ""
            enhanced_metadata["scope"] = ""
            enhanced_metadata["oauthProvider"] = "microsoft"
            enhanced_metadata["connectionMethod"] = "oauth"
            
            # Extract SharePoint-specific fields from connection_settings (flat structure)
            if config and config.get("connection_settings"):
                connection_settings = config.get("connection_settings")
                
                if connection_settings.get("client_id"):
                    enhanced_metadata["clientId"] = connection_settings.get("client_id")
                if connection_settings.get("client_secret"):
                    enhanced_metadata["clientSecret"] = connection_settings.get("client_secret")
                if connection_settings.get("tenant_id"):
                    enhanced_metadata["tenantId"] = connection_settings.get("tenant_id")
                if connection_settings.get("site_url"):
                    enhanced_metadata["siteUrl"] = connection_settings.get("site_url")
                if connection_settings.get("file_path"):
                    enhanced_metadata["filePath"] = connection_settings.get("file_path")
                if connection_settings.get("file_name"):
                    enhanced_metadata["fileName"] = connection_settings.get("file_name")
                if connection_settings.get("refresh_token"):
                    enhanced_metadata["refreshToken"] = connection_settings.get("refresh_token")
                if connection_settings.get("access_token"):
                    enhanced_metadata["accessToken"] = connection_settings.get("access_token")
                if connection_settings.get("email_id"):
                    enhanced_metadata["emailId"] = connection_settings.get("email_id")
                if connection_settings.get("scope"):
                    enhanced_metadata["scope"] = connection_settings.get("scope")
                if connection_settings.get("oauth_provider"):
                    enhanced_metadata["oauthProvider"] = connection_settings.get("oauth_provider")
                if connection_settings.get("connection_method"):
                    enhanced_metadata["connectionMethod"] = connection_settings.get("connection_method")
        elif app_type == "dropbox":
            enhanced_metadata["dropboxConfigured"] = True
        elif app_type == "oneDrive":
            enhanced_metadata["oneDriveConfigured"] = True
        
        # Update credentials object
        if "credentials" not in enhanced_metadata:
            enhanced_metadata["credentials"] = {}
        
        # Remove connection_settings if it exists
        if "connection_settings" in enhanced_metadata["credentials"]:
            del enhanced_metadata["credentials"]["connection_settings"]
        
        # For app storage, only include additional_config and app_id (if present)
        # Remove null values for cloud/local specific fields
        enhanced_metadata["credentials"] = {
            "additional_config": vault_creds["additional_config"]
        }
        
        # Add app_id if present (for pipedream provider)
        if provider == "pipedream" and vault_creds.get("app_id"):
            enhanced_metadata["credentials"]["app_id"] = vault_creds.get("app_id")
        
        # Also add app_id from config if available (for consistency)
        if config and config.get("app_id"):
            enhanced_metadata["credentials"]["app_id"] = config.get("app_id")
        
        return enhanced_metadata
    
    elif storage_type == "database":
        # Database storage (MySQL, PostgreSQL, SQL Server, Oracle, MongoDB, DynamoDB, Redshift, Snowflake)
        database_type = provider or "mysql"
        
        enhanced_metadata["storageType"] = "database"
        enhanced_metadata["databaseType"] = database_type  # mysql, postgresql, sqlserver, oracle, mongodb, dynamodb, redshift, snowflake
        
        # Update credentials object
        if "credentials" not in enhanced_metadata:
            enhanced_metadata["credentials"] = {}
        
        # Structure credentials according to database type
        enhanced_metadata["credentials"].update({
            "username": vault_creds.get("username"),
            "password": vault_creds.get("password"),
            "hostname": vault_creds.get("hostname"),
            "port": vault_creds.get("port"),
            "databaseName": vault_creds.get("databaseName")
        })
        
        # Add database-specific fields
        if vault_creds.get("schemaName"):
            enhanced_metadata["credentials"]["schemaName"] = vault_creds.get("schemaName")
        if vault_creds.get("tableName"):
            enhanced_metadata["tableName"] = vault_creds.get("tableName")
            # Also store tableName in credentials for vault data (for easy access with other DB connection info)
            enhanced_metadata["credentials"]["tableName"] = vault_creds.get("tableName")
        if vault_creds.get("collectionName"):  # MongoDB
            enhanced_metadata["collectionName"] = vault_creds.get("collectionName")
            # Also store collectionName in credentials for vault data (for easy access with other DB connection info)
            enhanced_metadata["credentials"]["collectionName"] = vault_creds.get("collectionName")
        if vault_creds.get("serviceName"):  # Oracle
            enhanced_metadata["credentials"]["serviceName"] = vault_creds.get("serviceName")
        if vault_creds.get("accountId"):  # Snowflake
            enhanced_metadata["credentials"]["accountId"] = vault_creds.get("accountId")
        if vault_creds.get("warehouse"):  # Snowflake
            enhanced_metadata["credentials"]["warehouse"] = vault_creds.get("warehouse")
        if vault_creds.get("regionName"):  # DynamoDB
            enhanced_metadata["credentials"]["regionName"] = vault_creds.get("regionName")
        if vault_creds.get("accessKeyId"):  # DynamoDB
            enhanced_metadata["credentials"]["accessKeyId"] = vault_creds.get("accessKeyId")
        if vault_creds.get("secretAccessKey"):  # DynamoDB
            enhanced_metadata["credentials"]["secretAccessKey"] = vault_creds.get("secretAccessKey")
        
        # Add additional_config if present
        if vault_creds.get("additional_config"):
            enhanced_metadata["credentials"]["additional_config"] = vault_creds.get("additional_config")
        
        return enhanced_metadata
    
    # Fallback for any other storage types
    return existing_metadata

def get_environment_info() -> Dict[str, Any]:
    """Get current configuration for debugging"""
    from app.core.config import settings
    
    storage_env = settings.FILE_UPLOAD_ENV
    cloud_provider = settings.CLOUD_PROVIDER
    
    config = {
        "FILE_UPLOAD_ENV": storage_env,
        "CLOUD_PROVIDER": cloud_provider,
        "current_configuration": "local" if storage_env == "local" else f"cloud-{cloud_provider}"
    }
    
    # Add cloud-specific environment variables if configured
    if storage_env == "cloud":
        if cloud_provider == "aws":
            config.update({
                "AWS_ACCESS_KEY_ID": settings.AWS_ACCESS_KEY_ID,
                "AWS_REGION": settings.AWS_REGION,
                "AWS_BUCKET_NAME": settings.AWS_BUCKET_NAME
            })
        elif cloud_provider == "azure":
            config.update({
                "AZURE_STORAGE_CONNECTION_STRING": settings.AZURE_STORAGE_CONNECTION_STRING,
                "AZURE_CONTAINER_NAME": settings.AZURE_CONTAINER_NAME
            })
        elif cloud_provider == "oracle":
            config.update({
                "ORACLE_NAMESPACE": settings.ORACLE_NAMESPACE,
                "ORACLE_BUCKET_NAME": settings.ORACLE_BUCKET_NAME
            })
    
    return config
