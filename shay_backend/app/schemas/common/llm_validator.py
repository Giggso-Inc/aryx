"""
LLM validation request+response schemas.

Split out of the former app/schemas/common.py to keep each file under the
Raven 150-line style limit.
"""

from typing import Optional
from pydantic import BaseModel, Field


class LLMValidatorRequest(BaseModel):
    """Request schema for LLM validation API"""
    llmType: str = Field(..., description="LLM type: 'azureopenai', 'chatgpt', or 'gemini'")
    llmApiKey: str = Field(..., description="Base64 encoded API key")
    llmModelName: str = Field(..., description="Model name (deployment name for Azure, model name for OpenAI/Gemini)")
    llmApiVersion: Optional[str] = Field(None, description="API version (required for Azure OpenAI)")
    llmEndpoint: Optional[str] = Field(None, description="Endpoint URL (required for Azure OpenAI)")


class LLMValidatorResponse(BaseModel):
    """Response schema for LLM validation API"""
    status: str = Field(..., description="Validation status: 'success' or 'failed'")
    type: str = Field(..., description="Error type if failed (e.g., 'invalid_key', 'quota_issue', 'resource_issue')")
    cost: float = Field(0.0, description="Cost of the validation request")
    message: str = Field(..., description="Validation message")
