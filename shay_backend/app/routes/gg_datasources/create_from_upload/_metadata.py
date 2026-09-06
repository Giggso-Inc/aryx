"""
Shared metadata-building + vault-integration helper used by both the
single and bulk from-upload endpoints in this package. Both endpoints
previously duplicated this exact block; extracting it here is what makes
splitting the original 293-line create_from_upload.py into single.py /
bulk.py (each well under 150 lines) possible without corrupting the
one-atomic-flow-per-datasource semantics of either endpoint.
"""

from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from ..upload import _build_config_from_upload


async def _build_metadata_and_vault(
    upload_result: Dict[str, Any],
    level: str,
    scope_id: str,
    log_type: Optional[str],
    user: User,
    db: AsyncSession,
) -> Tuple[str, str, Dict[str, Any], Dict[str, Any], Optional[UUID]]:
    """
    Build datasource config + metadata from an upload result, run vault
    metadata enhancement, then vault integration.

    Returns (provider, storage_type, config, final_metadata, vault_unique_id_val).
    Raises whatever handle_vault_integration raises — callers decide how to
    handle failure (single endpoint -> 500, bulk endpoint -> failed-list entry).
    """
    from app.services.vault_data_builder import enhance_datasource_metadata
    from app.routes.datasources import handle_vault_integration, generate_datasource_metadata, clean_metadata

    provider     = upload_result.get("provider", "local")
    storage_type = "cloud" if provider in ("aws", "azure", "oracle") else "local"
    config       = _build_config_from_upload(upload_result)

    metadata = generate_datasource_metadata(
        filename=upload_result["original_filename"],
        storage_type=storage_type,
        channel_id=scope_id if level == "channel" else "",
        workspace_id=scope_id if level == "workspace" else "",
        user_id=str(user.id),
        file_size=upload_result["file_size"],
        file_type=upload_result["file_type"],
        provider=provider,
        app_type=None,
        log_type=log_type,
        config=config,
        file_url=upload_result.get("file_url"),
    )
    cleaned_metadata  = clean_metadata(metadata)
    enhanced_metadata = await enhance_datasource_metadata(
        existing_metadata=cleaned_metadata,
        storage_type=storage_type,
        provider=provider,
        config=config,
        db=db,
        channel_id=scope_id if level == "channel" else None,
    )

    vault_unique_id_val: Optional[UUID] = None
    vault_result = await handle_vault_integration(
        datasource_metadata=enhanced_metadata,
        user_id=str(user.id),
        company_id=str(user.company_id),
        db=db,
        required=True,
    )
    if vault_result:
        vault_unique_id_val = UUID(str(vault_result["vault_unique_id"]))

    final_metadata = (enhanced_metadata or {}).copy()
    if vault_unique_id_val:
        final_metadata["vault_unique_id"] = str(vault_unique_id_val)

    return provider, storage_type, config, final_metadata, vault_unique_id_val
