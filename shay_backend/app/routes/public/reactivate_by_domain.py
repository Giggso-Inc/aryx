"""PATCH /companies/domain/{domain}/reactivate (testing helper).

Split from the original reactivate.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.company import Company
from app.schemas.common import SuccessResponse

from .reactivate_shared import reactivate_company_records

router = APIRouter()


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

        users, subscriptions = await reactivate_company_records(db, company)

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
