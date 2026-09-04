"""
Zoho Billing Service for Python FastAPI

This service mirrors the Node.js ZohoBillingService functionality,
providing comprehensive Zoho API integration for billing, customers, and subscriptions.

Author: Karthick Chandrasekar
Date: 2025-08-26
Version: 1.0.0

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 1,060-line app/services/zoho_service.py. It is now a package
of mixins by responsibility, combined into one `ZohoBillingService` class
below so that `from app.services.zoho_service import ZohoBillingService,
get_zoho_service, zoho_service` (used throughout the app) needs zero changes.

  config.py                     - platform config selection + validation (__init__)
  auth.py                       - token refresh + make_request dispatcher
  customers.py                  - format_customer_name + customer CRUD
  subscription_with_customer.py - create_subscription_with_customer
  subscription_create.py        - create_subscription (stated exception, see its docstring)
  hosted_pages.py                - create_hosted_page / update_subscription_hosted_page
  subscriptions.py              - get/update/cancel/reactivate subscription + plan-id lookup
  invoices.py                   - invoice list/get/PDF download

All mixins share the same `self` (one ZohoBillingService instance); no two
mixins define the same method name, so MRO order does not matter here.
"""

from typing import Optional

from .config import ConfigMixin
from .auth import AuthMixin
from .customers import CustomersMixin
from .subscription_with_customer import SubscriptionWithCustomerMixin
from .subscription_create import SubscriptionCreateMixin
from .hosted_pages import HostedPagesMixin
from .subscriptions import SubscriptionsMixin
from .invoices import InvoicesMixin


class ZohoBillingService(
    ConfigMixin,
    AuthMixin,
    CustomersMixin,
    SubscriptionWithCustomerMixin,
    SubscriptionCreateMixin,
    HostedPagesMixin,
    SubscriptionsMixin,
    InvoicesMixin,
):
    """Zoho Billing Service for managing customers, plans, and subscriptions (see module docstring for the split map)."""


# Create global instance (default, no platform_name)
zoho_service = ZohoBillingService()


def get_zoho_service(platform_name: Optional[str] = None) -> ZohoBillingService:
    """
    Get Zoho service instance based on platform_name.

    Args:
        platform_name: Platform name (e.g., 'prism7', 'accsell', 'zaptag').
            If one of these, returns service with that platform's Zoho config.

    Returns:
        ZohoBillingService instance configured for the specified platform
    """
    # Only use platform-specific config for known platforms; otherwise default (unchanged from previous flow)
    if platform_name:
        lower = platform_name.lower()
        if lower in ("prism7", "accsell", "zaptag"):
            return ZohoBillingService(platform_name=lower)
    return zoho_service


__all__ = ["ZohoBillingService", "zoho_service", "get_zoho_service"]
