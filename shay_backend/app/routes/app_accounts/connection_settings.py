"""
connection_settings pre-processing for new app accounts: Jira client
credential injection, and SharePoint vault integration + sanitization.

Extracted from create.py's create_app_account so the endpoint itself stays
under the line-count limit (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4); this is the same
atomic pre-processing step the original single function performed inline.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

from .vault import build_sharepoint_credentials_metadata, handle_app_account_vault_integration


async def resolve_create_connection_settings(
    app_key: Optional[str],
    connection_settings: Optional[Dict[str, Any]],
    user_id: str,
    company_id: str,
    db: AsyncSession,
) -> Optional[Dict[str, Any]]:
    """
    Process connection_settings for a new app account: inject Jira client
    credentials, and — for SharePoint apps — push credentials to the vault
    and return sanitized (non-sensitive) settings in their place.
    """
    if connection_settings and isinstance(connection_settings, dict):
        # Create a copy to avoid modifying the original
        connection_settings = copy.deepcopy(connection_settings)
        if connection_settings.get("provider") == "jira":
            connection_settings["client_id"] = settings.JIRA_CLIENT_ID
            connection_settings["client_secret"] = settings.JIRA_CLIENT_SECRET

    if app_key and app_key.lower() in ["sharepoint", "share_point"]:
        if connection_settings and isinstance(connection_settings, dict):
            credentials_metadata = build_sharepoint_credentials_metadata(connection_settings)
            if credentials_metadata:
                try:
                    vault_result = await handle_app_account_vault_integration(
                        credentials_metadata=credentials_metadata,
                        user_id=user_id,
                        company_id=company_id,
                        db=db,
                        required=True,
                    )
                    if vault_result:
                        # Remove sensitive credentials from connection_settings (keep only non-sensitive metadata)
                        connection_settings = {
                            "provider": connection_settings.get("provider"),
                            "oauth_provider": connection_settings.get("oauth_provider"),
                            "connection_method": connection_settings.get("connection_method"),
                            "email_id": connection_settings.get("email_id"),
                            "scope": connection_settings.get("scope"),
                        }
                except HTTPException:
                    raise
                except Exception as e:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to integrate with vault service: {str(e)}",
                    )

    return connection_settings
