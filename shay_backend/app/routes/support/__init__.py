"""
Customer support routes.

User-initiated support form: submit name, email, description (optional subject).
Stores in gg_support_requests, notifies SUPPORT_EMAIL, and optionally sends confirmation to user.
GET by company_id, GET by id, UPDATE and DELETE require authentication and company access.

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5): this used to be a
single 288-line app/routes/support.py. It is now a package of submodules by
endpoint (submit, company_list, detail — GET/PUT/DELETE combined since they
share the `/{request_id}` path), combined into one `router` below so that
`from .support import router as support_router` (used by
app/routes/__init__.py) needs zero changes.

Route registration order matches the original file's declaration order:
POST /submit, GET /company/{company_id}, GET/PUT/DELETE /{request_id}.
"/company/{company_id}" and "/{request_id}" are both single-dynamic-segment
paths but differ in their literal first path component ("company" vs. a
UUID), so there is no ambiguity regardless of order; registration order is
preserved anyway per the wave B5 plan.
"""

from fastapi import APIRouter

from . import submit
from . import company_list
from . import detail
from .helpers import (
    _support_detail_from_model,
    _generate_ticket_reference,
    _can_access_support_request,
    _can_access_company_support,
)

router = APIRouter()
router.include_router(submit.router)
router.include_router(company_list.router)
router.include_router(detail.router)

__all__ = [
    "router",
    "_support_detail_from_model",
    "_generate_ticket_reference",
    "_can_access_support_request",
    "_can_access_company_support",
]
