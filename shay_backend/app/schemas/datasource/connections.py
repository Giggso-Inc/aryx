"""
Datasource connect/disconnect request+response schemas.

Split out of the former app/schemas/datasource.py during Phase 5a
file-size compliance work. See app/schemas/datasource/__init__.py for the
full package layout and re-export list.
"""

from datetime import datetime
from typing import List, Dict, Any

from pydantic import BaseModel, Field


class DatasourceConnectionResponse(BaseModel):
    """Response for datasource connection operations"""
    datasource_id: str
    is_connected: bool
    message: str
    updated_at: datetime


class DatasourceConnectionRequest(BaseModel):
    """Request for datasource connection operations"""
    datasource_ids: List[str] = Field(..., min_items=1, max_items=100, description="List of datasource IDs to connect/disconnect")
    action: str = Field(..., pattern="^(connect|disconnect)$", description="Action to perform: connect or disconnect")


class DatasourceBulkConnectionResponse(BaseModel):
    """Response for bulk datasource connection operations"""
    successful_operations: List[DatasourceConnectionResponse]
    failed_operations: List[Dict[str, Any]]
    total_successful: int
    total_failed: int
    action_performed: str
    message: str
