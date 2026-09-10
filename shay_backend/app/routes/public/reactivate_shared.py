"""
Shared reactivation core used by both reactivate_by_id.py and
reactivate_by_domain.py (testing helpers).

Split from the original reactivate.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4): both endpoints
performed the identical "reactivate users + subscriptions + company" logic
inline, so it is extracted here to avoid duplication across the split files.
"""

from datetime import datetime
from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.subscription import Subscription
from app.models.user import User


async def reactivate_company_records(
    db: AsyncSession, company: Company
) -> Tuple[List[User], List[Subscription]]:
    """
    Reactivate a company's users, subscriptions, and the company itself.

    Returns (users, subscriptions) that were reactivated. Caller is
    responsible for db.commit() (kept in the caller so the two endpoints'
    error-handling/logging wrapper stays intact).
    """
    company_id = str(company.id)

    # Reactivate associated users (set to active)
    user_result = await db.execute(select(User).where(User.company_id == company_id))
    users = user_result.scalars().all()

    for user in users:
        print(f"🔄 Reactivating user: {user.email_id}")
        user.is_active = True
        user.is_verified = False  # Reset verification status on reactivation
        user.updated_datetime = datetime.utcnow()

    # Reactivate associated subscriptions (set to active)
    subscription_result = await db.execute(
        select(Subscription).where(Subscription.company_id == company_id)
    )
    subscriptions = subscription_result.scalars().all()

    for subscription in subscriptions:
        print(f"🔄 Reactivating subscription: {subscription.id}")
        subscription.status = "active"
        subscription.subscription_status = "active"
        subscription.updated_at = datetime.utcnow()

    # Reactivate the company (set to active)
    company.is_active = True
    company.updated_at = datetime.utcnow()

    return users, subscriptions
