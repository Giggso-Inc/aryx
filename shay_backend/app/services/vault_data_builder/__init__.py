"""
Vault Data Builder Service for Datasources API
Handles transformation of API payload to vault data structure with dynamic localProvider

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a): this used to be a
single 635-line app/services/vault_data_builder.py. It is now a package of
submodules by responsibility:
  - credentials.py: get_endpoint_url, build_vault_credentials
  - metadata.py:    enhance_datasource_metadata
  - environment.py: get_environment_info

All four names are re-exported here so `from app.services.vault_data_builder
import enhance_datasource_metadata` (used throughout app/routes/datasources
and app/routes/gg_datasources) and `from app.services.vault_data_builder
import get_environment_info` need zero changes.

Note: the original file imported `from app.models.app_account import
AppAccount` but never used it (the DB lookup inside build_vault_credentials
uses a raw `sqlalchemy.text()` query and a local proxy class instead of the
ORM model) — that dead import has been dropped as part of the split; it has
no behavioral effect.
"""

from .credentials import build_vault_credentials, get_endpoint_url
from .environment import get_environment_info
from .metadata import enhance_datasource_metadata

__all__ = [
    "get_endpoint_url",
    "build_vault_credentials",
    "enhance_datasource_metadata",
    "get_environment_info",
]
