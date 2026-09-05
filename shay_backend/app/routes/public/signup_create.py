"""
Fresh-company-creation path for POST /createCompany (create_company) — hit
when neither an existing (reactivatable) company nor an existing user was
found. Extracted from signup.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2 follow-up.
"""

from typing import Any
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
from decimal import Decimal
import uuid

from app.core.auth import generate_company_id, create_access_token, get_password_hash
from app.core.config import settings
from app.models.user import User
from app.models.company import Company
from app.models.subscription_plan import SubscriptionPlan
from app.models.subscription import Subscription
from app.schemas.common import SuccessResponse
from app.routes.public.signup_helpers import _create_placeholder_gpt_vault_for_company


async def _create_new_company_with_user(
    db: AsyncSession, company_data: Any, user_data: dict
) -> SuccessResponse[dict]:
    """Create a brand new company, its admin user, and its initial free subscription."""
    company_id = generate_company_id()
    company = Company(
        id=company_id,
        name=company_data.name,
        domain=company_data.domain,
        description=company_data.description,
        subscription_plan=company_data.subscription_plan,
        max_users=company_data.max_users,
        max_workspaces=company_data.max_workspaces,
        max_storage_gb=company_data.max_storage_gb,
        ai_enabled=company_data.ai_enabled,
        ai_provider=company_data.ai_provider,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    db.add(company)
    await db.flush()  # Get the company ID without committing

    # Create placeholder gpt_token in gg_vault for dev/prod only (not marketplace)
    if not settings.IS_MARKETPLACE:
        await _create_placeholder_gpt_vault_for_company(db, company_id)
    else:
        # Marketplace: skip automatic gg_vault; token can be set later via saveTokenDetails
        pass

    # Create admin user
    user_id = uuid.uuid4()
    hashed_password = get_password_hash(user_data["password"])

    user = User(
        id=user_id,
        name=company_data.userName,  # Use the userName from the company data
        email_id=user_data["email"],
        password_hash=hashed_password,
        company_id=company_id,
        role="admin",
        is_active=True,
        created_datetime=datetime.utcnow(),
        updated_datetime=datetime.utcnow()
    )

    db.add(user)
    await db.flush()

    # Find a default free plan for initial subscription
    default_plan_result = await db.execute(
        select(SubscriptionPlan).where(
            SubscriptionPlan.is_active == True,
            SubscriptionPlan.monthly_price == Decimal('0.00')
        ).limit(1)
    )
    default_plan = default_plan_result.scalar_one_or_none()

    if not default_plan:
        # If no free plan exists, we'll need to handle this case
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No free subscription plan available for initial setup"
        )

    # Create initial subscription (free plan)
    subscription_id = uuid.uuid4()
    subscription = Subscription(
        id=subscription_id,
        company_id=company_id,
        plan_id=default_plan.id,  # Use the found free plan
        status="active",
        subscription_status="active",
        amount=Decimal('0.00'),
        currency_code="USD",
        billing_cycle="monthly",
        auto_collect=True,
        current_period_start=datetime.utcnow(),
        current_period_end=datetime.utcnow() + timedelta(days=30),
        next_billing_date=datetime.utcnow() + timedelta(days=30),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    db.add(subscription)

    # Commit all changes
    await db.commit()

    # Generate API token for the user
    access_token = create_access_token(
        data={"sub": str(user_id), "company_id": str(company_id), "role": "admin"}
    )

    # Return response similar to Node.js API
    return SuccessResponse(
        success=True,
        data={
            "status": "success",
            "message": "Company created successfully",
            "data": {
                "customer_id": str(company_id),
                "company_name": company.name,
                "api_token": access_token,
                "zoho_customer_id": None,  # Will be set when integrated with Zoho
                "user": {
                    "id": str(user_id),
                    "email": user.email_id,
                    "role": user.role
                }
            }
        },
        message="Company created successfully",
        code=status.HTTP_200_OK
    )
