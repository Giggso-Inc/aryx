"""
Branding/logo/name-resolution helpers shared by every notification type:
platform name resolution, display-name normalization, and the logo URL /
embedded-logo-HTML fallback chain (public HTTPS URL -> static asset -> text
badge).

Stated exception (161 lines, over the ~150 target): these are ~12 small,
tightly related one/two-line helpers used by every other notification-type
file; splitting them into two files would force each notification type to
import from two branding modules instead of one for no isolation benefit.
"""

import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from app.core.config import settings


class BrandingMixin:
    """Platform/user-name resolution and email logo rendering."""

    def _brand_header_tagline(self, platform_name: Optional[str] = None) -> str:
        """Return the short Aryx header line used across email templates."""
        return f"{platform_name or self.default_platform_name} | Linked data, Ask, and graph workspaces"

    def _platform_intro_text(self, platform_name: Optional[str] = None) -> str:
        """Return the standard Aryx product description for onboarding emails."""
        display_name = platform_name or self.default_platform_name or "Aryx"
        return (
            f"{display_name} helps teams ingest data, connect records into a searchable knowledge graph, "
            "and ask grounded questions with confidence."
        )

    def _normalize_name(self, raw_name: Optional[str]) -> str:
        """
        Normalize a raw name by replacing common separators with spaces and title-casing the result.
        """
        if not raw_name:
            return ""
        cleaned = re.sub(r"[._\-]+", " ", raw_name)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned.title() if cleaned else ""

    def _resolve_user_name(self, invitation_data: Dict[str, Any], fallback: str = "There") -> str:
        """
        Determine the display name for the invited user, preferring explicit names over email-derived ones.
        """
        provided_name = invitation_data.get('user_name')
        normalized_name = self._normalize_name(provided_name)
        if normalized_name:
            return normalized_name

        email = invitation_data.get('email')
        if email and '@' in email:
            local_part = email.split('@')[0]
            email_based_name = self._normalize_name(local_part)
            if email_based_name:
                return email_based_name

        return fallback

    def _resolve_platform_name(self, invitation_data: Dict[str, Any]) -> str:
        """
        Determine the platform name to surface in invitation content.
        Falls back to company name or default platform name from config if not provided.
        """
        raw = invitation_data.get('platform_name')
        if raw and str(raw).strip():
            return str(raw).strip()

        fallback = invitation_data.get('company_name')
        if fallback and str(fallback).strip():
            return str(fallback).strip()

        return self.default_platform_name

    def _replace_placeholders(self, template: str, placeholders: dict) -> str:
        """Replace {key} with value in template. Order by key length desc to avoid partial matches. No .format() so braces in values are safe."""
        for key in sorted(placeholders.keys(), key=len, reverse=True):
            template = template.replace("{" + key + "}", str(placeholders[key]))
        return template

    def _get_platform_logo_url(self, platform_name: Optional[str]) -> Optional[str]:
        """Return logo URL only for accsell and zaptag; other platforms (e.g. prism7) unchanged, return None."""
        slug = (platform_name or '').lower()
        if slug == 'accsell':
            return settings.SHAY_LOGO_URL
        if slug == 'zaptag':
            return settings.ZAPTAG_LOGO_URL
        return None

    def _is_accsell_or_zaptag(self, platform_name: Optional[str]) -> bool:
        """True only for Accsell and Zaptag; limits added-user flow to these platforms, previous flow for others."""
        slug = (platform_name or '').strip().lower()
        return slug in ('accsell', 'zaptag')

    def _is_public_logo_url(self, value: Optional[str]) -> bool:
        """Return True when a configured logo value is a usable public HTTP(S) URL."""
        if not value:
            return False
        return value.startswith("https://") or value.startswith("http://")

    def _url_origin(self, value: Optional[str]) -> Optional[str]:
        """Return scheme + host origin for a public URL, dropping any path/query."""
        if not self._is_public_logo_url(value):
            return None
        parts = urlsplit(value)
        if not parts.scheme or not parts.netloc:
            return None
        return f"{parts.scheme}://{parts.netloc}"

    def _get_default_logo_url(self, platform_url: Optional[str] = None) -> Optional[str]:
        """Return the shared Aryx logo URL when a public static asset is available."""
        logo_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "static",
            "email",
            "logo.png",
        )
        if not os.path.isfile(logo_path):
            return None

        candidate_bases: List[str] = []
        public_backend_origin = self._url_origin(settings.SHAY_BE_PUBLIC_URL)
        if public_backend_origin:
            candidate_bases.append(public_backend_origin)
        if platform_url:
            platform_origin = self._url_origin(platform_url)
            if platform_origin:
                candidate_bases.append(platform_origin)

        for candidate_base in candidate_bases:
            return f"{candidate_base}/static/email/logo.png"
        return None

    def _get_email_logo_url(
        self, platform_name: Optional[str] = None, platform_url: Optional[str] = None
    ) -> Optional[str]:
        """Return the safest public logo URL for email clients."""
        platform_logo_url = self._get_platform_logo_url(platform_name)
        if self._is_public_logo_url(platform_logo_url):
            return platform_logo_url
        return self._get_default_logo_url(platform_url)

    def _get_embedded_logo_html(
        self, platform_name: Optional[str] = None, platform_url: Optional[str] = None
    ) -> str:
        """Return compact hosted-logo markup for emails without Gmail clipping."""
        brand = (platform_name or self.default_platform_name or "Aryx").strip() or "Aryx"
        logo_url = self._get_email_logo_url(platform_name, platform_url)
        if logo_url:
            return (
                f'<img src="{logo_url}" alt="{brand}" '
                'style="max-width: 180px; max-height: 48px; width: auto; height: auto; display: inline-block;" />'
            )
        return (
            f'<div style="display:inline-block;padding:10px 14px;border-radius:999px;'
            f'background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.18);'
            f'color:#FFFFFF;font-size:16px;line-height:1;font-weight:700;letter-spacing:0.04em;">'
            f'{brand}</div>'
        )
