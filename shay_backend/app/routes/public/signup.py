"""
Company signup endpoints: /createCompany and /companies.

Stated exception to the 150-line target: create_company_simple alone is a
~640-line function implementing several deeply-nested reactivation and
restoration branches (inactive company reactivation, deactivated user
restoration, existing-subscription vs. new-subscription paths) that were
golden-mastered as a single unit in
tests/test_public_characterization.py::TestCreateCompanySimple. Splitting
these branches into separate helper functions risks silently changing
control flow (e.g. which branch commits before which check) without a
matching benefit, so this file is kept together as one unit per the
Raven Style Compliance Plan's "too tightly coupled to split further
safely" carve-out (see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from typing import Optional, Any
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta
from decimal import Decimal
import uuid
import logging

from app.core.database import get_db
from app.core.auth import generate_company_id, create_access_token, get_password_hash
from app.core.encryption_utils import decrypt
from app.core.config import settings
from app.models.user import User
from app.models.company import Company
from app.models.subscription_plan import SubscriptionPlan
from app.models.subscription import Subscription
from app.schemas.company import (
    CompanySignupRequest,
    CompanyCreateSimple,
    CompanyCreateSimpleEncrypted,
    CompanyCreationResponse,
)
from app.schemas.common import SuccessResponse
from app.models.giggso_vault import GiggsoVault
from app.services.vault_service import vault_service
from app.services.email_verification_service import email_verification_service
from app.routes.token_details import _normalize_token_type_for_vault  # ML vault shape normalization

logger = logging.getLogger(__name__)

router = APIRouter()


async def _create_placeholder_gpt_vault_for_company(db: AsyncSession, company_id: Any) -> None:
    """
    Create gg_vault row and vault entry for gpt_token when a company is created (dev/prod).
    Uses token defaults from config (GPT_* env vars). Same vault shape and flow as saveTokenDetails API.
    User can update later via api/v1/public/saveTokenDetails.
    """
    try:
        company_uuid = company_id if isinstance(company_id, uuid.UUID) else uuid.UUID(str(company_id))
        company_id_str = str(company_uuid)
        # Build vault payload identical to saveTokenDetails: same keys, order, and conditionals
        _token_type = settings.GPT_TOKEN_TYPE or ""
        vault_data = {
            "tokenType": _normalize_token_type_for_vault(_token_type),
            "tokenName": settings.GPT_TOKEN_NAME or "",
            "openaiToken": settings.GPT_API_KEY or "",
            "embeddingsDeploymentName": settings.GPT_EMBEDDING_MODEL or "",
            "model": settings.GPT_MODEL or "",
            "apiVersion": settings.GPT_DEPLOYMENT_VERSION if settings.GPT_DEPLOYMENT_VERSION else "",
            "companyId": company_id_str,
        }
        if settings.GPT_DEPLOYMENT_NAME:
            vault_data["deploymentName"] = settings.GPT_DEPLOYMENT_NAME
        if settings.GPT_ENDPOINT:
            vault_data["endpoint"] = settings.GPT_ENDPOINT
        vault_unique_id = vault_service.generate_vault_unique_id(
            company_id_str, app_key=_token_type or "token"
        )
        saved_vault_id = await vault_service.save_to_vault(vault_data, vault_unique_id)
        if not saved_vault_id:
            logger.warning("create_company: vault save failed for company_id=%s; gg_vault not created", company_id_str)
            return
        # Same gg_vault record creation as saveTokenDetails
        base_label = f"tk_{vault_unique_id.replace('/', '_')[:20]}"
        vault_label = (base_label + "_ok")[:50]
        vault_record = GiggsoVault(
            vault_unique_id=vault_unique_id,
            user_id=None,
            vault_label=vault_label,
            vault_type="gpt_token",
            company_id=company_uuid,
            created_datetime=datetime.utcnow(),
        )
        db.add(vault_record)
        await db.flush()
    except Exception as e:
        logger.warning("create_company: failed to create placeholder gpt vault for company_id=%s: %s", company_id, e)


async def _create_subscription_for_company(company_id: str, db: AsyncSession) -> Optional[Subscription]:
    """Create a new subscription for an existing company"""
    try:
        # Find a default free plan
        default_plan_result = await db.execute(
            select(SubscriptionPlan).where(
                SubscriptionPlan.is_active == True,
                SubscriptionPlan.monthly_price == Decimal('0.00')
            ).limit(1)
        )
        default_plan = default_plan_result.scalar_one_or_none()

        if not default_plan:
            print("⚠️ No free plan available for subscription creation")
            return None

        # Create subscription
        subscription_id = uuid.uuid4()
        subscription = Subscription(
            id=subscription_id,
            company_id=company_id,
            plan_id=default_plan.id,
            status="active",
            subscription_status="active",
            amount=Decimal('0.00'),
            currency_code="USD",
            billing_cycle="monthly",
            auto_collect=True,
            current_period_start=datetime.utcnow(),
            current_period_end=datetime.utcnow() + timedelta(days=30),
            next_billing_date=datetime.utcnow() + timedelta(days=30),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.add(subscription)
        await db.commit()
        print(f"✅ Subscription created for company {company_id}")
        return subscription

    except Exception as e:
        print(f"❌ Failed to create subscription: {e}")
        await db.rollback()
        return None


async def _create_zoho_customer(company: Company, company_data: CompanyCreateSimple, plan: SubscriptionPlan, db: AsyncSession, platform_name: Optional[str] = None) -> Optional[str]:
    """Create Zoho customer and subscription (non-blocking)"""
    try:
        from app.services.zoho_service import get_zoho_service

        # Get appropriate Zoho service instance based on platform_name
        zoho_service_instance = get_zoho_service(platform_name)

        print(f"🔄 Creating Zoho customer for company: {company.name}")

        # Prepare customer data for Zoho
        customer_data = {
            'name': company.name,
            'email': company_data.contactEmail,
            'companyName': company.name,
            'website': company.domain,
            'currency': 'USD'
        }

        # Create customer in Zoho
        zoho_customer = await zoho_service_instance.create_customer(customer_data)
        zoho_customer_id = zoho_customer['customer_id']

        # Prepare subscription data for Zoho
        subscription_data = {
            'plan': {
                'planCode': plan.plan_code or 'ShayFree30',
                'description': plan.description or 'Basic Monthly Plan'
            },
            'customer': {
                'displayName': company.name,
                'email': company_data.contactEmail,
                'companyName': company.name,
                'website': company.domain,
                'currencyCode': 'USD'
            },
            'planCycles': plan.plan_cycles or -1,
            'autoCollect': True
        }

        # Create subscription in Zoho
        zoho_subscription = await zoho_service_instance.create_subscription_with_customer(subscription_data)

        # Update subscription with Zoho customer ID
        subscription_result = await db.execute(
            select(Subscription).where(Subscription.company_id == company.id)
        )
        subscription = subscription_result.scalar_one_or_none()

        if subscription:
            subscription.zoho_customer_id = zoho_customer_id
            subscription.zoho_subscription_id = zoho_subscription['subscription']['subscription_id']
            await db.commit()
            print(f"✅ Zoho customer ID stored: {zoho_customer_id}")
            print(f"✅ Zoho subscription ID stored: {zoho_subscription['subscription']['subscription_id']}")

        return zoho_customer_id

    except Exception as e:
        print(f"⚠️ Zoho customer creation failed: {e}")
        # Enhanced error handling matching Node.js behavior
        error_message = "Company created successfully, but Zoho customer creation failed. Please contact support."

        # Handle specific error types if available
        if hasattr(e, 'response') and e.response:
            error_data = e.response.get('data', {})
            error_code = error_data.get('code')

            if error_code == 100502:
                error_message = "Company created successfully, but plan code already exists in Zoho. Please contact support."
            elif error_code == 3013:
                error_message = "Company created successfully, but invalid customer name for subscription. Please contact support."
            elif error_code == 3014:
                error_message = "Company created successfully, but invalid email address for subscription. Please contact support."
            elif error_code == 3015:
                error_message = "Company created successfully, but invalid company name for subscription. Please contact support."
            elif error_data.get('message'):
                error_message = f"Company created successfully, but Zoho API error: {error_data['message']}"
            elif str(e):
                error_message = f"Company created successfully, but subscription error: {str(e)}"

        print(f"⚠️ {error_message}")
        return None


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

        # Check if company with same domain already exists
        # Use order_by and limit to handle potential duplicates (RCA: Multiple rows found error)
        if company_data.domain:
            existing_company_result = await db.execute(
                select(Company)
                .where(Company.domain == company_data.domain)
                .order_by(Company.created_at.desc())
                .limit(1)
            )
            existing_company = existing_company_result.scalar_one_or_none()

            if existing_company:
                # If company exists but is inactive, we can reactivate it
                if not existing_company.is_active:
                    print(f"🔄 Found inactive company with domain '{company_data.domain}', will reactivate")
                    # Continue with the flow to handle reactivation
                else:
                    # Company exists and is active
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Company with this domain already exists"
                    )

        # Check if user with same email already exists
        existing_user = await db.execute(
            select(User).where(User.email_id == user_data["email"])
        )
        existing_user = existing_user.scalar_one_or_none()

        # Handle existing company reactivation if company is inactive
        if existing_company and not existing_company.is_active:
            print(f"🔄 Reactivating inactive company: {existing_company.id}")

            # Reactivate the company
            existing_company.is_active = True
            existing_company.updated_at = datetime.utcnow()

            # Handle existing user if found
            if existing_user:
                if existing_user.company_id == existing_company.id:
                    # User belongs to this company, reactivate them
                    print(f"🔄 Reactivating existing user: {existing_user.id}")
                    existing_user.is_active = True
                    existing_user.is_verified = False  # Reset verification status on reactivation
                    existing_user.updated_datetime = datetime.utcnow()
                    existing_user.password_hash = get_password_hash(password_to_use)

                    # Update user name if provided
                    if company_data.userName:
                        existing_user.name = company_data.userName

                    await db.commit()

                    # Return success response for reactivated company
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
                else:
                    # User belongs to different company
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="User with this email already exists and belongs to a different company"
                    )
            else:
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

        # Check if user exists and is active (for non-reactivation cases)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email already exists"
            )

        # Create company
        company_id = generate_company_id()
        company = Company(
            id=company_id,
            name=company_data.name,
            domain=company_data.domain,
            description=company_data.description,
            subscription_plan=company_data.subscription_plan,
            max_users=company_data.max_users,
            max_workspaces=company_data.max_workspaces,
            max_storage_gb=company_data.max_storage_gb,
            ai_enabled=company_data.ai_enabled,
            ai_provider=company_data.ai_provider,
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.add(company)
        await db.flush()  # Get the company ID without committing

        # Create placeholder gpt_token in gg_vault for dev/prod only (not marketplace)
        if not settings.IS_MARKETPLACE:
            await _create_placeholder_gpt_vault_for_company(db, company_id)
        else:
            # Marketplace: skip automatic gg_vault; token can be set later via saveTokenDetails
            pass

        # Create admin user
        user_id = uuid.uuid4()
        hashed_password = get_password_hash(user_data["password"])

        user = User(
            id=user_id,
            name=company_data.userName,  # Use the userName from the company data
            email_id=user_data["email"],
            password_hash=hashed_password,
            company_id=company_id,
            role="admin",
            is_active=True,
            created_datetime=datetime.utcnow(),
            updated_datetime=datetime.utcnow()
        )

        db.add(user)
        await db.flush()

        # Find a default free plan for initial subscription
        default_plan_result = await db.execute(
            select(SubscriptionPlan).where(
                SubscriptionPlan.is_active == True,
                SubscriptionPlan.monthly_price == Decimal('0.00')
            ).limit(1)
        )
        default_plan = default_plan_result.scalar_one_or_none()

        if not default_plan:
            # If no free plan exists, we'll need to handle this case
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No free subscription plan available for initial setup"
            )

        # Create initial subscription (free plan)
        subscription_id = uuid.uuid4()
        subscription = Subscription(
            id=subscription_id,
            company_id=company_id,
            plan_id=default_plan.id,  # Use the found free plan
            status="active",
            subscription_status="active",
            amount=Decimal('0.00'),
            currency_code="USD",
            billing_cycle="monthly",
            auto_collect=True,
            current_period_start=datetime.utcnow(),
            current_period_end=datetime.utcnow() + timedelta(days=30),
            next_billing_date=datetime.utcnow() + timedelta(days=30),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.add(subscription)

        # Commit all changes
        await db.commit()

        # Generate API token for the user
        access_token = create_access_token(
            data={"sub": str(user_id), "company_id": str(company_id), "role": "admin"}
        )

        # Return response similar to Node.js API
        return SuccessResponse(
            success=True,
            data={
                "status": "success",
                "message": "Company created successfully",
                "data": {
                    "customer_id": str(company_id),
                    "company_name": company.name,
                    "api_token": access_token,
                    "zoho_customer_id": None,  # Will be set when integrated with Zoho
                    "user": {
                        "id": str(user_id),
                        "email": user.email_id,
                        "role": user.role
                    }
                }
            },
            message="Company created successfully",
            code=status.HTTP_200_OK
        )

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
        # Handle password decryption if encrypted
        password_to_use = company_data.password

        if company_data.encrypted:
            try:
                # Decrypt the password if it's encrypted
                password_to_use = decrypt(company_data.password)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid encrypted password format"
                )
        # Check if company with same domain already exists
        # Use order_by and limit to handle potential duplicates (RCA: Multiple rows found error)
        if company_data.domain:
            existing_company_result = await db.execute(
                select(Company)
                .where(Company.domain == company_data.domain)
                .order_by(Company.created_at.desc())
                .limit(1)
            )
            existing_company = existing_company_result.scalar_one_or_none()

            if existing_company:
                # If company exists but is inactive, we can reactivate it
                if not existing_company.is_active:
                    print(f"🔄 Found inactive company with domain '{company_data.domain}', will reactivate")
                    # Continue with the flow to handle reactivation
                else:
                    # Company exists and is active
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Company with this domain already exists"
                    )

        # Check if user with same email already exists
        existing_user = await db.execute(
            select(User).where(User.email_id == company_data.contactEmail).options(selectinload(User.company))
        )
        existing_user = existing_user.scalar_one_or_none()

        # Handle existing company reactivation if company is inactive
        if existing_company and not existing_company.is_active:
            print(f"🔄 Reactivating inactive company: {existing_company.id}")

            # Reactivate the company and update settings with emailId
            existing_company.is_active = True
            existing_company.updated_at = datetime.utcnow()
            if company_data.contactEmail:
                if not existing_company.settings:
                    existing_company.settings = {}
                existing_company.settings["emailId"] = company_data.contactEmail

            # Handle existing user if found
            if existing_user:
                if existing_user.company_id == existing_company.id:
                    # User belongs to this company, reactivate them
                    print(f"🔄 Reactivating existing user: {existing_user.id}")
                    existing_user.is_active = True
                    existing_user.is_verified = False  # Reset verification status on reactivation
                    existing_user.updated_datetime = datetime.utcnow()
                    existing_user.password_hash = get_password_hash(password_to_use)

                    # Update user name if provided
                    if company_data.userName:
                        existing_user.name = company_data.userName

                    await db.commit()

                    # Send verification email on reactivation (same as new company flow)
                    try:
                        print(f"📧 [public/companies] Reactivated user: sending verification email to {existing_user.email_id}")
                        verification_token = await email_verification_service.generate_verification_token(
                            email=existing_user.email_id,
                            company_id=existing_user.company_id,
                            user_id=existing_user.id,
                            token_type="company_signup",
                            db=db
                        )
                        await db.commit()
                        company_name_for_email = (await db.execute(
                            select(Company.name).where(Company.id == existing_user.company_id)
                        )).scalar_one_or_none() or "Restored Company"
                        email_sent = await email_verification_service.send_verification_email(
                            email=existing_user.email_id,
                            token=verification_token.token,
                            company_name=company_name_for_email,
                            user_name=company_data.userName or (existing_user.name or existing_user.email_id.split("@")[0]),
                            platform_url=getattr(company_data, "platform_url", None),
                            platform_name=getattr(company_data, "platform_name", None),
                            db=db,
                        )
                        if email_sent:
                            print(f"✅ Verification email sent to {existing_user.email_id} (reactivation)")
                        else:
                            print(f"⚠️ Failed to send verification email to {existing_user.email_id} (reactivation)")
                    except Exception as email_error:
                        print(f"⚠️ Verification email error on reactivation (non-critical): {email_error}")

                    # Get existing subscription or create new one
                    # Use order_by and limit to handle multiple subscriptions (RCA: Multiple rows found error)
                    existing_subscription_result = await db.execute(
                        select(Subscription)
                        .where(Subscription.company_id == existing_user.company_id)
                        .order_by(Subscription.created_at.desc())
                        .limit(1)
                    )
                    existing_subscription = existing_subscription_result.scalar_one_or_none()

                    # Get company name for response
                    company_result = await db.execute(
                        select(Company.name).where(Company.id == existing_user.company_id)
                    )
                    company_name = company_result.scalar_one_or_none()

                    if existing_subscription:
                        # Reactivate the subscription if it's inactive
                        if existing_subscription.status == "inactive" or existing_subscription.subscription_status == "inactive":
                            print(f"🔄 Reactivating subscription: {existing_subscription.id}")
                            existing_subscription.status = "active"
                            existing_subscription.subscription_status = "active"
                            existing_subscription.updated_at = datetime.utcnow()
                            await db.commit()

                        # Get plan details for better response
                        plan_result = await db.execute(
                            select(SubscriptionPlan.name, SubscriptionPlan.monthly_price)
                            .where(SubscriptionPlan.id == existing_subscription.plan_id)
                        )
                        plan = plan_result.fetchone()
                        plan_name = plan[0] if plan else "Unknown Plan"
                        is_default_plan = plan[1] == Decimal('0.00') if plan else False

                        # Generate real JWT token for reactivated user
                        access_token = create_access_token(
                            data={"sub": str(existing_user.id), "company_id": str(existing_user.company_id), "role": existing_user.role}
                        )

                        # Create real token ID
                        token_id = str(uuid.uuid4())

                        # Return existing company data with real token
                        return SuccessResponse(
                            success=True,
                            data=CompanyCreationResponse(
                                customerId=str(existing_user.company_id),
                                companyName=company_name or "Restored Company",
                                token=access_token,  # Real JWT token
                                tokenId=token_id,   # Real token ID
                                zohoCustomerId=existing_subscription.zoho_customer_id,  # zoho_customer_id
                                planId=str(existing_subscription.plan_id),  # plan_id
                                planName=plan_name,  # Actual plan name
                                isDefaultPlan=is_default_plan  # Dynamic default plan check
                            ),
                            message="Company and user reactivated successfully!",
                            code=status.HTTP_200_OK
                        )
                    else:
                        # Create new subscription for reactivated company
                        await _create_subscription_for_company(existing_user.company_id, db)

                        return SuccessResponse(
                            success=True,
                            data=CompanyCreationResponse(
                                customerId=str(existing_user.company_id),
                                companyName=company_name or "Restored Company",
                                token="new_token_for_reactivated_company",
                                tokenId="new_token_id",
                                zohoCustomerId=None,
                                planId="free_plan_id",
                                planName="Free Plan",
                                isDefaultPlan=True
                            ),
                            message="Company and user reactivated successfully!",
                            code=status.HTTP_200_OK
                        )
                else:
                    # User belongs to different company
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="User with this email already exists and belongs to a different company"
                    )
            else:
                # No existing user, create new admin user for reactivated company
                print(f"🔄 Creating new admin user for reactivated company")
                user_id = uuid.uuid4()
                hashed_password = get_password_hash(password_to_use)

                user = User(
                    id=user_id,
                    name=company_data.userName,
                    email_id=company_data.contactEmail,
                    password_hash=hashed_password,
                    company_id=existing_company.id,
                    role="admin",
                    is_active=True,
                    created_datetime=datetime.utcnow(),
                    updated_datetime=datetime.utcnow()
                )

                db.add(user)
                await db.commit()

                # Create subscription for reactivated company
                await _create_subscription_for_company(existing_company.id, db)

                # Get plan details for the new subscription
                plan_result = await db.execute(
                    select(SubscriptionPlan.name, SubscriptionPlan.monthly_price)
                    .where(SubscriptionPlan.monthly_price == Decimal('0.00'))
                    .limit(1)
                )
                plan = plan_result.fetchone()
                plan_name = plan[0] if plan else "Free Plan"
                plan_id = str(plan[1]) if plan else "free_plan_id"

                # Generate real JWT token for new user
                access_token = create_access_token(
                    data={"sub": str(user.id), "company_id": str(existing_company.id), "role": user.role}
                )

                # Create real token ID
                token_id = str(uuid.uuid4())

                return SuccessResponse(
                    success=True,
                    data=CompanyCreationResponse(
                        customerId=str(existing_company.id),
                        companyName=existing_company.name,
                        token=access_token,  # Real JWT token
                        tokenId=token_id,   # Real token ID
                        zohoCustomerId=None,
                        planId=plan_id,     # Real plan ID
                        planName=plan_name, # Real plan name
                        isDefaultPlan=True  # Free plan is default
                    ),
                    message="Company reactivated with new user successfully!",
                    code=status.HTTP_200_OK
                )

        # NEW: User restoration logic (matching Node.js behavior)
        if existing_user:
            # Check if user/company is deactivated
            if not existing_user.is_active or not existing_user.company.is_active:
                print(f"🔄 Restoring deactivated user/organization: {existing_user.id}")

                # Restore company if deactivated
                if not existing_user.company.is_active:
                    existing_user.company.is_active = True
                    existing_user.company.updated_at = datetime.utcnow()
                    print("✅ Organization restored successfully")

                # Restore user if deactivated
                if not existing_user.is_active:
                    existing_user.is_active = True
                    existing_user.is_verified = False  # Reset verification status on restoration
                    existing_user.updated_datetime = datetime.utcnow()
                    print("✅ User restored successfully")

                # Update password for restored user
                hashed_password = get_password_hash(password_to_use)
                existing_user.password_hash = hashed_password

                # Update user name if provided
                if company_data.userName:
                    existing_user.name = company_data.userName

                await db.commit()

                # Send verification email on re-onboarding (same as new company flow)
                try:
                    print(f"📧 [public/companies] Restored user: sending verification email to {existing_user.email_id}")
                    verification_token = await email_verification_service.generate_verification_token(
                        email=existing_user.email_id,
                        company_id=existing_user.company_id,
                        user_id=existing_user.id,
                        token_type="company_signup",
                        db=db
                    )
                    await db.commit()
                    company_name_for_email = (await db.execute(
                        select(Company.name).where(Company.id == existing_user.company_id)
                    )).scalar_one_or_none() or "Restored Company"
                    email_sent = await email_verification_service.send_verification_email(
                        email=existing_user.email_id,
                        token=verification_token.token,
                        company_name=company_name_for_email,
                        user_name=company_data.userName or (existing_user.name or existing_user.email_id.split("@")[0]),
                        platform_url=getattr(company_data, "platform_url", None),
                        platform_name=getattr(company_data, "platform_name", None),
                        db=db,
                    )
                    if email_sent:
                        print(f"✅ Verification email sent to {existing_user.email_id} (re-onboarding)")
                    else:
                        print(f"⚠️ Failed to send verification email to {existing_user.email_id} (re-onboarding)")
                except Exception as email_error:
                    print(f"⚠️ Verification email error on re-onboarding (non-critical): {email_error}")

                # Get existing subscription or create new one
                # Use order_by and limit to handle multiple subscriptions (RCA: Multiple rows found error)
                existing_subscription_result = await db.execute(
                    select(Subscription)
                    .where(Subscription.company_id == existing_user.company_id)
                    .order_by(Subscription.created_at.desc())
                    .limit(1)
                )
                existing_subscription = existing_subscription_result.scalar_one_or_none()

                # Get company name for response
                company_result = await db.execute(
                    select(Company.name).where(Company.id == existing_user.company_id)
                )
                company_name = company_result.scalar_one_or_none()

                if existing_subscription:
                    # Reactivate the subscription if it's inactive
                    if existing_subscription.status == "inactive" or existing_subscription.subscription_status == "inactive":
                        print(f"🔄 Reactivating subscription: {existing_subscription.id}")
                        existing_subscription.status = "active"
                        existing_subscription.subscription_status = "active"
                        existing_subscription.updated_at = datetime.utcnow()
                        await db.commit()

                    # Get plan details for better response
                    plan_result = await db.execute(
                        select(SubscriptionPlan.name, SubscriptionPlan.monthly_price)
                        .where(SubscriptionPlan.id == existing_subscription.plan_id)
                    )
                    plan = plan_result.fetchone()
                    plan_name = plan[0] if plan else "Unknown Plan"
                    is_default_plan = plan[1] == Decimal('0.00') if plan else False

                    # Generate real JWT token for restored user
                    access_token = create_access_token(
                        data={"sub": str(existing_user.id), "company_id": str(existing_user.company_id), "role": existing_user.role}
                    )

                    # Create real token ID
                    token_id = str(uuid.uuid4())

                    # Return existing company data with real token
                    return SuccessResponse(
                        success=True,
                        data=CompanyCreationResponse(
                            customerId=str(existing_user.company_id),
                            companyName=company_name or "Restored Company",
                            token=access_token,  # Real JWT token
                            tokenId=token_id,   # Real token ID
                            zohoCustomerId=existing_subscription.zoho_customer_id,  # zoho_customer_id
                            planId=str(existing_subscription.plan_id),  # plan_id
                            planName=plan_name,  # Actual plan name
                            isDefaultPlan=is_default_plan  # Dynamic default plan check
                        ),
                        message="Company and user restored successfully!",
                        code=status.HTTP_200_OK
                    )
                else:
                    # Create new subscription for restored company
                    await _create_subscription_for_company(existing_user.company_id, db)

                    # Get plan details for the new subscription
                    plan_result = await db.execute(
                        select(SubscriptionPlan.name, SubscriptionPlan.monthly_price)
                        .where(SubscriptionPlan.monthly_price == Decimal('0.00'))
                        .limit(1)
                    )
                    plan = plan_result.fetchone()
                    plan_name = plan[0] if plan else "Free Plan"
                    plan_id = str(plan[1]) if plan else "free_plan_id"

                    # Generate real JWT token for restored user
                    access_token = create_access_token(
                        data={"sub": str(existing_user.id), "company_id": str(existing_user.company_id), "role": existing_user.role}
                    )

                    # Create real token ID
                    token_id = str(uuid.uuid4())

                    return SuccessResponse(
                        success=True,
                        data=CompanyCreationResponse(
                            customerId=str(existing_user.company_id),
                            companyName=company_name or "Restored Company",
                            token=access_token,  # Real JWT token
                            tokenId=token_id,   # Real token ID
                            zohoCustomerId=None,
                            planId=plan_id,     # Real plan ID
                            planName=plan_name, # Real plan name
                            isDefaultPlan=True  # Free plan is default
                        ),
                        message="Company and user restored successfully!",
                        code=status.HTTP_200_OK
                    )
            else:
                # User exists and is active
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="User with this email already exists"
                )

        # Create company
        company_id = generate_company_id()

        # Build settings JSONB with emailId
        company_settings = {}
        if company_data.contactEmail:
            company_settings["emailId"] = company_data.contactEmail

        company = Company(
            id=company_id,
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

        db.add(company)
        await db.flush()  # Get the company ID without committing

        # Create placeholder gpt_token in gg_vault for dev/prod only (not marketplace)
        if not settings.IS_MARKETPLACE:
            await _create_placeholder_gpt_vault_for_company(db, company_id)
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
            company_id=company_id,
            role="admin",
            is_active=False,
            is_verified=False,
            created_datetime=datetime.utcnow(),
            updated_datetime=datetime.utcnow()
        )

        db.add(user)
        await db.flush()

        # COMMENTED OUT: Plan lookup - no longer needed since subscription creation is disabled
        # # Find a default free plan for response (subscription creation commented out)
        # default_plan_result = await db.execute(
        #     select(SubscriptionPlan).where(
        #         SubscriptionPlan.is_active == True,
        #         SubscriptionPlan.monthly_price == Decimal('0.00')
        #     ).limit(1)
        # )
        # default_plan = default_plan_result.scalar_one_or_none()
        #
        # if not default_plan:
        #     # If no free plan exists, we'll need to handle this case
        #     raise HTTPException(
        #         status_code=status.HTTP_400_BAD_REQUEST,
        #         detail="No free subscription plan available for initial setup"
        #     )
        default_plan = None  # Set to None since we're not creating subscriptions

        # COMMENTED OUT: Subscription creation flow - no subscription record will be created
        # # Create initial subscription (free plan)
        # subscription_id = uuid.uuid4()
        # subscription = Subscription(
        #     id=subscription_id,
        #     company_id=company_id,
        #     plan_id=default_plan.id,  # Use the found free plan
        #     status="active",
        #     subscription_status="active",
        #     amount=Decimal('0.00'),
        #     currency_code="USD",
        #     billing_cycle="monthly",
        #     auto_collect=True,
        #     current_period_start=datetime.utcnow(),
        #     current_period_end=datetime.utcnow() + timedelta(days=30),
        #     next_billing_date=datetime.utcnow() + timedelta(days=30),
        #     created_at=datetime.utcnow(),
        #     updated_at=datetime.utcnow()
        # )
        #
        # db.add(subscription)

        # Commit all changes (Company and User only, no Subscription)
        await db.commit()

        # Generate and send email verification email
        try:
            print(f"📧 Generating verification token for {company_data.contactEmail}...")
            verification_token = await email_verification_service.generate_verification_token(
                email=company_data.contactEmail,
                company_id=company_id,
                user_id=user_id,
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

        # NEW: Create Zoho customer (non-blocking)
        # NOTE: Zoho integration disabled since default_plan is None (subscription creation is disabled)
        zoho_customer_id = None
        # try:
        #     zoho_customer_id = await _create_zoho_customer(company, company_data, default_plan, db, company_data.platform_name)
        #     if zoho_customer_id:
        #         print(f"✅ Zoho customer created successfully: {zoho_customer_id}")
        #     else:
        #         print("⚠️ Zoho customer creation returned None")
        # except Exception as e:
        #     print(f"⚠️ Zoho customer creation failed: {e}")
        #     # Enhanced error handling matching Node.js behavior
        #     error_message = "Company created successfully, but Zoho customer creation failed. Please contact support."
        #
        #     # Handle specific error types if available
        #     if hasattr(e, 'response') and e.response:
        #         error_data = e.response.get('data', {})
        #         error_code = error_data.get('code')
        #
        #         if error_code == 100502:
        #             error_message = "Company created successfully, but plan code already exists in Zoho. Please contact support."
        #         elif error_code == 3013:
        #             error_message = "Company created successfully, but invalid customer name for subscription. Please contact support."
        #         elif error_code == 3014:
        #             error_message = "Company created successfully, but invalid email address for subscription. Please contact support."
        #         elif error_code == 3015:
        #             error_message = "Company created successfully, but invalid company name for subscription. Please contact support."
        #         elif error_data.get('message'):
        #             error_message = f"Company created successfully, but Zoho API error: {error_data['message']}"
        #         elif str(e):
        #             error_message = f"Company created successfully, but subscription error: {str(e)}"
        #
        #     print(f"⚠️ {error_message}")
        #     # Continue without Zoho customer ID

        # Send welcome email (non-blocking)
        # try:
        #     app_link = settings.APP_URL  # Use environment-based app URL
        #     email_data = {
        #         "companyName": company.name,
        #         "contactEmail": company_data.contactEmail,
        #         "planName": default_plan.name,
        #         "monthlyPrice": float(default_plan.monthly_price),
        #         "appLink": app_link
        #     }

        #     # Send welcome email asynchronously (don't block the response)
        #     email_result = email_service.send_welcome_email(email_data)
        #     if email_result['success']:
        #         print(f"✅ Welcome email sent successfully to {company_data.contactEmail}")
        #     else:
        #         print(f"⚠️ Welcome email failed: {email_result['message']}")

        # except Exception as email_error:
        #     # Log email error but don't fail the company creation
        #     print(f"⚠️ Email service error (non-critical): {email_error}")

        # Generate API token (JWT)
        access_token = create_access_token(
            data={"sub": str(user_id), "company_id": str(company_id), "role": "admin"}
        )

        # Create token ID for tracking
        token_id = str(uuid.uuid4())

        # Return response in Node.js format
        return SuccessResponse(
            success=True,
            data=CompanyCreationResponse(
                customerId=str(company_id),
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

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create company: {str(e)}"
        )
