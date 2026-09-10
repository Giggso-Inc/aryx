"""DELETE /companies/{company_id} (testing helper).

Split from the original delete.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.company import Company
from app.schemas.common import SuccessResponse

from .delete_shared import soft_delete_company_records

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

        users, subscriptions = await soft_delete_company_records(db, company)

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
