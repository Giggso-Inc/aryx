"""
Shared soft-delete core used by both delete_by_id.py and
delete_by_domain.py (testing helpers).

Split from the original delete.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4): both endpoints
performed the identical "deactivate users + subscriptions + company" logic
inline, so it is extracted here to avoid duplication across the split files.
"""

from datetime import datetime
from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.subscription import Subscription
from app.models.user import User


async def soft_delete_company_records(
    db: AsyncSession, company: Company
) -> Tuple[List[User], List[Subscription]]:
    """
    Deactivate a company's users, subscriptions, and the company itself.

    Returns (users, subscriptions) that were deactivated. Caller is
    responsible for db.commit() (kept in the caller so the two endpoints'
    error-handling/logging wrapper stays intact).
    """
    company_id = str(company.id)

    # Soft delete associated users (set to inactive)
    user_result = await db.execute(select(User).where(User.company_id == company_id))
    users = user_result.scalars().all()

    for user in users:
        print(f"🔄 Deactivating user: {user.email_id}")
        user.is_active = False
        user.updated_datetime = datetime.utcnow()

    # Soft delete associated subscriptions (set to inactive)
    subscription_result = await db.execute(
        select(Subscription).where(Subscription.company_id == company_id)
    )
    subscriptions = subscription_result.scalars().all()

    for subscription in subscriptions:
        print(f"🔄 Deactivating subscription: {subscription.id}")
        subscription.status = "inactive"
        subscription.subscription_status = "inactive"
        subscription.updated_at = datetime.utcnow()

    # Soft delete the company (set to inactive)
    company.is_active = False
    company.updated_at = datetime.utcnow()

    return users, subscriptions
