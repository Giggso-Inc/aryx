#!/usr/bin/env python3
"""
Datasource metadata enrichment with vault-specific fields.

Split out of the former app/services/vault_data_builder.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a): this module owns
"take existing datasource metadata + vault credentials and merge in the
storage-type-specific vault fields", separate from credential building
(credentials.py) and environment introspection (environment.py).

Stated exception: `enhance_datasource_metadata` stays as one function
(not split per storage_type) for the same reason as
`build_vault_credentials` in credentials.py — the branches share one
signature/contract and callers invoke it with a single storage_type at a
time.
"""

import logging
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .credentials import build_vault_credentials

logger = logging.getLogger(__name__)


async def enhance_datasource_metadata(
    existing_metadata: Dict[str, Any],
    storage_type: str,
    provider: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    app_type: Optional[str] = None,
    db: Optional[AsyncSession] = None,
    channel_id: Optional[str] = None,
    location: Optional[str] = None,
    accessToken: Optional[str] = None,
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

        enhanced_metadata["credentials"].update(
            {
                "access_key": vault_creds["access_key"],
                "secret_access_key": vault_creds["secret_access_key"],
                "region": vault_creds["region"],
                "bucket_name": vault_creds["bucket_name"],
                "additional_config": vault_creds["additional_config"],
            }
        )

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
            enhanced_metadata["credentials"].update(
                {
                    "bucket_name": vault_creds.get("bucket_name"),
                    "file_path": vault_creds.get("file_path"),
                    "service_account_json": vault_creds.get("service_account_json"),
                    "project_id": vault_creds.get("project_id"),
                    "region": vault_creds.get("region"),
                    "additional_config": vault_creds.get("additional_config"),
                }
            )
        else:
            # AWS, Azure, Oracle credential structure
            enhanced_metadata["credentials"].update(
                {
                    "access_key": vault_creds["access_key"],
                    "secret_access_key": vault_creds["secret_access_key"],
                    "region": vault_creds["region"],
                    "bucket_name": vault_creds["bucket_name"],
                    "additional_config": vault_creds["additional_config"],
                }
            )

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
        enhanced_metadata["credentials"] = {"additional_config": vault_creds["additional_config"]}

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
        enhanced_metadata["credentials"].update(
            {
                "username": vault_creds.get("username"),
                "password": vault_creds.get("password"),
                "hostname": vault_creds.get("hostname"),
                "port": vault_creds.get("port"),
                "databaseName": vault_creds.get("databaseName"),
            }
        )

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
