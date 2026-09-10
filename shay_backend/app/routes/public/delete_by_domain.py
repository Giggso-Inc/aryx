"""DELETE /companies/domain/{domain} (testing helper).

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

        users, subscriptions = await soft_delete_company_records(db, company)

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
