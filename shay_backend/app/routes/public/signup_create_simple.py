"""
Fresh-company-creation path for POST /companies (create_company_simple) — hit
when no reactivatable company and no existing/deactivated user was found.
Extracted from signup.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2 follow-up.

Subscription creation and Zoho customer provisioning are intentionally
disabled for this flow in the current production code (the original
subscription-creation block is commented out in git history) — the response
always reports planId/planName/isDefaultPlan/zohoCustomerId as null. That
behavior is preserved here unchanged; see signup_create_simple_email.py for
the verification-email + response-building continuation of this flow.
"""

from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import uuid

from app.core.auth import generate_company_id, get_password_hash
from app.core.config import settings
from app.models.user import User
from app.models.company import Company
from app.schemas.company import CompanyCreationResponse
from app.schemas.common import SuccessResponse
from app.routes.public.signup_helpers import _create_placeholder_gpt_vault_for_company
from app.routes.public.signup_create_simple_email import _send_verification_and_build_response


def _build_new_simple_company(company_data: Any) -> Company:
    """Build the (inactive, pending-verification) Company row for a fresh /companies signup."""
    company_settings = {}
    if company_data.contactEmail:
        company_settings["emailId"] = company_data.contactEmail

    return Company(
        id=generate_company_id(),
        name=company_data.name,
        domain=company_data.domain,
        description=f"Industry: {company_data.industry}" if company_data.industry else None,
        settings=company_settings if len(company_settings) > 0 else None,  # Store emailId in settings
        subscription_plan="free",  # Default to free plan
        max_users="10",
        max_workspaces="5",
        max_storage_gb="1",
        ai_enabled=True,
        ai_provider="openai",
        is_active=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )


async def _create_new_simple_company_with_user(
    db: AsyncSession, company_data: Any, password_to_use: str
) -> SuccessResponse[CompanyCreationResponse]:
    """Create a brand new (pending-verification) company and admin user for the /companies endpoint."""
    company = _build_new_simple_company(company_data)
    db.add(company)
    await db.flush()  # Get the company ID without committing

    # Create placeholder gpt_token in gg_vault for dev/prod only (not marketplace)
    if not settings.IS_MARKETPLACE:
        await _create_placeholder_gpt_vault_for_company(db, company.id)
    else:
        # Marketplace: skip automatic gg_vault; token can be set later via saveTokenDetails
        pass

    # Create admin user (pending email verification)
    user_id = uuid.uuid4()
    hashed_password = get_password_hash(password_to_use)

    user = User(
        id=user_id,
        name=company_data.userName,  # Use the userName from the request
        email_id=company_data.contactEmail,
        password_hash=hashed_password,
        company_id=company.id,
        role="admin",
        is_active=False,
        is_verified=False,
        created_datetime=datetime.utcnow(),
        updated_datetime=datetime.utcnow()
    )

    db.add(user)
    await db.flush()

    # Commit all changes (Company and User only, no Subscription)
    await db.commit()

    return await _send_verification_and_build_response(db, company, user, company_data)
