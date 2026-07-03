"""
Vault Service for Secure Data Storage

This module provides a service layer for interacting with external vault APIs to store
sensitive datasource configuration data securely. It handles base64 encoded environment
variables for endpoint and token configuration, and provides methods for saving data
to vault and generating unique vault identifiers.

Author: Karthick Chandrasekar
Version: 1.0.0
Date: 2025-08-13
"""

import os  # For accessing environment variables
import json  # For JSON data handling (though not directly used in current implementation)
import uuid  # For generating unique identifiers
import base64  # For decoding base64 encoded environment variables
from typing import Dict, Any, Optional  # For type hints and annotations
import httpx  # For making asynchronous HTTP requests to vault API
from datetime import datetime  # For timestamp handling (though not directly used in current implementation)

from app.core.config import settings  # For application configuration settings


class VaultService:
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
    
    def generate_vault_unique_id(self, user_id: str, app_key: str = "datasource") -> str:
        """
        Generate a unique vault identifier for organizing vault entries.
        
        This method creates a structured, unique identifier that combines user information
        with a random component to ensure uniqueness across the vault system. The generated
        ID follows a hierarchical pattern that makes it easy to organize and locate vault
        entries by user and application context.
        
        Args:
            user_id (str): The unique identifier of the user requesting vault storage.
                          Used to create user-specific vault organization.
            app_key (str, optional): Application context key for the vault entry.
                                   Defaults to "datasource" for datasource-related storage.
                                   Can be customized for different application modules.
            
        Returns:
            str: A unique vault identifier in the format "user_id_prefix/random_string".
                 Example: "5d97b1ed/abc12345"
            
        Design Considerations:
            - Uses first 8 characters of user_id to maintain readability
            - Appends 8 random characters from UUID for uniqueness
            - Total length fits within VARCHAR(50) database constraints
            - Hierarchical structure enables easy vault organization
            - Random component prevents ID collisions between users
            
        Example:
            >>> vault_service = VaultService()
            >>> vault_id = vault_service.generate_vault_unique_id("5d97b1ed-9c78-4a70-9b4e-74d556d35bad")
            >>> print(vault_id)  # "5d97b1ed/abc12345"
        """
        # Generate a random 8-character string from UUID for uniqueness
        random_string = str(uuid.uuid4())[:8]
        
        # Create a shorter ID that will fit in VARCHAR(50) as fallback
        # Use first 8 chars of user_id + random string for hierarchical organization
        short_user_id = user_id[:8]
        
        # Return hierarchical identifier: user_prefix/random_string
        return f"{short_user_id}/{random_string}"


# Global vault service instance
# This singleton instance is used throughout the application for vault operations
# It maintains the decoded configuration and provides vault functionality to other modules
vault_service = VaultService() 