"""Reactivation endpoints (testing helpers): PATCH /companies/{id}/reactivate and /companies/domain/{domain}/reactivate."""

from typing import Dict, Any
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.core.database import get_db
from app.models.user import User
from app.models.company import Company
from app.models.subscription import Subscription
from app.schemas.common import SuccessResponse

router = APIRouter()


@router.patch("/companies/{company_id}/reactivate", response_model=SuccessResponse[Dict[str, Any]])
async def reactivate_company(
    company_id: str,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[Dict[str, Any]]:
    """Reactivate a soft-deleted company by setting it back to active (for testing purposes)"""
    try:
        # Find the company
        company_result = await db.execute(
            select(Company).where(Company.id == company_id)
        )
        company = company_result.scalar_one_or_none()

        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found"
            )

        if company.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Company is already active"
            )

        print(f"🔄 Reactivating company: {company.name} ({company_id})")

        # Reactivate associated users (set to active)
        user_result = await db.execute(
            select(User).where(User.company_id == company_id)
        )
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

        # Commit all reactivations
        await db.commit()

        print(f"✅ Company {company.name} reactivated successfully")

        return SuccessResponse(
            success=True,
            data={
                "message": f"Company '{company.name}' reactivated successfully",
                "reactivatedCompanyId": company_id,
                "reactivatedUsersCount": len(users),
                "reactivatedSubscriptionsCount": len(subscriptions),
                "companyStatus": "active"
            },
            message="Company reactivated successfully",
            code=status.HTTP_200_OK
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        print(f"❌ Error reactivating company: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reactivate company: {str(e)}"
        )


@router.patch("/companies/domain/{domain}/reactivate", response_model=SuccessResponse[Dict[str, Any]])
async def reactivate_company_by_domain(
    domain: str,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[Dict[str, Any]]:
    """Reactivate a soft-deleted company by domain by setting it back to active (for testing purposes)"""
    try:
        # Find the company by domain
        company_result = await db.execute(
            select(Company).where(Company.domain == domain)
        )
        company = company_result.scalar_one_or_none()

        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Company with domain '{domain}' not found"
            )

        if company.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Company with domain '{domain}' is already active"
            )

        company_id = str(company.id)
        print(f"🔄 Reactivating company by domain: {company.name} ({domain})")

        # Reactivate associated users (set to active)
        user_result = await db.execute(
            select(User).where(User.company_id == company_id)
        )
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

        # Commit all reactivations
        await db.commit()

        print(f"✅ Company {company.name} (domain: {domain}) reactivated successfully")

        return SuccessResponse(
            success=True,
            data={
                "message": f"Company '{company.name}' with domain '{domain}' reactivated successfully",
                "reactivatedCompanyId": company_id,
                "reactivatedDomain": domain,
                "reactivatedUsersCount": len(users),
                "reactivatedSubscriptionsCount": len(subscriptions),
                "companyStatus": "active"
            },
            message="Company reactivated successfully",
            code=status.HTTP_200_OK
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        print(f"❌ Error reactivating company by domain: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reactivate company by domain: {str(e)}"
        )
