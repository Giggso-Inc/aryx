"""
"No existing user" sub-branch of the /companies (create_company_simple)
company-reactivation flow: a brand new admin user must be created for the
now-reactivated company. Split out of signup_reactivation_simple.py purely
for the 150-line-per-file target — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2 follow-up.
"""

from typing import Any
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from decimal import Decimal
import uuid

from app.core.auth import get_password_hash, create_access_token
from app.models.user import User
from app.models.company import Company
from app.models.subscription_plan import SubscriptionPlan
from app.schemas.company import CompanyCreationResponse
from app.schemas.common import SuccessResponse
from app.routes.public.signup_helpers import _create_subscription_for_company


async def _reactivate_company_new_admin_user(
    db: AsyncSession, existing_company: Company, company_data: Any, password_to_use: str
) -> SuccessResponse[CompanyCreationResponse]:
    """No user existed for this reactivated company's email — create a fresh admin user for it."""
    print(f"🔄 Creating new admin user for reactivated company")
    user_id = uuid.uuid4()
    hashed_password = get_password_hash(password_to_use)

    user = User(
        id=user_id,
        name=company_data.userName,
        email_id=company_data.contactEmail,
        password_hash=hashed_password,
        company_id=existing_company.id,
        role="admin",
        is_active=True,
        created_datetime=datetime.utcnow(),
        updated_datetime=datetime.utcnow()
    )

    db.add(user)
    await db.commit()

    # Create subscription for reactivated company
    await _create_subscription_for_company(existing_company.id, db)

    # Get plan details for the new subscription
    plan_result = await db.execute(
        select(SubscriptionPlan.name, SubscriptionPlan.monthly_price)
        .where(SubscriptionPlan.monthly_price == Decimal('0.00'))
        .limit(1)
    )
    plan = plan_result.fetchone()
    plan_name = plan[0] if plan else "Free Plan"
    plan_id = str(plan[1]) if plan else "free_plan_id"

    access_token = create_access_token(
        data={"sub": str(user.id), "company_id": str(existing_company.id), "role": user.role}
    )
    token_id = str(uuid.uuid4())

    return SuccessResponse(
        success=True,
        data=CompanyCreationResponse(
            customerId=str(existing_company.id),
            companyName=existing_company.name,
            token=access_token,
            tokenId=token_id,
            zohoCustomerId=None,
            planId=plan_id,
            planName=plan_name,
            isDefaultPlan=True
        ),
        message="Company reactivated with new user successfully!",
        code=status.HTTP_200_OK
    )
