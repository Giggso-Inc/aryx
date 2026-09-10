#!/usr/bin/env python3
"""
Vault credential-building helpers.

Split out of the former app/services/vault_data_builder.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a): this module owns
the "given a storage type and raw config, build a vault credentials dict"
responsibility, separate from metadata enrichment (metadata.py) and
environment introspection (environment.py).

Stated exception: `build_vault_credentials` stays as one function (not
split further per storage_type) because the branches share the same
signature/return contract and callers always invoke it with a single
storage_type value at a time — splitting into four functions would just
relocate an if/elif into a dict-of-callables without reducing real
complexity, and would risk subtly changing which kwargs are required for
each branch.
"""

import logging
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def get_endpoint_url(cloud_provider: str) -> str:
    """Get endpoint URL based on cloud provider"""
    endpoints = {
        "aws": "https://s3.amazonaws.com",
        "azure": "https://storage.blob.core.windows.net",
        "gcp": "https://storage.googleapis.com",
        "oracle": "https://objectstorage.oraclecloud.com",
    }
    return endpoints.get(cloud_provider, "https://s3.amazonaws.com")


async def build_vault_credentials(
    storage_type: str,
    provider: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    app_type: Optional[str] = None,
    db: Optional[AsyncSession] = None,
    channel_id: Optional[str] = None,
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
                        "cloud_provider": cloud_provider,
                    },
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
                        "cloud_provider": cloud_provider,
                    },
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
                        "cloud_provider": cloud_provider,
                    },
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
                        "cloud_provider": "aws",
                    },
                }
        else:
            # Local storage with file_system provider
            return {
                "access_key": None,
                "secret_access_key": None,
                "region": None,
                "bucket_name": None,
                "localProvider": "file_system",
                "additional_config": None,
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
                "additional_config": None,
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
                    "provider": provider,
                },
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
                    "provider": provider,
                },
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
                "additional_config": None,
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
                "provider": database_type,
            },
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
                "additional_config": None,
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
                "oauth_configured": True,
            },
        }

        # Add app-specific information from connection_settings
        if config and config.get("connection_settings"):
            connection_settings = config.get("connection_settings")
            account = connection_settings.get("account", {}) if connection_settings else {}

            # Fetch refresh_token from app_accounts if secret_key is missing
            connection_id = config.get("connection_id")
            if not account.get("secret_key") and connection_id and db:
                try:
                    app_account_query = text(
                        """
                        SELECT id, app_id, channel_id, connected_by, connection_name,
                               connection_status, connection_settings, api_key, webhook_url,
                               callback_url, last_sync_at, sync_status, error_message,
                               is_active, auto_sync, sync_interval, created_at, updated_at
                        FROM gg_app_accounts
                        WHERE id = :connection_id AND is_active = true
                        """
                    )
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
                                    print(
                                        f"✅ Fetched refresh_token from app_account {connection_id} and added as secret_key"
                                    )
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
                    # NOTE (pre-existing bug, preserved as-is): the gate checks
                    # settings.GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET but the
                    # VALUES assigned come from the unrelated settings.CLIENT_ID
                    # / settings.CLIENT_SECRET keys.
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
            "additional_config": None,
        }
