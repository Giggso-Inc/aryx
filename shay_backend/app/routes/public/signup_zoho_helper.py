"""
Zoho customer/subscription provisioning helper for company signup.

Split out of signup_helpers.py purely for the 150-line-per-file target —
this is otherwise the same "post-create setup" category as the gpt-vault and
subscription helpers there. Currently only referenced from commented-out code
in signup_create.py (Zoho integration is disabled), kept intact per the
characterization tests' golden-master of signup.py's public surface.
"""

from typing import Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.company import Company
from app.models.subscription_plan import SubscriptionPlan
from app.models.subscription import Subscription


async def _create_zoho_customer(company: Company, company_data: Any, plan: SubscriptionPlan, db: AsyncSession, platform_name: Optional[str] = None) -> Optional[str]:
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
