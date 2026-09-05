"""
Deactivated-user/company restoration branch for POST /companies
(create_company_simple) — hit when an existing user is found by email but
either the user or their company (or both) is currently inactive. Extracted
from signup.py — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a
item 2 follow-up.
"""

from typing import Optional
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from decimal import Decimal
import uuid

from app.core.auth import get_password_hash, create_access_token
from app.models.user import User
from app.models.subscription_plan import SubscriptionPlan
from app.schemas.company import CompanyCreationResponse
from app.schemas.common import SuccessResponse
from app.routes.public.signup_helpers import _create_subscription_for_company
from app.routes.public.signup_shared_response import (
    _send_verification_email_for_restored_user,
    _lookup_company_name_and_subscription,
    _build_subscription_response_for_existing,
)


async def _restore_no_subscription_response(
    db: AsyncSession, existing_user: User, company_name: Optional[str]
) -> SuccessResponse[CompanyCreationResponse]:
    """Build the restoration response when the company has no subscription row yet (creates one, looks up the real free plan)."""
    await _create_subscription_for_company(existing_user.company_id, db)

    plan_result = await db.execute(
        select(SubscriptionPlan.name, SubscriptionPlan.monthly_price)
        .where(SubscriptionPlan.monthly_price == Decimal('0.00'))
        .limit(1)
    )
    plan = plan_result.fetchone()
    plan_name = plan[0] if plan else "Free Plan"
    plan_id = str(plan[1]) if plan else "free_plan_id"

    access_token = create_access_token(
        data={"sub": str(existing_user.id), "company_id": str(existing_user.company_id), "role": existing_user.role}
    )
    token_id = str(uuid.uuid4())

    return SuccessResponse(
        success=True,
        data=CompanyCreationResponse(
            customerId=str(existing_user.company_id),
            companyName=company_name or "Restored Company",
            token=access_token,
            tokenId=token_id,
            zohoCustomerId=None,
            planId=plan_id,
            planName=plan_name,
            isDefaultPlan=True
        ),
        message="Company and user restored successfully!",
        code=status.HTTP_200_OK
    )


def _restore_deactivated_fields(existing_user: User, password_to_use: str, user_name: Optional[str]) -> None:
    """Flip the user/company back to active and refresh the user's credentials."""
    if not existing_user.company.is_active:
        existing_user.company.is_active = True
        existing_user.company.updated_at = datetime.utcnow()
        print("✅ Organization restored successfully")

    if not existing_user.is_active:
        existing_user.is_active = True
        existing_user.is_verified = False  # Reset verification status on restoration
        existing_user.updated_datetime = datetime.utcnow()
        print("✅ User restored successfully")

    existing_user.password_hash = get_password_hash(password_to_use)

    if user_name:
        existing_user.name = user_name


async def _restore_deactivated_user_and_company(
    db: AsyncSession, existing_user: User, company_data, password_to_use: str
) -> SuccessResponse[CompanyCreationResponse]:
    """Orchestrate restoration of a deactivated user and/or its deactivated company."""
    print(f"🔄 Restoring deactivated user/organization: {existing_user.id}")

    _restore_deactivated_fields(existing_user, password_to_use, company_data.userName)

    await db.commit()

    # Send verification email on re-onboarding (same as new company flow)
    await _send_verification_email_for_restored_user(db, existing_user, company_data, "Restored", "re-onboarding")

    company_name, existing_subscription = await _lookup_company_name_and_subscription(db, existing_user.company_id)

    if existing_subscription:
        return await _build_subscription_response_for_existing(
            db, existing_user, existing_subscription, company_name, "Company and user restored successfully!"
        )
    return await _restore_no_subscription_response(db, existing_user, company_name)
