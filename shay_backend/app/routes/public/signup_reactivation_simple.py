"""
Inactive-company reactivation branch for POST /companies (create_company_simple).
Extracted from signup.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2 follow-up.
"""

from typing import Optional, Any
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.core.auth import get_password_hash
from app.models.user import User
from app.models.company import Company
from app.schemas.company import CompanyCreationResponse
from app.schemas.common import SuccessResponse
from app.routes.public.signup_helpers import _create_subscription_for_company
from app.routes.public.signup_reactivation_new_admin import _reactivate_company_new_admin_user
from app.routes.public.signup_shared_response import (
    _send_verification_email_for_restored_user,
    _lookup_company_name_and_subscription,
    _build_subscription_response_for_existing,
)


def _reactivate_company_fields(existing_company: Company, company_data: Any) -> None:
    """Mark the company active again and stamp its settings.emailId from the signup payload."""
    existing_company.is_active = True
    existing_company.updated_at = datetime.utcnow()
    if company_data.contactEmail:
        if not existing_company.settings:
            existing_company.settings = {}
        existing_company.settings["emailId"] = company_data.contactEmail


async def _reactivate_no_subscription_response(
    db: AsyncSession, existing_user: User, company_name: Optional[str]
) -> SuccessResponse[CompanyCreationResponse]:
    """Build the reactivation response when the company has no subscription row yet (placeholder token/plan)."""
    await _create_subscription_for_company(existing_user.company_id, db)

    return SuccessResponse(
        success=True,
        data=CompanyCreationResponse(
            customerId=str(existing_user.company_id),
            companyName=company_name or "Restored Company",
            token="new_token_for_reactivated_company",
            tokenId="new_token_id",
            zohoCustomerId=None,
            planId="free_plan_id",
            planName="Free Plan",
            isDefaultPlan=True
        ),
        message="Company and user reactivated successfully!",
        code=status.HTTP_200_OK
    )


async def _reactivate_existing_user_in_company(
    db: AsyncSession, existing_user: User, company_data: Any, password_to_use: str
) -> SuccessResponse[CompanyCreationResponse]:
    """Reactivate a user that already belongs to the (now-reactivated) company."""
    print(f"🔄 Reactivating existing user: {existing_user.id}")
    existing_user.is_active = True
    existing_user.is_verified = False  # Reset verification status on reactivation
    existing_user.updated_datetime = datetime.utcnow()
    existing_user.password_hash = get_password_hash(password_to_use)

    if company_data.userName:
        existing_user.name = company_data.userName

    await db.commit()

    # Send verification email on reactivation (same as new company flow)
    await _send_verification_email_for_restored_user(db, existing_user, company_data, "Reactivated", "reactivation")

    company_name, existing_subscription = await _lookup_company_name_and_subscription(db, existing_user.company_id)

    if existing_subscription:
        return await _build_subscription_response_for_existing(
            db, existing_user, existing_subscription, company_name, "Company and user reactivated successfully!"
        )
    return await _reactivate_no_subscription_response(db, existing_user, company_name)


async def _reactivate_company_simple(
    db: AsyncSession, existing_company: Company, existing_user: Optional[User], company_data: Any, password_to_use: str
) -> SuccessResponse[CompanyCreationResponse]:
    """Orchestrate reactivation of an inactive company for the /companies (simple) endpoint."""
    print(f"🔄 Reactivating inactive company: {existing_company.id}")
    _reactivate_company_fields(existing_company, company_data)

    if existing_user:
        if existing_user.company_id != existing_company.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email already exists and belongs to a different company"
            )
        return await _reactivate_existing_user_in_company(db, existing_user, company_data, password_to_use)

    return await _reactivate_company_new_admin_user(db, existing_company, company_data, password_to_use)
