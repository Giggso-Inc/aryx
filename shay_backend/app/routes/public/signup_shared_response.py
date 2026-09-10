"""
Shared "already exists, bring it back" response-building steps used by both
the company-reactivation path (existing_company found inactive) and the
user-restoration path (existing_user found deactivated) of create_company_simple.
Extracted from signup.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2 follow-up.

The "existing subscription found" response is identical in shape for both
callers (only the success message differs), so it is shared here as
_build_subscription_response_for_existing. The "no subscription found" branch
genuinely differs between the two callers (reactivation returns hardcoded
placeholder token/plan strings with no DB lookup; restoration generates a
real JWT and looks up the actual free plan) so those two stay as separate,
non-shared functions in their respective modules.
"""

from typing import Optional, Any, Tuple
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from decimal import Decimal
import uuid

from app.core.auth import create_access_token
from app.models.company import Company
from app.models.subscription_plan import SubscriptionPlan
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.company import CompanyCreationResponse
from app.schemas.common import SuccessResponse
from app.services.email_verification_service import email_verification_service


async def _send_verification_email_for_restored_user(
    db: AsyncSession, existing_user: User, company_data: Any, event_label: str, context_label: str
) -> None:
    """Send the "welcome back" verification email; failures are logged, never fatal."""
    try:
        print(f"📧 [public/companies] {event_label} user: sending verification email to {existing_user.email_id}")
        verification_token = await email_verification_service.generate_verification_token(
            email=existing_user.email_id,
            company_id=existing_user.company_id,
            user_id=existing_user.id,
            token_type="company_signup",
            db=db
        )
        await db.commit()
        company_name_for_email = (await db.execute(
            select(Company.name).where(Company.id == existing_user.company_id)
        )).scalar_one_or_none() or "Restored Company"
        email_sent = await email_verification_service.send_verification_email(
            email=existing_user.email_id,
            token=verification_token.token,
            company_name=company_name_for_email,
            user_name=company_data.userName or (existing_user.name or existing_user.email_id.split("@")[0]),
            platform_url=getattr(company_data, "platform_url", None),
            platform_name=getattr(company_data, "platform_name", None),
            db=db,
        )
        if email_sent:
            print(f"✅ Verification email sent to {existing_user.email_id} ({context_label})")
        else:
            print(f"⚠️ Failed to send verification email to {existing_user.email_id} ({context_label})")
    except Exception as email_error:
        print(f"⚠️ Verification email error on {context_label} (non-critical): {email_error}")


async def _lookup_company_name_and_subscription(db: AsyncSession, company_id: Any) -> Tuple[Optional[str], Optional[Subscription]]:
    """Fetch the company's display name and its most recent subscription (if any)."""
    existing_subscription_result = await db.execute(
        select(Subscription)
        .where(Subscription.company_id == company_id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    existing_subscription = existing_subscription_result.scalar_one_or_none()

    company_result = await db.execute(
        select(Company.name).where(Company.id == company_id)
    )
    company_name = company_result.scalar_one_or_none()
    return company_name, existing_subscription


async def _build_subscription_response_for_existing(
    db: AsyncSession, existing_user: User, existing_subscription: Subscription, company_name: Optional[str], success_message: str
) -> SuccessResponse[CompanyCreationResponse]:
    """Build the response when the company/user already has a subscription (reactivating it if inactive)."""
    if existing_subscription.status == "inactive" or existing_subscription.subscription_status == "inactive":
        print(f"🔄 Reactivating subscription: {existing_subscription.id}")
        existing_subscription.status = "active"
        existing_subscription.subscription_status = "active"
        existing_subscription.updated_at = datetime.utcnow()
        await db.commit()

    plan_result = await db.execute(
        select(SubscriptionPlan.name, SubscriptionPlan.monthly_price)
        .where(SubscriptionPlan.id == existing_subscription.plan_id)
    )
    plan = plan_result.fetchone()
    plan_name = plan[0] if plan else "Unknown Plan"
    is_default_plan = plan[1] == Decimal('0.00') if plan else False

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
            zohoCustomerId=existing_subscription.zoho_customer_id,
            planId=str(existing_subscription.plan_id),
            planName=plan_name,
            isDefaultPlan=is_default_plan
        ),
        message=success_message,
        code=status.HTTP_200_OK
    )
