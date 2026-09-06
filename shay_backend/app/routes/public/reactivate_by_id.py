"""PATCH /companies/{company_id}/reactivate (testing helper).

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

        users, subscriptions = await reactivate_company_records(db, company)

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
