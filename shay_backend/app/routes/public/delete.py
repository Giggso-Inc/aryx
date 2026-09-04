"""Soft-delete endpoints (testing helpers): DELETE /companies/{id} and /companies/domain/{domain}."""

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


@router.delete("/companies/{company_id}", response_model=SuccessResponse[Dict[str, Any]])
async def delete_company(
    company_id: str,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[Dict[str, Any]]:
    """Soft delete a company by setting it to inactive (for testing purposes)"""
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

        if not company.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Company is already inactive"
            )

        print(f"🔄 Soft deleting company: {company.name} ({company_id})")

        # Soft delete associated users (set to inactive)
        user_result = await db.execute(
            select(User).where(User.company_id == company_id)
        )
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

        # Commit all soft deletions
        await db.commit()

        print(f"✅ Company {company.name} soft deleted successfully (set to inactive)")

        return SuccessResponse(
            success=True,
            data={
                "message": f"Company '{company.name}' soft deleted successfully (set to inactive)",
                "deletedCompanyId": company_id,
                "deactivatedUsersCount": len(users),
                "deactivatedSubscriptionsCount": len(subscriptions),
                "companyStatus": "inactive"
            },
            message="Company soft deleted successfully (set to inactive)",
            code=status.HTTP_200_OK
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        print(f"❌ Error soft deleting company: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to soft delete company: {str(e)}"
        )


@router.delete("/companies/domain/{domain}", response_model=SuccessResponse[Dict[str, Any]])
async def delete_company_by_domain(
    domain: str,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[Dict[str, Any]]:
    """Soft delete a company by domain by setting it to inactive (for testing purposes)"""
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

        if not company.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Company with domain '{domain}' is already inactive"
            )

        company_id = str(company.id)
        print(f"🔄 Soft deleting company by domain: {company.name} ({domain})")

        # Soft delete associated users (set to inactive)
        user_result = await db.execute(
            select(User).where(User.company_id == company_id)
        )
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

        # Commit all soft deletions
        await db.commit()

        print(f"✅ Company {company.name} (domain: {domain}) soft deleted successfully (set to inactive)")

        return SuccessResponse(
            success=True,
            data={
                "message": f"Company '{company.name}' with domain '{domain}' soft deleted successfully (set to inactive)",
                "deletedCompanyId": company_id,
                "deletedDomain": domain,
                "deactivatedUsersCount": len(users),
                "deactivatedSubscriptionsCount": len(subscriptions),
                "companyStatus": "inactive"
            },
            message="Company soft deleted successfully (set to inactive)",
            code=status.HTTP_200_OK
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        print(f"❌ Error soft deleting company by domain: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to soft delete company by domain: {str(e)}"
        )
