"""
Re-export shim: helpers for the app_accounts route package now live in
response.py (build_user_metadata, build_app_account_response) and vault.py
(build_sharepoint_credentials_metadata, handle_app_account_vault_integration),
split for line-count compliance (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4). Kept here so
`from .helpers import ...` continues to work unchanged across the package.
"""

from .response import build_app_account_response, build_user_metadata
from .vault import build_sharepoint_credentials_metadata, handle_app_account_vault_integration

__all__ = [
    "build_app_account_response",
    "build_user_metadata",
    "build_sharepoint_credentials_metadata",
    "handle_app_account_vault_integration",
]
