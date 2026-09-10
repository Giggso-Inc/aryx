"""Save-to-vault operation."""

from typing import Any, Dict, Optional

import httpx


class SaveMixin:
    """Save arbitrary payloads to the configured vault endpoint."""

    async def save_to_vault(self, vault_data: Dict[str, Any], vault_unique_id: str) -> Optional[str]:
        """
        Save data to external vault service asynchronously.

        This method sends the provided data to the configured vault API endpoint
        using the unique identifier for storage location. It handles HTTP requests
        asynchronously and provides comprehensive error handling for various failure
        scenarios including network issues, authentication failures, and API errors.

        Args:
            vault_data (Dict[str, Any]): The data dictionary to store in vault.
                                        No transformation is performed on this data.
            vault_unique_id (str): Unique identifier for the vault entry location.
                                  Used to construct the specific vault API endpoint.

        Returns:
            Optional[str]: The vault_unique_id if successful, None if the operation failed.
                          Returns None if vault is not configured or if the operation failed.

        Error Handling:
            - Network/Connection errors: Catches and logs exceptions
            - Authentication failures: Logs HTTP status codes and response text
            - Vault not configured: Returns None and logs appropriate message
            - Timeout: 30-second timeout for HTTP requests

        Example:
            >>> vault_service = VaultService()
            >>> result = await vault_service.save_to_vault({"key": "value"}, "user123/abc12345")
            >>> print(result)  # "user123/abc12345" if successful, None if failed
        """
        try:
            # Check if vault is properly configured
            if not self.vault_endpoint or not self.vault_token:
                print(f"Vault not configured - cannot save data with ID: {vault_unique_id}")
                print("Set CREDENTIALS_MGMT_KV_ENDPOINT and CREDENTIALS_MGMT_VAULT_TOKEN environment variables")
                return None

            # Prepare the HTTP request configuration
            client_config = self._init_vault_client_request(vault_unique_id)
            print(f"Attempting to save to vault at: {client_config['url']}")

            # Make the HTTP request to the vault API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    client_config["url"],
                    headers=client_config["headers"],
                    json=vault_data,
                    timeout=30.0  # 30 second timeout for vault operations
                )

                # Check if the request was successful
                if response.status_code in [200, 201, 204]:
                    print(f"Successfully saved to vault with ID: {vault_unique_id}")
                    return vault_unique_id
                else:
                    print(f"Vault API error: {response.status_code} - {response.text}")
                    print(f"Failed to save data with ID: {vault_unique_id}")
                    return None

        except Exception as e:
            print(f"Error saving to vault: {str(e)}")
            print(f"Failed to save data with ID: {vault_unique_id}")
            return None
