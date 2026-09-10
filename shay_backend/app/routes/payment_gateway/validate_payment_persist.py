"""
DB upsert + company activation for validate_payment.

Extracted from validate_payment.py (Raven style compliance, wave B): once
payment has been validated, this finds-or-creates the local Subscription
row (delegated to validate_payment_subscription_upsert), activates the
Company, deactivates the company's other subscriptions, and commits. Any
error here is rolled back and re-raised as an HTTPException(500) exactly
as in the original inline try/except, so it still passes through
validate_payment's own `except HTTPException: raise`.
"""

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.subscription import Subscription
from app.schemas.common import SuccessResponse

from .validate_payment_dates import _parse_subscription_dates
from .validate_payment_subscription_upsert import _upsert_local_subscription

logger = logging.getLogger(__name__)


async def _persist_subscription_and_activate(
    db: AsyncSession,
    company_id: Any,
    subscription_data: dict,
    subscription_id_from_data: str,
    subscription_amount: Any,
) -> SuccessResponse:
    try:
        # Get customer data
        customer = subscription_data.get('customer', {})
        customer_id = customer.get('customer_id')
        customer_email = customer.get('email')  # noqa: F841 - kept for parity with original (unused there too)

        # Get plan data
        plan = subscription_data.get('plan', {})
        plan_code = plan.get('plan_code')
        plan_name = plan.get('name')

        # Verify company exists
        company_result = await db.execute(
            select(Company).where(Company.id == company_id)
        )
        company = company_result.scalar_one_or_none()

        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found"
            )

        created_time, next_billing_date = _parse_subscription_dates(subscription_data)

        await _upsert_local_subscription(
            db, company_id, subscription_data, subscription_id_from_data,
            subscription_amount, customer_id, plan_code, created_time, next_billing_date
        )

        # Update company subscription plan and activate company
        if plan_code:
            await db.execute(
                update(Company)
                .where(Company.id == company_id)
                .values(
                    subscription_plan=plan_code,
                    is_active=True,  # Activate company
                    updated_at=__import__("datetime").datetime.utcnow()
                )
            )

        # Update other subscriptions for this company to inactive
        # Mark other active subscriptions for this company as inactive
        await db.execute(
            update(Subscription)
            .where(
                Subscription.company_id == company_id,
                Subscription.zoho_subscription_id != subscription_id_from_data,
                Subscription.status.in_(["active", "trial"])
            )
            .values(
                status="inactive",
                subscription_status="inactive",
                updated_at=__import__("datetime").datetime.utcnow()
            )
        )

        await db.commit()
        logger.info(f"✅ Payment validated and company {company_id} activated successfully")

        return SuccessResponse(
            success=True,
            data={
                "subscriptionId": subscription_id_from_data,
                "companyId": company_id,
                "status": "active",
                "planCode": plan_code,
                "planName": plan_name
            },
            message="Payment validated and company activated successfully",
            code=status.HTTP_200_OK
        )

    except Exception as db_error:
        # NOTE: preserved verbatim from the original inline try/except: this
        # catches HTTPException too (e.g. the "Company not found" 404 raised
        # above), converting it into a 500 "Failed to update database: ..."
        # response instead of propagating the 404. Not fixed here — kept
        # as characterized by tests/test_payment_gateway_characterization.py.
        await db.rollback()
        logger.error(f"Database error during payment validation: {db_error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update database: {str(db_error)}"
        )
