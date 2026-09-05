"""
Template service for fetching and processing email templates.

This module provides functionality to fetch template content by template_id
and process templates for email invitations.

Author: AI Assistant
Date: 2025-01-27
Version: 1.0.0

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): this used to be a single
311-line app/services/template_service.py. It is now a package of mixins by
responsibility, combined into one TemplateService class below so that
`from app.services.template_service import TemplateService, template_service`
(used throughout the app) needs zero changes.

  fetch.py            - get_template_content (DB lookup + on-disk read)
  process.py          - process_template_content (variable substitution)
  default_template.py - get_default_invitation_template (built-in HTML fallback)
"""

from app.core.config import settings
from .default_template import DefaultTemplateMixin
from .fetch import FetchMixin
from .process import ProcessMixin


class TemplateService(FetchMixin, ProcessMixin, DefaultTemplateMixin):
    """Service for managing email templates"""

    def __init__(self):
        """Initialize template service"""
        self.template_dir = settings.TEMPLATE_DIR


# Create a singleton instance
template_service = TemplateService()
