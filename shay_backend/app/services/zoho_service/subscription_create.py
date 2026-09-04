"""
create_subscription: normalizes a caller-supplied camelCase/snake_case mix
of customer + plan fields into Zoho's exact request shape, then posts it.

Stated exception (well over the ~150-line-per-file target on its own):
every branch here (customer-object normalization, plan-object normalization,
optional top-level fields, the plan-code error-message rewrite) is part of
one atomic request-building flow for a single Zoho API call — there is no
independently reusable sub-concern to extract without fragmenting one
validation/normalization pass across files. Same reasoning as
app/routes/tasks/crud.py's create_task/update_task stated exception.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class SubscriptionCreateMixin:
    """create_subscription: full field-normalization + POST to /subscriptions."""

    async def create_subscription(self, subscription_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a subscription in Zoho.

        This method creates a subscription directly in Zoho using the provided subscription data.
        The subscription_data should contain customer/customer_id, plan, and other subscription details.
        """
        try:
            # Build the request payload for Zoho API
            data = {}

            # Handle customer - either customer object or customer_id
            if subscription_data.get('customer'):
                customer_data = subscription_data['customer']
                logger.info(f'🔄 Received customer data: {customer_data}')

                # Normalize customer object - convert camelCase to snake_case and ensure required fields
                zoho_customer = {}

                # display_name is required
                display_name = customer_data.get('display_name') or customer_data.get('displayName')
                if not display_name:
                    raise ValueError("'display_name' or 'displayName' is required in customer object")

                # Format customer name (remove extra spaces, ensure minimum length)
                display_name = self.format_customer_name(display_name)
                if not display_name or len(display_name) < 2:
                    raise ValueError("Customer display_name must be at least 2 characters after formatting")

                zoho_customer['display_name'] = display_name

                # first_name and last_name are required by Zoho
                # Extract from displayName if not provided separately
                first_name = customer_data.get('first_name') or customer_data.get('firstName')
                last_name = customer_data.get('last_name') or customer_data.get('lastName')

                if not first_name or not last_name:
                    # Split display_name into first and last name
                    name_parts = display_name.split(' ', 1)
                    if len(name_parts) > 1:
                        first_name = name_parts[0] if not first_name else first_name
                        last_name = name_parts[1] if not last_name else last_name
                    else:
                        # Single word name - use it as first_name, last_name can be empty or same
                        first_name = name_parts[0] if not first_name else first_name
                        last_name = last_name if last_name else ''  # Allow empty last_name

                # Ensure first_name is not empty (required by Zoho)
                if not first_name or not first_name.strip():
                    first_name = display_name

                # Clean and format names
                first_name = first_name.strip()
                last_name = last_name.strip() if last_name else ''

                # Zoho requires first_name to be at least 1 character
                if len(first_name) < 1:
                    raise ValueError("Customer first_name must be at least 1 character")

                zoho_customer['first_name'] = first_name
                zoho_customer['last_name'] = last_name  # Can be empty string

                # email is required
                email = customer_data.get('email')
                if not email:
                    raise ValueError("'email' is required in customer object")
                zoho_customer['email'] = email

                # Optional fields - normalize from camelCase to snake_case
                if 'company_name' in customer_data or 'companyName' in customer_data:
                    zoho_customer['company_name'] = customer_data.get('company_name') or customer_data.get('companyName')

                if 'salutation' in customer_data:
                    zoho_customer['salutation'] = customer_data['salutation']

                if 'phone' in customer_data:
                    zoho_customer['phone'] = customer_data['phone']

                if 'mobile' in customer_data:
                    zoho_customer['mobile'] = customer_data['mobile']

                if 'website' in customer_data:
                    zoho_customer['website'] = customer_data['website']

                if 'currency_code' in customer_data or 'currencyCode' in customer_data:
                    zoho_customer['currency_code'] = customer_data.get('currency_code') or customer_data.get('currencyCode')

                # Remove None values
                zoho_customer = {k: v for k, v in zoho_customer.items() if v is not None and v != ''}

                # Ensure required fields are present
                if not zoho_customer.get('first_name'):
                    zoho_customer['first_name'] = display_name
                if not zoho_customer.get('last_name'):
                    zoho_customer['last_name'] = ''  # Zoho may require this even if empty

                data['customer'] = zoho_customer
                logger.info(f'🔄 Customer data for Zoho: {zoho_customer}')

            elif subscription_data.get('customerId'):
                data['customer_id'] = subscription_data['customerId']
            else:
                raise ValueError("Either 'customer' object or 'customerId' must be provided")

            # Handle plan (required) - normalize field names from camelCase to snake_case
            if subscription_data.get('plan'):
                plan_data = subscription_data['plan']
                logger.info(f'🔄 Received plan data: {plan_data}')

                # Build plan object with proper field names for Zoho API
                zoho_plan = {}

                # plan_code is required - check both camelCase and snake_case
                plan_code = plan_data.get('plan_code') or plan_data.get('planCode')
                if not plan_code:
                    logger.error(f'❌ Plan code not found in plan data. Available keys: {list(plan_data.keys())}')
                    raise ValueError("'plan_code' or 'planCode' is required in plan object. Please provide a valid Zoho plan code.")

                # Ensure plan_code is a string and not empty
                plan_code = str(plan_code).strip()
                if not plan_code:
                    raise ValueError("plan_code cannot be empty. Please provide a valid Zoho plan code.")

                zoho_plan['plan_code'] = plan_code
                logger.info(f'🔄 Using plan_code: {plan_code}')

                # Optional plan fields - normalize from camelCase to snake_case
                if 'quantity' in plan_data:
                    zoho_plan['quantity'] = plan_data['quantity']
                elif 'quantity' not in plan_data:
                    zoho_plan['quantity'] = 1  # Default quantity

                if 'price' in plan_data:
                    zoho_plan['price'] = plan_data['price']

                if 'plan_description' in plan_data or 'planDescription' in plan_data:
                    zoho_plan['plan_description'] = plan_data.get('plan_description') or plan_data.get('planDescription')

                if 'setup_fee' in plan_data or 'setupFee' in plan_data:
                    zoho_plan['setup_fee'] = plan_data.get('setup_fee') or plan_data.get('setupFee')

                if 'tax_id' in plan_data or 'taxId' in plan_data:
                    zoho_plan['tax_id'] = plan_data.get('tax_id') or plan_data.get('taxId')

                if 'billing_cycles' in plan_data or 'billingCycles' in plan_data:
                    zoho_plan['billing_cycles'] = plan_data.get('billing_cycles') or plan_data.get('billingCycles')

                if 'trial_days' in plan_data or 'trialDays' in plan_data:
                    zoho_plan['trial_days'] = plan_data.get('trial_days') or plan_data.get('trialDays')

                if 'exclude_trial' in plan_data or 'excludeTrial' in plan_data:
                    zoho_plan['exclude_trial'] = plan_data.get('exclude_trial') or plan_data.get('excludeTrial')

                if 'exclude_setup_fee' in plan_data or 'excludeSetupFee' in plan_data:
                    zoho_plan['exclude_setup_fee'] = plan_data.get('exclude_setup_fee') or plan_data.get('excludeSetupFee')

                # Remove None values
                zoho_plan = {k: v for k, v in zoho_plan.items() if v is not None}

                # Validate plan_code is not empty
                if not zoho_plan.get('plan_code') or not str(zoho_plan.get('plan_code')).strip():
                    raise ValueError("plan_code cannot be empty. Please provide a valid Zoho plan code.")

                data['plan'] = zoho_plan
                logger.info(f'🔄 Plan data for Zoho: {zoho_plan}')
                logger.info(f'🔄 Plan code being sent: {zoho_plan.get("plan_code")}')
            else:
                raise ValueError("'plan' object is required")

            # Handle optional fields
            if 'autoCollect' in subscription_data:
                data['auto_collect'] = subscription_data['autoCollect']
            if 'referenceId' in subscription_data:
                data['reference_id'] = subscription_data['referenceId']
            if 'startsAt' in subscription_data:
                data['starts_at'] = subscription_data['startsAt']
            if 'addons' in subscription_data:
                data['addons'] = subscription_data['addons']
            if 'couponCode' in subscription_data:
                data['coupon_code'] = subscription_data['couponCode']

            # Make POST request to Zoho API
            logger.info(f'🔄 Final request payload to Zoho: {data}')
            response = await self.make_request('POST', '/subscriptions', data)

            logger.info(f'✅ Subscription created successfully in Zoho: {response.get("subscription", {}).get("subscription_id")}')

            return response

        except Exception as error:
            error_msg = str(error)
            logger.error(f'Error creating subscription in Zoho: {error}')

            # Provide more helpful error message for plan code errors
            if 'Invalid value passed for Plan Code' in error_msg or 'plan_code' in error_msg.lower():
                plan_code_sent = data.get('plan', {}).get('plan_code', 'unknown') if 'data' in locals() else 'unknown'
                platform_hint = (
                    f"If using platform_name in ('prism7','accsell','zaptag'), "
                    f"ensure the plan exists in that platform's Zoho account. "
                )
                raise Exception(
                    f"Invalid plan code '{plan_code_sent}'. "
                    f"Please verify that this plan code exists in your Zoho Billing account. "
                    f"{platform_hint}"
                    f"Error details: {error_msg}"
                )

            raise error
