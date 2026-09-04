"""
Embedding status and ML-webhook request/response schemas.

Split out of the former app/schemas/datasource.py during Phase 5a
file-size compliance work. See app/schemas/datasource/__init__.py for the
full package layout and re-export list.
"""

from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


class EmbeddingStatusResponse(BaseModel):
    """Response schema for embedding status by channel"""
    channel_id: str
    total_datasources: int
    embedding_required: int  # Count of datasources requiring embedding
    in_progress: int  # Count of datasources with embedding_status = 1
    completed: int  # Count of datasources with embedding_status = 2
    failed: int  # Count of datasources with embedding_status = 3
    not_required: int  # Count of datasources with embedding_status = 0
    datasources: List[Dict[str, Any]]  # List of datasources with their embedding status


class MLWebhookRequest(BaseModel):
    """Webhook request from ML team for embedding completion status"""
    vaultUniqueIds: List[str] = Field(..., alias="vaultUniqueIds", description="List of vault_unique_ids that were processed")
    status: str = Field(..., pattern="^(success|failed)$", description="Overall status of the embedding process")
    message: Optional[str] = Field(None, description="Status message")
    processingTime: Optional[int] = Field(None, alias="processingTime", description="Processing time in milliseconds")

    class Config:
        allow_population_by_field_name = True


class MLWebhookResponse(BaseModel):
    """Response for ML webhook"""
    message: str
    processed_count: int
    failed_count: int


class RegenerateEmbeddingResponse(BaseModel):
    """Response model for regenerate embedding API"""
    success: bool
    message: str
    datasource_id: str
    embedding_status: int
    status_description: str
