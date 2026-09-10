"""Vault connection configuration: env-var decoding + request-shape building.

Author: Karthick Chandrasekar
"""

import base64
import os
from typing import Any, Dict


class ConfigMixin:
    """Decode vault endpoint/token from environment and build request configs.

    Owns __init__ for the whole VaultService: no other mixin in this package
    defines one, so this is the only constructor in the MRO.
    """

    def __init__(self):
        """
        Initialize the VaultService with configuration from environment variables.

        This method:
        1. Reads base64 encoded vault endpoint and token from environment variables
        2. Decodes them to their actual values for secure configuration
        3. Reads the plain text connections path parameter
        4. Provides fallback handling if decoding fails

        Environment Variables:
            CREDENTIALS_MGMT_KV_ENDPOINT: Base64 encoded vault API endpoint
            CREDENTIALS_MGMT_VAULT_TOKEN: Base64 encoded vault authentication token
            GIGGSO_CONNECTIONS_PATH_PARAM: Plain text path for vault connections
        """
        # Decode base64 encoded environment variables (only endpoint and token)
        vault_endpoint_encoded = os.environ.get("CREDENTIALS_MGMT_KV_ENDPOINT")
        vault_token_encoded = os.environ.get("CREDENTIALS_MGMT_VAULT_TOKEN")

        # Connections path is not encoded, use as-is
        self.giggso_connections_path = os.environ.get("GIGGSO_CONNECTIONS_PATH_PARAM", "giggso-connections")

        # Initialize vault configuration
        self.vault_endpoint = None
        self.vault_token = None

        # Only configure vault if environment variables are provided
        if vault_endpoint_encoded and vault_token_encoded:
            try:
                self.vault_endpoint = base64.b64decode(vault_endpoint_encoded).decode('utf-8')
                self.vault_token = base64.b64decode(vault_token_encoded).decode('utf-8')
                print(f"Vault service configured successfully for endpoint: {self.vault_endpoint}")
            except Exception as e:
                print(f"Error decoding base64 environment variables: {str(e)}")
                print("Vault service will not be available - environment variables are malformed")
        else:
            print("Vault service not configured - environment variables not set")
            print("Set CREDENTIALS_MGMT_KV_ENDPOINT and CREDENTIALS_MGMT_VAULT_TOKEN to enable vault integration")

    def _init_vault_client_request(self, vault_unique_id: str) -> Dict[str, Any]:
        """
        Initialize vault client request configuration for HTTP requests.

        This private method constructs the request configuration dictionary containing
        the URL and headers needed to make requests to the vault API. It combines
        the decoded endpoint, connections path, and unique ID to form the complete URL.

        Args:
            vault_unique_id (str): Unique identifier for the vault entry to be accessed

        Returns:
            Dict[str, Any]: Dictionary containing 'url' and 'headers' for the HTTP request

        Example:
            The method constructs URLs like:
            "http://localhost:8200/v1/cubbyhole/giggso/connections/user123/abc12345"
        """
        return {
            "url": f"{self.vault_endpoint}/{self.giggso_connections_path}/{vault_unique_id}",
            "headers": {
                "X-Vault-Token": self.vault_token,
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
        }
