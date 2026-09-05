"""
Helpers shared by the two "create a datasource from an uploaded file" flows:
from_upload.py (single) and from_upload_bulk.py (bulk). Both endpoints
build an identical provider-specific config dict from the upload result, and
build+clean+enhance an identical metadata shape from it — extracted here
verbatim so each endpoint file stays under the line cap.
"""

from typing import Any, Dict, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.vault_data_builder import enhance_datasource_metadata

from ._metadata_generator import generate_datasource_metadata
from ._metadata_helpers import clean_metadata


def build_config_from_upload_result(upload_result: Dict[str, Any], filename: str) -> Tuple[str, str, Dict[str, Any]]:
    """Derive (storage_type, provider, config) for a datasource created from an upload result."""
    # Determine storage type and provider from upload result
    storage_type = "cloud" if upload_result["provider"] in ["aws", "azure", "oracle"] else "local"
    provider = upload_result["provider"]

    # Build config with provider-specific details
    config = {
        "file_path": upload_result["storage_path"],
        "original_filename": filename
    }

    # Add provider-specific configuration details
    if provider == "aws":
        config.update({
            "bucket_name": upload_result.get("bucket_name"),
            "region": upload_result.get("region")
        })
    elif provider == "azure":
        config.update({
            "container_name": upload_result.get("container_name"),
            "account_name": upload_result.get("account_name")
        })
    elif provider == "oracle":
        config.update({
            "bucket_name": upload_result.get("bucket_name"),
            "namespace": upload_result.get("namespace"),
            "compartment_id": upload_result.get("compartment_id")
        })

    return storage_type, provider, config


async def build_enhanced_metadata_for_upload(
    *,
    filename: str,
    storage_type: str,
    provider: str,
    channel_id: str,
    workspace_id: str,
    user_id: str,
    file_size: int,
    file_type: str,
    log_type: Optional[str],
    config: Dict[str, Any],
    file_url: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    """Generate, clean, and vault-enhance the metadata dict for an uploaded-file datasource."""
    metadata = generate_datasource_metadata(
        filename=filename,
        storage_type=storage_type,
        channel_id=channel_id,
        workspace_id=workspace_id,
        user_id=user_id,
        file_size=file_size,
        file_type=file_type,
        provider=provider,
        app_type=None,
        log_type=log_type,
        config=config,
        file_url=file_url
    )
    cleaned_metadata = clean_metadata(metadata)

    enhanced_metadata = await enhance_datasource_metadata(
        existing_metadata=cleaned_metadata,
        storage_type=storage_type,
        provider=provider,
        config=config,
        db=db,
        channel_id=channel_id
    )
    return enhanced_metadata
