"""
Company signup endpoints: /createCompany and /companies.

create_company and create_company_simple are thin orchestrators over the
sub-step helpers extracted into sibling modules (signup_lookup, signup_helpers,
signup_reactivation*, signup_restoration, signup_create*) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2 follow-up,
which replaced the earlier "kept as one atomic unit" carve-out for this file.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.company import CompanySignupRequest, CompanyCreateSimpleEncrypted, CompanyCreationResponse
from app.schemas.common import SuccessResponse
from app.routes.public.signup_lookup import (
    _check_existing_company_conflict,
    _get_existing_user_by_email,
    _get_existing_user_with_company_by_email,
    _decrypt_password_if_needed,
)
from app.routes.public.signup_reactivation import _reactivate_company_for_create_company
from app.routes.public.signup_reactivation_simple import _reactivate_company_simple
from app.routes.public.signup_restoration import _restore_deactivated_user_and_company
from app.routes.public.signup_create import _create_new_company_with_user
from app.routes.public.signup_create_simple import _create_new_simple_company_with_user

router = APIRouter()


@router.post("/createCompany", response_model=SuccessResponse[dict])
async def create_company(
    signup_data: CompanySignupRequest,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[dict]:
    """
    Creates a new company with admin user and API token.

    This is the main endpoint called when a user submits the company signup form.
    It handles company creation, user creation, API token generation, and initial subscription assignment.
    """
    try:
        company_data = signup_data.company
        user_data = signup_data.user

        # Use order_by and limit to handle potential duplicates (RCA: Multiple rows found error)
        existing_company = await _check_existing_company_conflict(db, company_data.domain)
        existing_user = await _get_existing_user_by_email(db, user_data["email"])

        # Handle existing company reactivation if company is inactive
        if existing_company and not existing_company.is_active:
            return await _reactivate_company_for_create_company(db, existing_company, existing_user, company_data, user_data)

        # Check if user exists and is active (for non-reactivation cases)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email already exists"
            )

        return await _create_new_company_with_user(db, company_data, user_data)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create company: {str(e)}"
        )


@router.post("/companies", response_model=SuccessResponse[CompanyCreationResponse])
async def create_company_simple(
    company_data: CompanyCreateSimpleEncrypted,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[CompanyCreationResponse]:
    """
    Creates a new company with admin user using simplified payload with encrypted password support.

    This endpoint accepts a flat payload structure for easier frontend integration.
    """
    try:
        password_to_use = await _decrypt_password_if_needed(company_data)

        # Use order_by and limit to handle potential duplicates (RCA: Multiple rows found error)
        existing_company = await _check_existing_company_conflict(db, company_data.domain)
        existing_user = await _get_existing_user_with_company_by_email(db, company_data.contactEmail)

        # Handle existing company reactivation if company is inactive
        if existing_company and not existing_company.is_active:
            return await _reactivate_company_simple(db, existing_company, existing_user, company_data, password_to_use)

        # User restoration logic (matching Node.js behavior)
        if existing_user:
            if not existing_user.is_active or not existing_user.company.is_active:
                return await _restore_deactivated_user_and_company(db, existing_user, company_data, password_to_use)
            # User exists and is active
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email already exists"
            )

        return await _create_new_simple_company_with_user(db, company_data, password_to_use)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create company: {str(e)}"
        )
