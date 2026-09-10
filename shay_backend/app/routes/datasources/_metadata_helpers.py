"""
Small metadata utility helpers shared across datasource create/upload/bulk flows.

Private module: used by crud.py, upload.py, bulk.py, and the metadata
generator (_metadata_generator.py + its per-storage-type builders).
"""

from typing import Any, Dict


def clean_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Remove null, empty string, and default values from metadata"""
    cleaned = {}
    for key, value in metadata.items():
        # Skip null values
        if value is None:
            continue

        # Skip empty strings
        if isinstance(value, str) and value == "":
            continue

        # Skip empty lists
        if isinstance(value, list) and len(value) == 0:
            continue

        # Skip empty dicts
        if isinstance(value, dict) and len(value) == 0:
            continue

        # Skip default values that are commonly not needed
        if key in ["botFlag", "countFlg", "datasourcePrivacy", "disconnectDataSource",
                   "emailAttachmentFlg", "emailValidate", "embeddingsGenerated",
                   "embeddingStatus", "enableDecrypt", "isValidate", "maxCount",
                   "minCount", "multiSelect", "regenerateEmbeddings",
                   "scheduleEmbeddingDelayTime", "scheduleEmbeddingFlg",
                   "startFrom", "threadId", "topicLevelFlg"] and value == 0:
            continue

        if key in ["botFlag", "isValidate", "workspaceChannelFlg"] and value == 1:
            continue

        if key in ["maxCount"] and value == 10:
            continue

        if key in ["minCount", "startFrom", "threadId"] and value == 0:
            continue

        cleaned[key] = value

    return cleaned


def generate_app_filename(datasource_data) -> str:
    """
    Generate a meaningful filename for app storage type based on connection_settings
    Format: "App Name - Account Name" or "App Name" as fallback
    """
    try:
        # Get connection_settings from config
        connection_settings = None
        if datasource_data.config and hasattr(datasource_data.config, 'connection_settings'):
            connection_settings = datasource_data.config.connection_settings
        elif datasource_data.config and isinstance(datasource_data.config, dict):
            connection_settings = datasource_data.config.get('connection_settings')

        if connection_settings and isinstance(connection_settings, dict):
            account = connection_settings.get('account', {})
            app = account.get('app', {}) if isinstance(account, dict) else {}

            # Extract app name and account name
            app_name = app.get('name', '') if isinstance(app, dict) else ''
            account_name = account.get('name', '') if isinstance(account, dict) else ''

            # Create filename based on available data
            if app_name and account_name:
                return f"{app_name} - {account_name}"
            elif app_name:
                return app_name
            elif account_name:
                return f"Account - {account_name}"
        else:
            # Fallback to app_type based naming ONLY if connection_settings is not present
            app_type = getattr(datasource_data, 'app_type', 'unknown')
            if app_type == 'google_drive':
                return "Google Drive"
            elif app_type == 'sharepoint':
                return "SharePoint"
            elif app_type == 'dropbox':
                return "Dropbox"
            elif app_type == 'oneDrive':
                return "OneDrive"
            else:
                return f"{app_type.title()} Datasource"

    except Exception as e:
        # Ultimate fallback
        app_type = getattr(datasource_data, 'app_type', 'unknown')
        return f"{app_type.title()} Datasource"


def sanitize_datasource_metadata(metadata: dict) -> dict:
    """Remove sensitive credentials from datasource metadata for API responses"""
    if not metadata:
        return metadata

    # Create a copy to avoid modifying the original
    sanitized = metadata.copy()

    # Remove sensitive credential fields
    if 'credentials' in sanitized:
        credentials = sanitized['credentials'].copy() if sanitized['credentials'] else {}
        # Remove sensitive fields but keep structure
        sensitive_fields = ['access_key', 'secret_key', 'secret_access_key', 'password', 'token']
        for field in sensitive_fields:
            if field in credentials:
                del credentials[field]

        # Remove sensitive fields from additional_config if it exists
        if 'additional_config' in credentials and isinstance(credentials['additional_config'], dict):
            additional_config = credentials['additional_config'].copy()
            # Remove sensitive OAuth credentials
            sensitive_config_fields = ['client_id', 'client_secret', 'secret_key']
            for field in sensitive_config_fields:
                if field in additional_config:
                    del additional_config[field]
            credentials['additional_config'] = additional_config

        sanitized['credentials'] = credentials

    # Remove other potentially sensitive fields
    sensitive_metadata_fields = ['giggsoToken', 'api_key', 'private_key']
    for field in sensitive_metadata_fields:
        if field in sanitized:
            sanitized[field] = "***REDACTED***"

    return sanitized
