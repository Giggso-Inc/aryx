"""
Zoho hosted-page creation for new subscriptions and subscription updates.

Stated exception (163 lines, over the ~150 target): update_subscription_hosted_page
alone is ~90 lines of one atomic camelCase->snake_case field-normalization
pass (mirrors subscription_create.py's same-shaped stated exception);
splitting it further would fragment one payload-building flow across files.
"""

import logging
from typing import Any, Dict

from app.core.config import settings

logger = logging.getLogger(__name__)


class HostedPagesMixin:
    """Create hosted payment pages for new/updated subscriptions."""

    async def create_hosted_page(self, subscription_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create hosted payment page in Zoho. Uses existing customer_id when provided (from subscriptions.zoho_customer_id), else sends customer object for new customer."""
        try:
            # Plan payload per Zoho Hosted-Pages API (Create a subscription)
            data = {
                'plan': {
                    'plan_code': subscription_data.get('planCode', 'ShayFree30'),
                    'quantity': 1,
                },
                'redirect_url': subscription_data.get('redirectUrl', f"{settings.FRONTEND_URL}/payment-success"),
                'auto_collect': subscription_data.get('autoCollect', True),
            }
            # Existing customer: send customer_id only. New customer: send customer object (do not send customer_id).
            zoho_customer_id = subscription_data.get('zoho_customer_id')
            if zoho_customer_id:
                data['customer_id'] = zoho_customer_id
            else:
                data['customer'] = {
                    'display_name': subscription_data.get('customerName', 'Customer'),
                    'salutation': 'Mr.',
                    'first_name': subscription_data.get('customerName', 'Customer'),
                    'last_name': subscription_data.get('customerName', 'Customer'),
                    'email': subscription_data.get('customerEmail'),
                    'company_name': subscription_data.get('companyName', 'Company'),
                    'website': subscription_data.get('companyDomain', ''),
                    'currency_code': 'USD',
                }

            # Create hosted page
            response = await self.make_request('POST', '/hostedpages/newsubscription', data)

            logger.info(f'✅ Hosted page created successfully: {response.get("hostedpage", {}).get("hostedpage_id")}')

            return {
                'hostedPageId': response.get('hostedpage', {}).get('hostedpage_id') or response.get('hostedpage_id'),
                'hostedPageUrl': response.get('hostedpage', {}).get('url') or response.get('hostedpage_url') or response.get('url'),
                'subscription': response.get('subscription', response)
            }

        except Exception as error:
            logger.error(f'Error creating hosted page: {error}')
            raise error

    async def update_subscription_hosted_page(self, subscription_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create hosted payment page for updating a subscription in Zoho"""
        try:
            # Build the request data based on Zoho API documentation
            # can_prorate and end_of_term always sent from backend (not from frontend)
            data = {
                'subscription_id': subscription_data.get('subscriptionId'),
                'can_prorate': False,
                'end_of_term': True,
            }

            # Add plan if provided
            if subscription_data.get('plan'):
                plan_data = subscription_data['plan']
                data['plan'] = {
                    'plan_code': plan_data.get('planCode') or plan_data.get('plan_code'),
                    'plan_description': plan_data.get('planDescription') or plan_data.get('plan_description'),
                    'price': plan_data.get('price'),
                    'setup_fee': plan_data.get('setupFee') or plan_data.get('setup_fee'),
                    'quantity': plan_data.get('quantity', 1),
                    'tax_id': plan_data.get('taxId') or plan_data.get('tax_id'),
                    'tax_exemption_id': plan_data.get('taxExemptionId') or plan_data.get('tax_exemption_id'),
                    'tax_exemption_code': plan_data.get('taxExemptionCode') or plan_data.get('tax_exemption_code'),
                    'setup_fee_tax_exemption_id': plan_data.get('setupFeeTaxExemptionId') or plan_data.get('setup_fee_tax_exemption_id'),
                    'setup_fee_tax_exemption_code': plan_data.get('setupFeeTaxExemptionCode') or plan_data.get('setup_fee_tax_exemption_code'),
                    'exclude_trial': plan_data.get('excludeTrial') or plan_data.get('exclude_trial', False),
                    'exclude_setup_fee': plan_data.get('excludeSetupFee') or plan_data.get('exclude_setup_fee', False),
                    'billing_cycles': plan_data.get('billingCycles') or plan_data.get('billing_cycles'),
                    'trial_days': plan_data.get('trialDays') or plan_data.get('trial_days', 0)
                }

                # Remove None values
                data['plan'] = {k: v for k, v in data['plan'].items() if v is not None}

            # Add addons if provided
            if subscription_data.get('addons'):
                data['addons'] = []
                for addon in subscription_data['addons']:
                    addon_data = {
                        'addon_code': addon.get('addonCode') or addon.get('addon_code'),
                        'addon_description': addon.get('addonDescription') or addon.get('addon_description'),
                        'price': addon.get('price'),
                        'quantity': addon.get('quantity', 1),
                        'tax_id': addon.get('taxId') or addon.get('tax_id'),
                        'tax_exemption_id': addon.get('taxExemptionId') or addon.get('tax_exemption_id'),
                        'tax_exemption_code': addon.get('taxExemptionCode') or addon.get('tax_exemption_code')
                    }
                    # Remove None values
                    addon_data = {k: v for k, v in addon_data.items() if v is not None}
                    data['addons'].append(addon_data)

            # Add optional fields
            if subscription_data.get('referenceId'):
                data['reference_id'] = subscription_data['referenceId']
            if subscription_data.get('startsAt'):
                data['starts_at'] = subscription_data['startsAt']
            if subscription_data.get('customFields'):
                data['custom_fields'] = subscription_data['customFields']
            if subscription_data.get('couponCode'):
                data['coupon_code'] = subscription_data['couponCode']
            if subscription_data.get('redirectUrl'):
                data['redirect_url'] = subscription_data['redirectUrl']
            if subscription_data.get('salespersonName'):
                data['salesperson_name'] = subscription_data['salespersonName']
            if subscription_data.get('canChargeSetupFeeImmediately') is not None:
                data['can_charge_setup_fee_immediately'] = subscription_data['canChargeSetupFeeImmediately']
            if subscription_data.get('exchangeRate'):
                data['exchange_rate'] = subscription_data['exchangeRate']
            if subscription_data.get('placeOfSupply'):
                data['place_of_supply'] = subscription_data['placeOfSupply']
            if subscription_data.get('gstTreatment'):
                data['gst_treatment'] = subscription_data['gstTreatment']
            if subscription_data.get('gstNo'):
                data['gst_no'] = subscription_data['gstNo']
            if subscription_data.get('cfdiUsage'):
                data['cfdi_usage'] = subscription_data['cfdiUsage']
            if subscription_data.get('paymentGateways'):
                data['payment_gateways'] = [
                    {'payment_gateway': pg.get('paymentGateway') or pg.get('payment_gateway')}
                    for pg in subscription_data['paymentGateways']
                ]
            if subscription_data.get('billingAddressId'):
                data['billing_address_id'] = subscription_data['billingAddressId']
            if subscription_data.get('shippingAddressId'):
                data['shipping_address_id'] = subscription_data['shippingAddressId']
            if subscription_data.get('branchId'):
                data['branch_id'] = subscription_data['branchId']
            if subscription_data.get('templateId'):
                data['template_id'] = subscription_data['templateId']

            # Create hosted page for subscription update
            response = await self.make_request('POST', '/hostedpages/updatesubscription', data)

            logger.info(f'✅ Update subscription hosted page created successfully: {response.get("hostedpage", {}).get("hostedpage_id")}')

            return {
                'hostedPageId': response.get('hostedpage', {}).get('hostedpage_id') or response.get('hostedpage_id'),
                'hostedPageUrl': response.get('hostedpage', {}).get('url') or response.get('hostedpage_url') or response.get('url'),
                'action': response.get('hostedpage', {}).get('action') or response.get('action'),
                'expiringTime': response.get('hostedpage', {}).get('expiring_time') or response.get('expiring_time'),
                'createdTime': response.get('hostedpage', {}).get('created_time') or response.get('created_time'),
                'subscription': response.get('subscription', response)
            }

        except Exception as error:
            logger.error(f'Error creating update subscription hosted page: {error}')
            raise error
