"""
Payment Gateway routes for Zoho integration (package).

This package is the split of the original monolithic
app/routes/payment_gateway.py (2,505 lines, 13 endpoints) into one module
per resource area. This file combines every submodule's router into a
single `router` for app/routes/__init__.py to mount, in the module order
below.

Module order mirrors the ORIGINAL file's top-to-bottom endpoint order
(by first endpoint appearance) for auditability. It was verified that NONE
of the 13 endpoint paths in this package actually have an overlapping path
shape at the same HTTP method (no literal-segment route is shadowed by a
same-position dynamic segment route) — see the path list below — so
include_router order does not change routing behavior today. The order is
kept anyway so any future submodule addition preserves the same discipline.

Endpoints (method, path -> submodule):
  POST /zoho/subscriptions/hostedPage/create              -> hosted_pages
  POST /zoho/subscriptions/create                         -> subscription_create
  GET  /zoho/subscriptions/fetchByHostedId/{hostedPageId}  -> hosted_pages
  POST /zoho/subscriptions/updateCompanyPlan               -> subscription_plan_update
  PUT  /zoho/subscriptions/hostedPage/update               -> hosted_pages
  POST /zoho/subscriptions/cancel                          -> subscription_cancel
  POST /zoho/subscriptions/reactivate                      -> subscription_cancel
  POST /zoho/subscriptions/validatePayment                 -> validate_payment
  POST /zoho/webhook/subscription                          -> webhook
  POST /zoho/subscriptions/validation/{user_id}            -> subscription_validation
  POST /zoho/subscriptions/fetchCompanySubscriptionDetails -> subscription_details
  POST /zoho/invoices/companyInvoiceDetails                -> invoice_details
  GET  /zoho/invoices/{invoice_id}/download                -> invoice_download
"""

from fastapi import APIRouter

from . import hosted_pages
from . import subscription_create
from . import subscription_plan_update
from . import subscription_cancel
from . import validate_payment
from . import webhook
from . import subscription_validation
from . import subscription_details
from . import invoice_details
from . import invoice_download

router = APIRouter()
router.include_router(hosted_pages.router)
router.include_router(subscription_create.router)
router.include_router(subscription_plan_update.router)
router.include_router(subscription_cancel.router)
router.include_router(validate_payment.router)
router.include_router(webhook.router)
router.include_router(subscription_validation.router)
router.include_router(subscription_details.router)
router.include_router(invoice_details.router)
router.include_router(invoice_download.router)

__all__ = ["router"]
