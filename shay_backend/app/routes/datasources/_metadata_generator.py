"""
generate_datasource_metadata: builds the full metadata dict for a new datasource.

Private module: used by crud.py, upload.py, and bulk.py.

This used to be one ~420-line function with three near-duplicate inline dict
literals (one per storage_type branch). It's split here into three per-branch
builders (_metadata_database, _metadata_cloud, _metadata_local) plus this
thin orchestrator that computes the shared filename/token values and
dispatches — the exact same dict contents as before, just organized by file.
"""

import os
from datetime import datetime
from typing import Any, Dict, Optional

from ._metadata_cloud import build_cloud_metadata
from ._metadata_database import build_database_metadata
from ._metadata_helpers import clean_metadata
from ._metadata_local import build_local_app_metadata

_CLOUD_PROVIDERS = ("aws", "azure", "oracle", "gcp")


def _derive_filename_parts(filename: Optional[str]) -> tuple:
    """Extract file_format and generate a unique_filename with a date suffix."""
    if filename:
        file_format = os.path.splitext(filename)[1].lstrip('.').lower()
        if not file_format:
            file_format = ""  # Default format

        # Generate unique filename with date pattern
        base_filename = os.path.splitext(filename)[0]
        current_date = datetime.now().strftime("%Y-%m-%d")
        unique_filename = f"{base_filename}_{current_date}.{file_format}"
    else:
        # For cloud storage without filename, use a default
        file_format = "txt"
        unique_filename = f"cloud_file_{datetime.now().strftime('%Y-%m-%d')}.{file_format}"
    return file_format, unique_filename


def generate_datasource_metadata(
    filename: str,
    storage_type: str,
    channel_id: str,
    workspace_id: str,
    user_id: str,
    file_size: int,
    file_type: str,
    provider: Optional[str] = None,
    app_type: Optional[str] = None,
    log_type: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    file_url: Optional[str] = None,
    is_embedding_required: bool = False
) -> Dict[str, Any]:
    """Generate metadata structure for datasource"""
    file_format, unique_filename = _derive_filename_parts(filename)

    # Generate giggs token (simple hash of current timestamp)
    timestamp = int(datetime.now().timestamp())
    giggs_token = f"{timestamp}JtmtSTJj6F"

    if storage_type == "database":
        metadata = build_database_metadata(
            filename=filename,
            channel_id=channel_id,
            workspace_id=workspace_id,
            user_id=user_id,
            file_size=file_size,
            provider=provider,
            log_type=log_type,
            config=config,
            is_embedding_required=is_embedding_required,
            unique_filename=unique_filename,
            giggs_token=giggs_token,
        )
    elif storage_type == "cloud" and provider in _CLOUD_PROVIDERS:
        metadata = build_cloud_metadata(
            filename=filename,
            channel_id=channel_id,
            workspace_id=workspace_id,
            user_id=user_id,
            file_size=file_size,
            file_type=file_type,
            provider=provider,
            app_type=app_type,
            log_type=log_type,
            config=config,
            file_url=file_url,
            is_embedding_required=is_embedding_required,
            file_format=file_format,
            unique_filename=unique_filename,
            giggs_token=giggs_token,
        )
    else:
        # For local and app storage
        metadata = build_local_app_metadata(
            filename=filename,
            storage_type=storage_type,
            channel_id=channel_id,
            workspace_id=workspace_id,
            user_id=user_id,
            file_size=file_size,
            provider=provider,
            app_type=app_type,
            log_type=log_type,
            config=config,
            is_embedding_required=is_embedding_required,
            file_format=file_format,
            unique_filename=unique_filename,
            giggs_token=giggs_token,
        )

    # Clean the metadata to remove null/empty/default values
    return clean_metadata(metadata)
