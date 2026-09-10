"""Delete-from-vault operation."""

import httpx


class DeleteMixin:
    """Delete a stored payload from the configured vault endpoint."""

    async def delete_from_vault(self, vault_unique_id: str) -> bool:
        """
        Delete data from external vault service asynchronously.

        This method attempts to delete the stored payload for the given vault_unique_id.
        If the vault returns 404, we treat it as already deleted (success=True) so that
        the gg_vault reference can still be cleaned up.

        Args:
            vault_unique_id (str): Unique identifier of the vault entry to delete.

        Returns:
            bool: True if delete succeeded (or entry already missing), False otherwise.
        """
        try:
            # Check if vault is properly configured
            if not self.vault_endpoint or not self.vault_token:
                print(f"Vault not configured - cannot delete data with ID: {vault_unique_id}")
                print("Set CREDENTIALS_MGMT_KV_ENDPOINT and CREDENTIALS_MGMT_VAULT_TOKEN environment variables")
                return False

            client_config = self._init_vault_client_request(vault_unique_id)
            print(f"Attempting to delete from vault at: {client_config['url']}")

            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    client_config["url"],
                    headers=client_config["headers"],
                    timeout=30.0,  # 30 second timeout for vault operations
                )

            if response.status_code in [200, 202, 204]:
                print(f"Successfully deleted vault entry with ID: {vault_unique_id}")
                return True

            if response.status_code == 404:
                print(f"Vault entry already missing for ID: {vault_unique_id} (treating as deleted)")
                return True

            print(f"Vault delete API error: {response.status_code} - {response.text}")
            return False
        except Exception as e:
            print(f"Error deleting from vault: {str(e)}")
            print(f"Failed to delete data with ID: {vault_unique_id}")
            return False
