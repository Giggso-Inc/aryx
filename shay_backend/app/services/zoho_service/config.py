"""
Platform-config selection and validation for ZohoBillingService: the
constructor picks which set of env vars (default / PRISM_ / SHAY_ /
ZAPTAG_) this instance talks to Zoho with.
"""

import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class ConfigMixin:
    """Constructor + config-name/validation helpers."""

    def __init__(self, platform_name: Optional[str] = None):
        """
        Initialize Zoho Billing Service

        Args:
            platform_name: Platform name (e.g., 'prism7', 'accsell', 'zaptag').
                If 'prism7', uses PRISM config; if 'accsell', uses SHAY config;
                if 'zaptag', uses ZAPTAG config; otherwise uses default Zoho config.
        """
        self.platform_name = platform_name
        platform_lower = (platform_name or "").lower()
        self.is_prism = platform_lower == "prism7"
        # Prefix for platform-specific env vars (e.g. PRISM_, SHAY_, ZAPTAG_); empty for default
        self._config_prefix = ""
        # Use platform-specific config when platform_name is prism7, accsell, or zaptag
        if platform_lower == "prism7":
            self._config_prefix = "PRISM_"
            self.base_url = f"{settings.PRISM_ZOHO_BASE_URL}/billing/v1"
            self.org_id = settings.PRISM_ZOHO_ORGANIZATION_ID
            self.client_id = settings.PRISM_ZOHO_CLIENT_ID
            self.client_secret = settings.PRISM_ZOHO_CLIENT_SECRET
            self.refresh_token = settings.PRISM_ZOHO_REFRESH_TOKEN
            self.token_url = settings.PRISM_ZOHO_TOKEN_URL
        elif platform_lower == "accsell":
            self._config_prefix = "SHAY_"
            self.base_url = f"{settings.SHAY_ZOHO_BASE_URL}/billing/v1"
            self.org_id = settings.SHAY_ZOHO_ORGANIZATION_ID
            self.client_id = settings.SHAY_ZOHO_CLIENT_ID
            self.client_secret = settings.SHAY_ZOHO_CLIENT_SECRET
            self.refresh_token = settings.SHAY_ZOHO_REFRESH_TOKEN
            self.token_url = settings.SHAY_ZOHO_TOKEN_URL
        elif platform_lower == "zaptag":
            self._config_prefix = "ZAPTAG_"
            self.base_url = f"{settings.ZAPTAG_ZOHO_BASE_URL}/billing/v1"
            self.org_id = settings.ZAPTAG_ZOHO_ORGANIZATION_ID
            self.client_id = settings.ZAPTAG_ZOHO_CLIENT_ID
            self.client_secret = settings.ZAPTAG_ZOHO_CLIENT_SECRET
            self.refresh_token = settings.ZAPTAG_ZOHO_REFRESH_TOKEN
            self.token_url = settings.ZAPTAG_ZOHO_TOKEN_URL
        else:
            # Default Zoho config — unchanged from previous behavior (no platform_name or unknown value)
            self.base_url = f"{settings.ZOHO_BASE_URL}/billing/v1"
            self.org_id = settings.ZOHO_ORGANIZATION_ID
            self.client_id = settings.ZOHO_CLIENT_ID
            self.client_secret = settings.ZOHO_CLIENT_SECRET
            self.refresh_token = settings.ZOHO_REFRESH_TOKEN
            self.token_url = settings.ZOHO_TOKEN_URL

        # Validate configuration
        self._validate_config()

    def get_config_var_name(self, suffix: str) -> str:
        """Return env var name for this platform (e.g. PRISM_ZOHO_REFRESH_TOKEN or ZOHO_REFRESH_TOKEN)."""
        return f"{self._config_prefix}{suffix}" if self._config_prefix else suffix

    def _validate_config(self) -> None:
        """Validate Zoho configuration for current platform"""
        if self._config_prefix:
            # Platform-specific (prism7, accsell, zaptag) required env vars
            required_vars = [
                f"{self._config_prefix}ZOHO_BASE_URL",
                f"{self._config_prefix}ZOHO_ORGANIZATION_ID",
                f"{self._config_prefix}ZOHO_REFRESH_TOKEN",
                f"{self._config_prefix}ZOHO_CLIENT_ID",
                f"{self._config_prefix}ZOHO_CLIENT_SECRET",
                f"{self._config_prefix}ZOHO_TOKEN_URL",
            ]
            platform_label = self._config_prefix.rstrip("_").upper()
        else:
            required_vars = [
                "ZOHO_BASE_URL",
                "ZOHO_ORGANIZATION_ID",
                "ZOHO_REFRESH_TOKEN",
                "ZOHO_CLIENT_ID",
                "ZOHO_CLIENT_SECRET",
                "ZOHO_TOKEN_URL",
            ]
            platform_label = "Default"

        missing_vars = []
        for var in required_vars:
            if not getattr(settings, var, None):
                missing_vars.append(var)

        if missing_vars:
            logger.warning(f"⚠️ Missing {platform_label} Zoho configuration variables: {missing_vars}")
            logger.warning(f"⚠️ {platform_label} Zoho integration will not work without these variables")
