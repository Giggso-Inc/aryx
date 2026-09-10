"""
GGDatasource embedding-status / ML-webhook schemas.

Split out of the former app/schemas/gg_datasource.py to keep each file
under the Raven 150-line style limit.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class GGEmbeddingStatusResponse(BaseModel):
    scope_level:         str
    scope_id:            str
    total_datasources:   int
    embedding_required:  int
    in_progress:         int
    completed:           int
    failed:              int
    not_required:        int
    datasources:         List[Dict[str, Any]]


class MLWebhookRequest(BaseModel):
    vaultUniqueIds: List[str]
    status:         str   # success | failed
    message:        Optional[str] = None
    processingTime: Optional[int] = None

    model_config = {"populate_by_name": True}


class MLWebhookResponse(BaseModel):
    message:         str
    processed_count: int
    failed_count:    int


class RegenerateEmbeddingResponse(BaseModel):
    success:            bool
    message:            str
    datasource_id:      str
    embedding_status:   int
    status_description: str
