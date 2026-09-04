"""
Datasource statistics and type-count schemas.

Split out of the former app/schemas/datasource.py during Phase 5a
file-size compliance work. See app/schemas/datasource/__init__.py for the
full package layout and re-export list.
"""

from typing import List, Dict

from pydantic import BaseModel


class DatasourceStats(BaseModel):
    """Datasource statistics response schema"""
    total_datasources: int
    active_datasources: int
    processed_datasources: int
    pending_datasources: int
    failed_datasources: int
    total_file_size: int
    storage_type_breakdown: Dict[str, int]
    provider_breakdown: Dict[str, int]


class DatasourceTypeCount(BaseModel):
    """Count response for a specific data source type"""
    type: str  # local, cloud, db, app
    count: int


class DatasourceTypeCountResponse(BaseModel):
    """Response schema for data source type count API"""
    counts: List[DatasourceTypeCount]
    total_connected: int
