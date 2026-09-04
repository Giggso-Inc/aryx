"""
Public routes for company signup and onboarding.

This package handles public API endpoints that don't require authentication,
including company creation, plan fetching, and initial user setup. It was
split from a single 2,196-line app/routes/public.py into per-resource
submodules (see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5).

`router` is re-exported so `from app.routes.public import router` (used by
app/routes/__init__.py and main.py) needs no changes.

Author: Karthick Chandrasekar
Date: 2025-08-26
Version: 1.0.0
"""

from fastapi import APIRouter

from . import signup, users, delete, reactivate, plans, subscription, auth, verification, zoho, notifications, vault

router = APIRouter()

router.include_router(signup.router)
router.include_router(users.router)
router.include_router(delete.router)
router.include_router(reactivate.router)
router.include_router(plans.router)
router.include_router(subscription.router)
router.include_router(auth.router)
router.include_router(verification.router)
router.include_router(zoho.router)
router.include_router(notifications.router)
router.include_router(vault.router)

__all__ = ["router"]
