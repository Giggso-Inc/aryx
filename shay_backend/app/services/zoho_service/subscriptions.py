"""
Subscription read/update/cancel/reactivate + local-plan-id lookup helper.

Stated exception (182 lines, over the ~150 target): cancel_subscription and
reactivate_subscription each bypass make_request with their own httpx
call + query-param handling (~40 lines each of near-duplicate error
handling); splitting them into their own files would separate two very
short, symmetrical methods without isolating any independently reusable
concern.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class SubscriptionsMixin:
    """List/get/update/cancel/reactivate subscriptions."""

    async def get_subscriptions(self) -> List[Dict[str, Any]]:
        """Get all subscriptions from Zoho"""
        try:
            response = await self.make_request('GET', '/subscriptions')
            return response.get('subscriptions', [])
        except Exception as error:
            logger.error(f'Error getting subscriptions: {error}')
            raise error

    async def get_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """Get specific subscription from Zoho"""
        try:
            response = await self.make_request('GET', f'/subscriptions/{subscription_id}')
            return response.get('subscription', {})
        except Exception as error:
            logger.error(f'Error getting subscription: {error}')
            raise error

    async def update_subscription(self, subscription_id: str, subscription_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update subscription in Zoho"""
        try:
            # Prepare update data
            data = {}

            # Handle plan update if provided
            if subscription_data.get('subscriptionPlanId'):
                # Get Zoho plan ID from local database or create/find it
                zoho_plan_id = await self._get_zoho_plan_id(subscription_data['subscriptionPlanId'])
                if zoho_plan_id:
                    data['plan'] = {'plan_code': zoho_plan_id}

            # Handle other subscription properties
            if 'autoCollect' in subscription_data:
                data['auto_collect'] = subscription_data['autoCollect']
            if 'paymentTerms' in subscription_data:
                data['payment_terms'] = subscription_data['paymentTerms']
            if 'paymentTermsLabel' in subscription_data:
                data['payment_terms_label'] = subscription_data['paymentTermsLabel']
            if 'referenceId' in subscription_data:
                data['reference_id'] = subscription_data['referenceId']
            if 'startsAt' in subscription_data:
                data['starts_at'] = subscription_data['startsAt']
            if 'billingCycles' in subscription_data:
                data['billing_cycles'] = subscription_data['billingCycles']

            # Make the update request to Zoho
            response = await self.make_request('PUT', f'/subscriptions/{subscription_id}', data)
            return response.get('subscription', {})

        except Exception as error:
            logger.error(f'Error updating subscription: {error}')
            raise error

    async def get_hosted_page(self, hosted_page_id: str) -> Dict[str, Any]:
        """Retrieve hosted page details from Zoho"""
        try:
            endpoint = f'/hostedpages/{hosted_page_id}'
            response = await self.make_request('GET', endpoint)
            return response
        except Exception as error:
            logger.error(f'Error retrieving hosted page: {error}')
            raise error

    async def cancel_subscription(self, subscription_id: str, cancel_at_end: bool = False) -> Dict[str, Any]:
        """Cancel a subscription in Zoho"""
        try:
            # According to Zoho API docs, cancel_at_end is a query parameter
            # If cancel_at_end is true, status becomes non_renewing
            # If cancel_at_end is false, status becomes cancelled
            endpoint = f'/subscriptions/{subscription_id}/cancel'

            # Use query parameters for cancel_at_end
            url = f"{self.base_url}{endpoint}"
            params = {'cancel_at_end': str(cancel_at_end).lower()}

            # Get access token
            token = await self.get_auth_token()

            # Prepare headers
            headers = {
                'Authorization': f'Zoho-oauthtoken {token}',
                'X-com-zoho-subscriptions-organizationid': self.org_id
            }

            logger.info(f'🔄 Canceling subscription {subscription_id} with cancel_at_end={cancel_at_end}')

            # Make POST request with query parameters
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, params=params)

                logger.info(f'✅ Response status: {response.status_code}')

                if response.status_code >= 400:
                    logger.error(f'❌ Zoho API error: {response.status_code} - {response.text}')
                    raise Exception(f'Zoho API error: {response.status_code} - {response.text}')

                return response.json()

        except httpx.ConnectError as error:
            logger.error(f'❌ Connection error to Zoho API: {error}')
            raise Exception(f'Cannot connect to Zoho API. Please check your network connection and ZOHO_BASE_URL configuration.')
        except httpx.TimeoutException as error:
            logger.error(f'❌ Timeout error to Zoho API: {error}')
            raise Exception(f'Zoho API request timed out. Please try again.')
        except Exception as error:
            logger.error(f'❌ Error canceling subscription: {error}')
            raise error

    async def reactivate_subscription(self, subscription_id: str, billing_cycles: int = 12) -> Dict[str, Any]:
        """
        Reactivate a cancelled subscription in Zoho.
        Zoho requires billing_cycles (code 101017 if missing); sent as query param like cancel_at_end for cancel.
        Reference: https://www.zoho.com/billing/api/v1/subscription/#reactivate-subscription
        """
        try:
            endpoint = f'/subscriptions/{subscription_id}/reactivate'
            url = f"{self.base_url}{endpoint}"
            # Zoho expects billing_cycles as query parameter (same pattern as cancel's cancel_at_end)
            params = {"billing_cycles": billing_cycles}
            token = await self.get_auth_token()
            headers = {
                "Authorization": f"Zoho-oauthtoken {token}",
                "X-com-zoho-subscriptions-organizationid": self.org_id,
            }
            logger.info(f'🔄 Reactivating subscription {subscription_id} with billing_cycles={billing_cycles} (query param)')
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, params=params)
                logger.info(f'✅ Response status: {response.status_code}')
                if response.status_code >= 400:
                    logger.error(f'❌ Zoho API error: {response.status_code} - {response.text}')
                    raise Exception(f'Zoho API error: {response.status_code} - {response.text}')
                return response.json()
        except httpx.ConnectError as error:
            logger.error(f'❌ Connection error to Zoho API: {error}')
            raise Exception('Cannot connect to Zoho API. Please check your network connection and ZOHO_BASE_URL configuration.')
        except httpx.TimeoutException as error:
            logger.error(f'❌ Timeout error to Zoho API: {error}')
            raise Exception('Zoho API request timed out. Please try again.')
        except Exception as error:
            logger.error(f'❌ Error reactivating subscription: {error}')
            raise error

    async def _get_zoho_plan_id(self, subscription_plan_id: str) -> Optional[str]:
        """Get Zoho plan ID for a subscription plan"""
        try:
            # Import here to avoid circular imports
            from app.core.database import get_db
            from app.models.subscription_plan import SubscriptionPlan
            from sqlalchemy import select

            # Get database session
            async for db in get_db():
                # Query the subscription_plans table for zoho_plan_id
                result = await db.execute(
                    select(SubscriptionPlan.zoho_plan_id)
                    .where(SubscriptionPlan.id == subscription_plan_id)
                )
                zoho_plan_id = result.scalar_one_or_none()

                if zoho_plan_id:
                    logger.info(f'Found Zoho plan ID {zoho_plan_id} for subscription plan {subscription_plan_id}')
                    return zoho_plan_id
                else:
                    logger.warning(f'No Zoho plan ID found for subscription plan: {subscription_plan_id}')
                    return None

        except Exception as error:
            logger.error(f'Error getting Zoho plan ID: {error}')
            return None
