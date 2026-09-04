#!/usr/bin/env python3
"""
Debug/introspection helper reporting the current vault storage configuration.

Split out of the former app/services/vault_data_builder.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a).
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def get_environment_info() -> Dict[str, Any]:
    """Get current configuration for debugging"""
    from app.core.config import settings

    storage_env = settings.FILE_UPLOAD_ENV
    cloud_provider = settings.CLOUD_PROVIDER

    config = {
        "FILE_UPLOAD_ENV": storage_env,
        "CLOUD_PROVIDER": cloud_provider,
        "current_configuration": "local" if storage_env == "local" else f"cloud-{cloud_provider}",
    }

    # Add cloud-specific environment variables if configured
    if storage_env == "cloud":
        if cloud_provider == "aws":
            config.update(
                {
                    "AWS_ACCESS_KEY_ID": settings.AWS_ACCESS_KEY_ID,
                    "AWS_REGION": settings.AWS_REGION,
                    "AWS_BUCKET_NAME": settings.AWS_BUCKET_NAME,
                }
            )
        elif cloud_provider == "azure":
            config.update(
                {
                    "AZURE_STORAGE_CONNECTION_STRING": settings.AZURE_STORAGE_CONNECTION_STRING,
                    "AZURE_CONTAINER_NAME": settings.AZURE_CONTAINER_NAME,
                }
            )
        elif cloud_provider == "oracle":
            config.update(
                {
                    "ORACLE_NAMESPACE": settings.ORACLE_NAMESPACE,
                    "ORACLE_BUCKET_NAME": settings.ORACLE_BUCKET_NAME,
                }
            )

    return config
