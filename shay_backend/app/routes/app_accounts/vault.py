"""
SharePoint/vault helpers for the app_accounts route package, used by
create, mutate, and connect.

Split out of the original app_accounts/helpers.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.giggso_vault import GiggsoVault
from app.services.vault_service import vault_service


def build_sharepoint_credentials_metadata(connection_settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build SharePoint credentials metadata for vault storage

    Args:
        connection_settings: Connection settings dictionary containing SharePoint credentials

    Returns:
        Dictionary containing SharePoint credentials formatted for vault storage
    """
    if not connection_settings or not isinstance(connection_settings, dict):
        return {}

    metadata = {
        "sharePointConfigured": True,
        "clientId": "",
        "clientSecret": "",
        "tenantId": "",
        "siteUrl": "",
        "refreshToken": "",
        "accessToken": "",
        "emailId": "",
        "scope": "",
        "oauthProvider": "microsoft",
        "connectionMethod": "oauth"
    }

    # Extract SharePoint credentials from connection_settings
    if connection_settings.get("client_id"):
        metadata["clientId"] = connection_settings.get("client_id")
    if connection_settings.get("client_secret"):
        metadata["clientSecret"] = connection_settings.get("client_secret")
    if connection_settings.get("tenant_id"):
        metadata["tenantId"] = connection_settings.get("tenant_id")
    if connection_settings.get("site_url"):
        metadata["siteUrl"] = connection_settings.get("site_url")
    if connection_settings.get("refresh_token"):
        metadata["refreshToken"] = connection_settings.get("refresh_token")
    if connection_settings.get("access_token"):
        metadata["accessToken"] = connection_settings.get("access_token")
    if connection_settings.get("email_id"):
        metadata["emailId"] = connection_settings.get("email_id")
    if connection_settings.get("scope"):
        metadata["scope"] = connection_settings.get("scope")
    if connection_settings.get("oauth_provider"):
        metadata["oauthProvider"] = connection_settings.get("oauth_provider")
    if connection_settings.get("connection_method"):
        metadata["connectionMethod"] = connection_settings.get("connection_method")

    return metadata


async def handle_app_account_vault_integration(
    credentials_metadata: Dict[str, Any],
    user_id: str,
    company_id: str,
    db: AsyncSession,
    required: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Handle vault integration for app account credentials

    Args:
        credentials_metadata: Credentials metadata dictionary to store in vault
        user_id: User ID
        company_id: Company ID
        db: Database session
        required: If True, vault failure will raise HTTPException. If False, returns None on failure.

    Returns:
        Dict with 'vault_unique_id' and 'giggso_vault_id' if successful, None if failed and not required

    Raises:
        HTTPException: If vault integration fails and vault is required
    """
    if not credentials_metadata:
        return None

    # Generate vault unique ID
    vault_unique_id = vault_service.generate_vault_unique_id(str(user_id), "app_account")

    # Save credentials to vault
    saved_vault_id = await vault_service.save_to_vault(credentials_metadata, vault_unique_id)

    # If vault save failed, handle based on required flag
    if not saved_vault_id:
        if required:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save credentials to vault. App account creation cannot proceed without secure storage."
            )
        else:
            return None

    # Create vault record if external vault save was successful
    try:
        base_label = f"app_{vault_unique_id[:8]}"
        vault_label = f"{base_label}_ok"

        vault_record = GiggsoVault(
            vault_unique_id=vault_unique_id,
            user_id=user_id,
            vault_label=vault_label,
            vault_type="app_account_credentials",
            company_id=company_id,
            created_by=user_id,
            created_datetime=datetime.utcnow()
        )

        db.add(vault_record)
        await db.flush()
        await db.commit()

        await db.refresh(vault_record)

        return {
            "vault_unique_id": vault_unique_id,
            "giggso_vault_id": vault_record.giggso_vault_id
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create vault record: {str(e)}"
        )
