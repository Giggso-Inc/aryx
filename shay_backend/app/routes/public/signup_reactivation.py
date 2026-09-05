"""
Inactive-company reactivation branch for POST /createCompany (create_company).
Extracted from signup.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2 follow-up.

NOTE: this function references `password_to_use`, a name that is never
assigned anywhere in create_company's request path (only
create_company_simple decrypts/derives a `password_to_use`). This is a
pre-existing defect carried over unchanged from the original monolithic
signup.py — the branch raises NameError if ever actually executed (existing
inactive company + an existing user already belonging to it). It is not
covered by tests/test_public_characterization.py::TestCreateCompany and is
preserved verbatim rather than silently "fixed" during this restructuring.
"""

from typing import Optional, Any
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import uuid

from app.core.auth import get_password_hash
from app.models.user import User
from app.models.company import Company
from app.schemas.common import SuccessResponse


async def _reactivate_company_for_create_company(
    db: AsyncSession, existing_company: Company, existing_user: Optional[User], company_data: Any, user_data: dict
) -> SuccessResponse[dict]:
    """Reactivate an inactive company for the /createCompany endpoint, reusing or creating its admin user."""
    print(f"🔄 Reactivating inactive company: {existing_company.id}")

    existing_company.is_active = True
    existing_company.updated_at = datetime.utcnow()

    if existing_user:
        if existing_user.company_id != existing_company.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email already exists and belongs to a different company"
            )

        print(f"🔄 Reactivating existing user: {existing_user.id}")
        existing_user.is_active = True
        existing_user.is_verified = False  # Reset verification status on reactivation
        existing_user.updated_datetime = datetime.utcnow()
        existing_user.password_hash = get_password_hash(password_to_use)  # noqa: F821 -- preserved pre-existing bug, see module docstring

        if company_data.userName:
            existing_user.name = company_data.userName

        await db.commit()

        return SuccessResponse(
            success=True,
            data={
                "status": "success",
                "message": "Company reactivated successfully",
                "data": {
                    "customer_id": str(existing_company.id),
                    "company_name": existing_company.name,
                    "api_token": "reactivated_token",  # Would need to generate new token
                    "zoho_customer_id": None,
                    "user": {
                        "id": str(existing_user.id),
                        "email": existing_user.email_id,
                        "role": existing_user.role
                    }
                }
            },
            message="Company reactivated successfully",
            code=status.HTTP_200_OK
        )

    # No existing user, create new admin user for reactivated company
    print(f"🔄 Creating new admin user for reactivated company")
    user_id = uuid.uuid4()
    hashed_password = get_password_hash(user_data["password"])

    user = User(
        id=user_id,
        name=company_data.userName,
        email_id=user_data["email"],
        password_hash=hashed_password,
        company_id=existing_company.id,
        role="admin",
        is_active=True,
        created_datetime=datetime.utcnow(),
        updated_datetime=datetime.utcnow()
    )

    db.add(user)
    await db.commit()

    return SuccessResponse(
        success=True,
        data={
            "status": "success",
            "message": "Company reactivated with new user",
            "data": {
                "customer_id": str(existing_company.id),
                "company_name": existing_company.name,
                "api_token": "new_token_for_reactivated_company",
                "zoho_customer_id": None,
                "user": {
                    "id": str(user.id),
                    "email": user.email_id,
                    "role": user.role
                }
            }
        },
        message="Company reactivated with new user successfully",
        code=status.HTTP_200_OK
    )
