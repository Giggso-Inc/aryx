"""
Small standalone datasource endpoints: supported log types, environment info.
"""

from typing import Any, Dict, List

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/supported-log-types", response_model=List[str])
async def get_supported_log_types() -> List[str]:
    """Get list of supported log types configured in environment"""
    return settings.SUPPORTED_LOG_TYPES


@router.get("/environment", response_model=Dict[str, Any])
async def get_environment_config() -> Dict[str, Any]:
    """Get current environment configuration for debugging vault settings"""
    from app.services.vault_data_builder import get_environment_info
    return get_environment_info()
