"""Vault-unique-id generation."""

import uuid


class IdsMixin:
    """Generate hierarchical vault identifiers."""

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
