"""Retrieve-from-vault operation."""

from typing import Any, Dict, Optional

import httpx


class RetrieveMixin:
    """Fetch and normalize a stored payload from the configured vault endpoint."""

    async def retrieve_from_vault(self, vault_unique_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve data from external vault service asynchronously.

        This method fetches the stored JSON payload for the given vault_unique_id.
        The exact response shape can vary by vault implementation, so this method
        attempts to unwrap common wrapper formats (e.g. {"data": {...}} or
        {"data": {"data": {...}}}).

        Args:
            vault_unique_id (str): Unique identifier for the vault entry location.

        Returns:
            Optional[Dict[str, Any]]: Stored payload dict if successful, otherwise None.
        """
        try:
            # Check if vault is properly configured
            if not self.vault_endpoint or not self.vault_token:
                print(f"Vault not configured - cannot retrieve data with ID: {vault_unique_id}")
                print("Set CREDENTIALS_MGMT_KV_ENDPOINT and CREDENTIALS_MGMT_VAULT_TOKEN environment variables")
                return None

            # Prepare the HTTP request configuration
            client_config = self._init_vault_client_request(vault_unique_id)
            print(f"Attempting to retrieve from vault at: {client_config['url']}")

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    client_config["url"],
                    headers=client_config["headers"],
                    timeout=30.0,  # 30 second timeout for vault operations
                )

            if response.status_code == 200:
                try:
                    body: Any = response.json()
                except Exception:
                    print(f"Vault retrieve returned non-JSON response for ID: {vault_unique_id}")
                    return None

                # Unwrap common vault response shapes
                if isinstance(body, dict) and "data" in body:
                    inner = body.get("data")
                    if isinstance(inner, dict) and "data" in inner and isinstance(inner.get("data"), dict):
                        return inner["data"]
                    if isinstance(inner, dict):
                        return inner

                # If it's already a dict payload, return it
                if isinstance(body, dict):
                    return body

                # Fallback: wrap non-dict payloads for consistent downstream handling
                return {"value": body}

            if response.status_code == 404:
                print(f"Vault entry not found for ID: {vault_unique_id}")
                return None

            print(f"Vault retrieve API error: {response.status_code} - {response.text}")
            return None
        except Exception as e:
            print(f"Error retrieving from vault: {str(e)}")
            print(f"Failed to retrieve data with ID: {vault_unique_id}")
            return None
