"""
GGDatasource connection/processing/type-count schemas.

Split out of the former app/schemas/gg_datasource.py to keep each file
under the Raven 150-line style limit.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DatasourceTypeCount(BaseModel):
    type:  str   # local | cloud | app | database
    count: int


class DatasourceTypeCountResponse(BaseModel):
    counts:          List[DatasourceTypeCount]
    total_connected: int


class DatasourceConnectionResponse(BaseModel):
    datasource_id: str
    is_connected:  bool
    message:       str
    updated_at:    Optional[datetime] = None


class DatasourceConnectionRequest(BaseModel):
    datasource_ids: List[str] = Field(..., min_length=1, max_length=100)
    action:         str = Field(..., pattern="^(connect|disconnect)$")


class DatasourceBulkConnectionResponse(BaseModel):
    successful_operations: List[DatasourceConnectionResponse]
    failed_operations:     List[Dict[str, Any]]
    total_successful:      int
    total_failed:          int
    action_performed:      str
    message:               str


class DatasourceProcessingRequest(BaseModel):
    datasource_id: str


class DatasourceProcessingResponse(BaseModel):
    datasource_id: str
    status:        str
    message:       str
