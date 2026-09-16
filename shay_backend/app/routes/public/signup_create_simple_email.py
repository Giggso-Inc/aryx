"""
Verification-email + response-building tail of the fresh-company-creation
path for POST /companies (create_company_simple). Split out of
signup_create_simple.py for the 150-line-per-file target — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2 follow-up.

NOTE: tests/test_public_characterization.py patches
`email_verification_service.generate_verification_token` /
`.send_verification_email` via this module's path (they used to live on
`app.routes.public.signup`, updated when this code moved here).
"""

from typing import Any
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.core.auth import create_access_token
from app.models.user import User
from app.models.company import Company
from app.schemas.company import CompanyCreationResponse
from app.schemas.common import SuccessResponse
from app.services.email_verification_service import email_verification_service


async def _send_verification_and_build_response(
    db: AsyncSession, company: Company, user: User, company_data: Any
) -> SuccessResponse[CompanyCreationResponse]:
    """Send the initial signup verification email (best-effort) and build the final signup response."""
    try:
        print(f"📧 Generating verification token for {company_data.contactEmail}...")
        verification_token = await email_verification_service.generate_verification_token(
            email=company_data.contactEmail,
            company_id=company.id,
            user_id=user.id,
            token_type="company_signup",
            db=db
        )
        await db.commit()

        # [DEBUG] Log platform from request so we can verify platformName/platform_name and Zaptag intro
        print(f"📧 [public/companies] Verification email: to={company_data.contactEmail}, company_data.platform_name={company_data.platform_name!r}, company_data.platform_url={company_data.platform_url!r}")
        print(f"📧 Sending verification email to {company_data.contactEmail}...")
        email_sent = await email_verification_service.send_verification_email(
            email=company_data.contactEmail,
            token=verification_token.token,
            company_name=company.name,
            user_name=company_data.userName or company_data.contactEmail.split('@')[0],
            platform_url=company_data.platform_url,
            platform_name=company_data.platform_name,
            db=db,
        )

        if email_sent:
            print(f"✅ Email verification email sent successfully to {company_data.contactEmail}")
        else:
            print(f"⚠️ Failed to send verification email to {company_data.contactEmail}")
        # Persist ShortenedUrl row so redirect/resolve link works when user clicks (same as password-reset flow)
        await db.commit()
    except Exception as email_error:
        # Log email error but don't fail the company creation
        print(f"⚠️ Email verification error (non-critical): {email_error}")
        import traceback
        print(f"📋 Email error traceback: {traceback.format_exc()}")

    return await _build_signup_response(company, user)


async def _build_signup_response(
    company: Company, user: User
) -> SuccessResponse[CompanyCreationResponse]:
    """Build the /companies signup success response (shared by the emailed and auto-verified paths)."""
    # Zoho customer creation and the welcome email are disabled while
    # subscription creation is disabled for this flow (see module docstring
    # of signup_create_simple.py).
    zoho_customer_id = None

    # Generate API token (JWT)
    access_token = create_access_token(
        data={"sub": str(user.id), "company_id": str(company.id), "role": "admin"}
    )

    # Create token ID for tracking
    token_id = str(uuid.uuid4())

    # Return response in Node.js format
    return SuccessResponse(
        success=True,
        data=CompanyCreationResponse(
            customerId=str(company.id),
            companyName=company.name,
            token=access_token,
            tokenId=token_id,
            zohoCustomerId=zoho_customer_id,  # Now includes Zoho customer ID
            planId=None,  # Set to null since subscription creation is disabled
            planName=None,  # Set to null since subscription creation is disabled
            isDefaultPlan=None  # Set to null since subscription creation is disabled
        ),
        message="Company created and onboarded successfully!",
        code=status.HTTP_200_OK
    )
