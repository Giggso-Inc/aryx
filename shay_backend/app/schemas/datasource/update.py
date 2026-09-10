"""
Datasource update request schema.

Split out of the former app/schemas/datasource/core.py during Phase 5b
file-size compliance work. See app/schemas/datasource/__init__.py for the
full package layout and re-export list.
"""

from typing import Optional, Dict, Any

from pydantic import BaseModel, Field

from .config import DatasourceConfig


class DatasourceUpdate(BaseModel):
    """Datasource update request"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    log_type: Optional[str] = Field(None, description="Type of log (e.g., android, kubernetes, python)")
    is_active: Optional[bool] = None
    is_connected: Optional[bool] = None
    config: Optional[DatasourceConfig] = None
    datasource_metadata: Optional[Dict[str, Any]] = None
