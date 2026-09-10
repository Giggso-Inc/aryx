"""Combined create-subscription-with-customer flow (checks for an existing
customer by email before deciding whether to send customer_id or a full
customer object)."""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class SubscriptionWithCustomerMixin:
    """create_subscription_with_customer: one atomic customer+subscription flow."""

    async def create_subscription_with_customer(self, subscription_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create subscription with customer data in Zoho"""
        try:
            # Get plan details
            plan_code = subscription_data.get('plan', {}).get('planCode', 'ShayFree30')
            plan_description = subscription_data.get('plan', {}).get('description', 'Basic Monthly Plan')

            # Determine auto_collect based on plan cycles
            plan_cycles = subscription_data.get('planCycles', -1)
            auto_collect = subscription_data.get('autoCollect', plan_cycles == -1)

            # Format customer name
            customer_name = self.format_customer_name(
                subscription_data.get('customer', {}).get('displayName') or
                subscription_data.get('customer', {}).get('name', '')
            )

            # Check for existing customer
            existing_customer_id = None
            try:
                customers = await self.get_customers()
                existing_customer = next(
                    (c for c in customers if c.get('email') == subscription_data['customer']['email']),
                    None
                )
                if existing_customer:
                    existing_customer_id = existing_customer['customer_id']
                    logger.info(f'✅ Using existing customer: {existing_customer_id}')
            except Exception as error:
                logger.warning(f'⚠️ Error checking for existing customer: {error}')

            # Prepare subscription data
            if existing_customer_id:
                # Use existing customer
                data = {
                    'customer_id': existing_customer_id,
                    'plan': {
                        'plan_code': plan_code,
                        'plan_description': plan_description,
                        'price': 0,  # Default price for free plan
                        'quantity': 1,
                        'billing_cycles': plan_cycles,
                        'trial_days': 0
                    },
                    'auto_collect': auto_collect,
                    'payment_terms': 0,
                    'payment_terms_label': 'Due On Receipt'
                }
            else:
                # Create new customer with subscription
                data = {
                    'customer': {
                        'display_name': customer_name,
                        'salutation': subscription_data.get('customer', {}).get('salutation', 'Mr.'),
                        'first_name': subscription_data.get('customer', {}).get('firstName', customer_name.split(' ')[0] or ''),
                        'last_name': subscription_data.get('customer', {}).get('lastName', ' '.join(customer_name.split(' ')[1:]) or ''),
                        'email': subscription_data['customer']['email'],
                        'company_name': subscription_data.get('customer', {}).get('companyName', customer_name),
                        'phone': subscription_data.get('customer', {}).get('phone', ''),
                        'mobile': subscription_data.get('customer', {}).get('mobile', ''),
                        'website': subscription_data.get('customer', {}).get('website', ''),
                        'currency_code': subscription_data.get('customer', {}).get('currencyCode', 'USD'),
                        'payment_terms': 0,
                        'payment_terms_label': 'Due On Receipt'
                    },
                    'plan': {
                        'plan_code': plan_code,
                        'plan_description': plan_description,
                        'price': 0,  # Default price for free plan
                        'quantity': 1,
                        'billing_cycles': plan_cycles,
                        'trial_days': 0
                    },
                    'auto_collect': auto_collect,
                    'payment_terms': 0,
                    'payment_terms_label': 'Due On Receipt'
                }

            # Create subscription
            response = await self.make_request('POST', '/subscriptions', data)

            # Get customer ID from response
            final_customer_id = existing_customer_id or response['subscription']['customer_id']

            logger.info(f'✅ Subscription created successfully: {response["subscription"]["subscription_id"]}')
            logger.info(f'✅ Customer ID: {final_customer_id}')

            return {
                'subscription': response['subscription'],
                'customer_id': final_customer_id
            }

        except Exception as error:
            logger.error(f'Error creating subscription with customer: {error}')

            # Handle specific Zoho API errors
            if hasattr(error, 'response') and error.response:
                error_data = error.response.get('data', {})
                error_code = error_data.get('code')

                if error_code == 100502:
                    raise Exception('Plan code already exists in Zoho. This usually happens when multiple companies try to use the same plan. Please contact support.')
                elif error_code == 3013:
                    raise Exception(f'Invalid customer name for subscription: {error_data.get("message", "Name format not supported")}')
                elif error_code == 3014:
                    raise Exception(f'Invalid email address for subscription: {error_data.get("message", "Email format not supported")}')
                elif error_code == 3015:
                    raise Exception(f'Invalid company name for subscription: {error_data.get("message", "Company name format not supported")}')
                elif error_data.get('message'):
                    raise Exception(f'Zoho API error: {error_data["message"]}')

            raise error
