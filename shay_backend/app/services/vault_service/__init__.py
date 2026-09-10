"""
Vault Service for Secure Data Storage

This module provides a service layer for interacting with external vault APIs to store
sensitive datasource configuration data securely. It handles base64 encoded environment
variables for endpoint and token configuration, and provides methods for saving data
to vault and generating unique vault identifiers.

Author: Karthick Chandrasekar
Version: 1.0.0
Date: 2025-08-13

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): this used to be a single
326-line app/services/vault_service.py. It is now a package of mixins by
operation, combined into one VaultService class below so that
`from app.services.vault_service import VaultService, vault_service` (used
throughout the app) needs zero changes.

  config.py    - __init__ (env var decoding) + _init_vault_client_request
  save.py      - save_to_vault
  retrieve.py  - retrieve_from_vault
  delete.py    - delete_from_vault
  ids.py       - generate_vault_unique_id

All mixins share the same `self` (one VaultService instance), so method
resolution order does not matter for correctness here — no two mixins
define the same method name. Only ConfigMixin defines __init__.
"""

from .config import ConfigMixin
from .save import SaveMixin
from .retrieve import RetrieveMixin
from .delete import DeleteMixin
from .ids import IdsMixin


class VaultService(ConfigMixin, SaveMixin, RetrieveMixin, DeleteMixin, IdsMixin):
    """
    Service for interacting with external vault APIs to store sensitive data securely.

    This class provides methods for:
    - Configuring vault connection parameters from environment variables
    - Decoding base64 encoded sensitive configuration values
    - Saving data to external vault services
    - Generating unique vault identifiers for data organization

    The service automatically handles base64 decoding of sensitive environment variables
    like vault endpoints and tokens, while using plain text for non-sensitive paths.
    """


# Global vault service instance
# This singleton instance is used throughout the application for vault operations
# It maintains the decoded configuration and provides vault functionality to other modules
vault_service = VaultService()
