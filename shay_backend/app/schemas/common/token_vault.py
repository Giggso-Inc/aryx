"""
Token-vault (save/fetch/delete) request+response schemas.

Split out of the former app/schemas/common.py to keep each file under the
Raven 150-line style limit.
"""

from typing import Optional
from pydantic import BaseModel, Field


class SaveTokenDetailsRequest(BaseModel):
    """Request schema for public saveTokenDetails - token/config stored in vault without JWT."""
    token_type: str = Field(..., description="Token type (e.g. openai, anthropic, azure)")
    tokenName: str = Field(..., description="Display name for the token (stored in vault)")
    api_key: str = Field(..., description="API key to store securely in vault")
    embedding_model: str = Field(..., description="Embedding model identifier")
    gpt_model: str = Field(..., description="GPT/LLM model identifier")
    companyId: str = Field(..., description="Company ID to associate with the vault entry")
    # Azure-specific (required when token_type is azure)
    deploymentName: Optional[str] = Field(None, description="Azure deployment name (required when token_type is azure)")
    deploymentVersion: Optional[str] = Field(None, description="Azure deployment version (required when token_type is azure)")
    endpoint: Optional[str] = Field(None, description="Azure endpoint URL (required when token_type is azure)")


class SaveTokenDetailsResponse(BaseModel):
    """Response schema for saveTokenDetails - returns vault identifiers."""
    vault_unique_id: str = Field(..., description="Vault unique ID used for external vault storage")
    giggso_vault_id: str = Field(..., description="Primary key of the gg_vault record (UUID)")


class FetchTokenDetailsRequest(BaseModel):
    """Request schema for fetching token details for a company (authenticated)."""
    companyId: str = Field(..., description="Company ID to fetch token details for")


class FetchTokenDetailsResponse(BaseModel):
    """Response schema for fetching token details from vault."""
    vault_unique_id: str = Field(..., description="Vault unique ID used for external vault storage")
    giggso_vault_id: str = Field(..., description="Primary key of the gg_vault record (UUID)")
    token_details: dict = Field(..., description="Token details fetched from vault")


class DeleteTokenDetailsRequest(BaseModel):
    """Request schema for deleting token details for a company (authenticated)."""
    companyId: str = Field(..., description="Company ID to delete token details for")


class DeleteTokenDetailsResponse(BaseModel):
    """Response schema for deleting token details from vault + gg_vault."""
    deleted: bool = Field(..., description="Whether the delete operation completed")
    vault_unique_id: Optional[str] = Field(None, description="Vault unique ID that was deleted")
    giggso_vault_id: Optional[str] = Field(None, description="gg_vault record ID that was deleted")
