"""
Shared low-level helpers for company signup: placeholder gpt-vault creation
and free-plan subscription creation. Extracted from signup.py so
create_company/create_company_simple can stay as thin orchestrators — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2 follow-up.
(Domain/email lookups and password decryption live in signup_lookup.py; Zoho
provisioning lives in signup_zoho_helper.py.)
"""

from typing import Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
from decimal import Decimal
import uuid
import logging

from app.core.config import settings
from app.models.subscription_plan import SubscriptionPlan
from app.models.subscription import Subscription
from app.models.giggso_vault import GiggsoVault
from app.services.vault_service import vault_service
from app.routes.token_details import _normalize_token_type_for_vault  # ML vault shape normalization

logger = logging.getLogger(__name__)


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
