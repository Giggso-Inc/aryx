"""
Zoho Billing Service for Python FastAPI

This service mirrors the Node.js ZohoBillingService functionality,
providing comprehensive Zoho API integration for billing, customers, and subscriptions.

Author: Karthick Chandrasekar
Date: 2025-08-26
Version: 1.0.0
"""

import httpx
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime
from decimal import Decimal
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class ZohoBillingService:
    """Zoho Billing Service for managing customers, plans, and subscriptions"""
    
    def __init__(self, platform_name: Optional[str] = None):
        """
        Initialize Zoho Billing Service
        
        Args:
            platform_name: Platform name (e.g., 'prism7', 'accsell', 'zaptag').
                If 'prism7', uses PRISM config; if 'accsell', uses SHAY config;
                if 'zaptag', uses ZAPTAG config; otherwise uses default Zoho config.
        """
        self.platform_name = platform_name
        platform_lower = (platform_name or "").lower()
        self.is_prism = platform_lower == "prism7"
        # Prefix for platform-specific env vars (e.g. PRISM_, SHAY_, ZAPTAG_); empty for default
        self._config_prefix = ""
        # Use platform-specific config when platform_name is prism7, accsell, or zaptag
        if platform_lower == "prism7":
            self._config_prefix = "PRISM_"
            self.base_url = f"{settings.PRISM_ZOHO_BASE_URL}/billing/v1"
            self.org_id = settings.PRISM_ZOHO_ORGANIZATION_ID
            self.client_id = settings.PRISM_ZOHO_CLIENT_ID
            self.client_secret = settings.PRISM_ZOHO_CLIENT_SECRET
            self.refresh_token = settings.PRISM_ZOHO_REFRESH_TOKEN
            self.token_url = settings.PRISM_ZOHO_TOKEN_URL
        elif platform_lower == "accsell":
            self._config_prefix = "SHAY_"
            self.base_url = f"{settings.SHAY_ZOHO_BASE_URL}/billing/v1"
            self.org_id = settings.SHAY_ZOHO_ORGANIZATION_ID
            self.client_id = settings.SHAY_ZOHO_CLIENT_ID
            self.client_secret = settings.SHAY_ZOHO_CLIENT_SECRET
            self.refresh_token = settings.SHAY_ZOHO_REFRESH_TOKEN
            self.token_url = settings.SHAY_ZOHO_TOKEN_URL
        elif platform_lower == "zaptag":
            self._config_prefix = "ZAPTAG_"
            self.base_url = f"{settings.ZAPTAG_ZOHO_BASE_URL}/billing/v1"
            self.org_id = settings.ZAPTAG_ZOHO_ORGANIZATION_ID
            self.client_id = settings.ZAPTAG_ZOHO_CLIENT_ID
            self.client_secret = settings.ZAPTAG_ZOHO_CLIENT_SECRET
            self.refresh_token = settings.ZAPTAG_ZOHO_REFRESH_TOKEN
            self.token_url = settings.ZAPTAG_ZOHO_TOKEN_URL
        else:
            # Default Zoho config — unchanged from previous behavior (no platform_name or unknown value)
            self.base_url = f"{settings.ZOHO_BASE_URL}/billing/v1"
            self.org_id = settings.ZOHO_ORGANIZATION_ID
            self.client_id = settings.ZOHO_CLIENT_ID
            self.client_secret = settings.ZOHO_CLIENT_SECRET
            self.refresh_token = settings.ZOHO_REFRESH_TOKEN
            self.token_url = settings.ZOHO_TOKEN_URL
        
        # Validate configuration
        self._validate_config()

    def get_config_var_name(self, suffix: str) -> str:
        """Return env var name for this platform (e.g. PRISM_ZOHO_REFRESH_TOKEN or ZOHO_REFRESH_TOKEN)."""
        return f"{self._config_prefix}{suffix}" if self._config_prefix else suffix
    
    def _validate_config(self):
        """Validate Zoho configuration for current platform"""
        if self._config_prefix:
            # Platform-specific (prism7, accsell, zaptag) required env vars
            required_vars = [
                f"{self._config_prefix}ZOHO_BASE_URL",
                f"{self._config_prefix}ZOHO_ORGANIZATION_ID",
                f"{self._config_prefix}ZOHO_REFRESH_TOKEN",
                f"{self._config_prefix}ZOHO_CLIENT_ID",
                f"{self._config_prefix}ZOHO_CLIENT_SECRET",
                f"{self._config_prefix}ZOHO_TOKEN_URL",
            ]
            platform_label = self._config_prefix.rstrip("_").upper()
        else:
            required_vars = [
                "ZOHO_BASE_URL",
                "ZOHO_ORGANIZATION_ID",
                "ZOHO_REFRESH_TOKEN",
                "ZOHO_CLIENT_ID",
                "ZOHO_CLIENT_SECRET",
                "ZOHO_TOKEN_URL",
            ]
            platform_label = "Default"
        
        missing_vars = []
        for var in required_vars:
            if not getattr(settings, var, None):
                missing_vars.append(var)
        
        if missing_vars:
            logger.warning(f"⚠️ Missing {platform_label} Zoho configuration variables: {missing_vars}")
            logger.warning(f"⚠️ {platform_label} Zoho integration will not work without these variables")
        
    async def get_auth_token(self) -> str:
        """Get access token using refresh token directly"""
        try:
            # Use refresh token directly instead of calling our own endpoint
            return await self.refresh_auth_token()
        except Exception as error:
            logger.error(f'Error getting auth token: {error}')
            raise error
    
    async def refresh_auth_token(self) -> str:
        """Refresh Zoho access token using refresh token"""
        try:
            # Check required environment variables using instance attributes
            if not self.refresh_token:
                config_type = self.get_config_var_name("ZOHO_REFRESH_TOKEN")
                raise Exception(f"{config_type} environment variable is required")
            if not self.client_id:
                config_type = self.get_config_var_name("ZOHO_CLIENT_ID")
                raise Exception(f"{config_type} environment variable is required")
            if not self.client_secret:
                config_type = self.get_config_var_name("ZOHO_CLIENT_SECRET")
                raise Exception(f"{config_type} environment variable is required")
            if not self.token_url:
                config_type = self.get_config_var_name("ZOHO_TOKEN_URL")
                raise Exception(f"{config_type} environment variable is required")
            
            # Call Zoho API to refresh token
            form_data = {
                'refresh_token': self.refresh_token,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'refresh_token'
            }
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.token_url,
                    data=form_data,
                    headers={'Content-Type': 'application/x-www-form-urlencoded'}
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get('access_token')
                else:
                    raise Exception(f'Zoho token refresh failed: {response.text}')
        except Exception as error:
            logger.error(f'Error refreshing auth token: {error}')
            raise error
    
    async def make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make authenticated request to Zoho API"""
        try:
            # Get access token
            token = await self.get_auth_token()
            
            # Prepare request
            url = f"{self.base_url}{endpoint}"
            headers = {
                'Authorization': f'Zoho-oauthtoken {token}',
                'Content-Type': 'application/json',
                'X-com-zoho-subscriptions-organizationid': self.org_id
            }
            
            logger.info(f'🔄 Making {method.upper()} request to: {url}')
            logger.info(f'🔄 Headers: {headers}')
            if data:
                # Log data but mask sensitive info
                log_data = data.copy()
                if 'customer' in log_data and isinstance(log_data['customer'], dict):
                    log_data['customer'] = {k: v for k, v in log_data['customer'].items() if k != 'email' or not v}
                logger.info(f'🔄 Data: {log_data}')
            
            # Make request
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method.upper() == 'GET':
                    response = await client.get(url, headers=headers)
                elif method.upper() == 'POST':
                    response = await client.post(url, headers=headers, json=data)
                elif method.upper() == 'PUT':
                    response = await client.put(url, headers=headers, json=data)
                elif method.upper() == 'DELETE':
                    response = await client.delete(url, headers=headers)
                else:
                    raise ValueError(f'Unsupported HTTP method: {method}')
                
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
            logger.error(f'❌ Error making Zoho request: {error}')
            raise error
    
    def format_customer_name(self, name: str) -> str:
        """Format customer name for Zoho compatibility"""
        if not name:
            return ''
        
        # Remove special characters that might cause issues
        import re
        formatted_name = re.sub(r'[^a-zA-Z0-9\s\-&.\'()]', '', name)
        formatted_name = re.sub(r'\s+', ' ', formatted_name).strip()
        
        # Ensure minimum length
        if len(formatted_name) < 2:
            formatted_name = name[:50].strip()
        
        # Limit length to 100 characters
        if len(formatted_name) > 100:
            formatted_name = formatted_name[:100].strip()
        
        return formatted_name
    
    async def create_customer(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create customer in Zoho"""
        try:
            # Format customer name
            customer_name = self.format_customer_name(customer_data.get('name', ''))
            if not customer_name or len(customer_name) < 2:
                raise Exception('Customer name must be at least 2 characters')
            
            # Prepare customer data
            data = {
                'display_name': customer_name,
                'salutation': customer_data.get('salutation', 'Mr.'),
                'first_name': customer_data.get('firstName', customer_name.split(' ')[0] or ''),
                'last_name': customer_data.get('lastName', ' '.join(customer_name.split(' ')[1:]) or ''),
                'email': customer_data.get('email'),
                'company_name': customer_data.get('companyName'),
                'phone': customer_data.get('phone', ''),
                'mobile': customer_data.get('mobile', ''),
                'website': customer_data.get('website', ''),
                'currency_code': customer_data.get('currency', 'USD'),
                'payment_terms': customer_data.get('paymentTerms', 0),
                'payment_terms_label': customer_data.get('paymentTermsLabel', 'Due On Receipt')
            }
            
            # Create customer in Zoho
            response = await self.make_request('POST', '/customers', data)
            
            logger.info(f'✅ Customer created successfully in Zoho: {response["customer"]["customer_id"]}')
            return response['customer']
            
        except Exception as error:
            logger.error(f'Error creating customer: {error}')
            raise error
    
    async def get_customers(self) -> List[Dict[str, Any]]:
        """Get all customers from Zoho"""
        try:
            response = await self.make_request('GET', '/customers')
            return response.get('customers', [])
        except Exception as error:
            logger.error(f'Error getting customers: {error}')
            raise error
    
    async def get_customer(self, customer_id: str) -> Dict[str, Any]:
        """Get specific customer from Zoho"""
        try:
            response = await self.make_request('GET', f'/customers/{customer_id}')
            return response.get('customer', {})
        except Exception as error:
            logger.error(f'Error getting customer: {error}')
            raise error
    
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
    
    async def get_customer_invoices(self, customer_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get invoices for a customer from Zoho.
        
        If customer_id is provided, fetches invoices for that specific customer.
        If customer_id is None, fetches all invoices.
        
        Reference: https://www.zoho.com/billing/api/v1/invoices/#list-all-invoices
        """
        try:
            # Build the endpoint with query parameter if customer_id is provided
            if customer_id:
                endpoint = f'/invoices?customer_id={customer_id}'
            else:
                endpoint = '/invoices'
            
            response = await self.make_request('GET', endpoint)
            invoices = response.get('invoices', [])
            logger.info(f'Fetched {len(invoices)} invoices from Zoho (customer_id: {customer_id or "all"})')
            return invoices
        except Exception as error:
            logger.error(f'Error getting customer invoices: {error}')
            # Return empty list if error (customer might not have invoices yet)
            return []
    
    async def get_invoice(self, invoice_id: str) -> Dict[str, Any]:
        """
        Get a single invoice by ID from Zoho.
        
        Args:
            invoice_id: The Zoho invoice ID (numeric ID, e.g., "5502770000001680023")
            
        Returns:
            Dict containing the full invoice details including invoice_items, subscriptions, etc.
            
        Reference: https://www.zoho.com/billing/api/v1/invoices/#get-an-invoice
        """
        try:
            # Build the endpoint to get a specific invoice
            endpoint = f'/invoices/{invoice_id}'
            
            # Make request to get invoice details
            response = await self.make_request('GET', endpoint)
            
            # The response should contain the invoice object directly
            invoice = response.get('invoice', response)
            logger.info(f'Fetched invoice details from Zoho (invoice_id: {invoice_id})')
            return invoice
        except Exception as error:
            logger.error(f'Error getting invoice {invoice_id}: {error}')
            # Re-raise the exception so the caller can handle it
            raise error
    
    async def download_invoice_pdf(self, invoice_id: str) -> bytes:
        """
        Download invoice PDF from Zoho.
        
        Args:
            invoice_id: The Zoho invoice ID (numeric ID, e.g., "5502770000001523062")
            
        Returns:
            bytes: The PDF file content as bytes
            
        Reference: https://www.zoho.com/billing/api/v1/invoices/#download-an-invoice
        """
        try:
            # Get access token
            token = await self.get_auth_token()
            
            # Prepare request URL for PDF download
            # Use the correct endpoint format: /billing/v1/invoices/{invoice_id}?accept=pdf
            url = f"{self.base_url}/invoices/{invoice_id}?accept=pdf"
            headers = {
                'Authorization': f'Zoho-oauthtoken {token}',
                'X-com-zoho-subscriptions-organizationid': self.org_id,
                'Accept': 'application/pdf'
            }
            
            logger.info(f'🔄 Downloading invoice PDF: invoice_id={invoice_id}')
            logger.info(f'🔄 Request URL: {url}')
            
            # Make request to download PDF (binary response)
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers)
                
                logger.info(f'✅ Response status: {response.status_code}')
                
                if response.status_code >= 400:
                    error_text = response.text if hasattr(response, 'text') else str(response.content)
                    logger.error(f'❌ Zoho API error: {response.status_code} - {error_text}')
                    raise Exception(f'Zoho API error: {response.status_code} - {error_text}')
                
                # Return PDF content as bytes
                pdf_content = response.content
                logger.info(f'✅ Invoice PDF downloaded successfully ({len(pdf_content)} bytes)')
                return pdf_content
                
        except httpx.ConnectError as error:
            logger.error(f'❌ Connection error to Zoho API: {error}')
            raise Exception(f'Cannot connect to Zoho API. Please check your network connection and ZOHO_BASE_URL configuration.')
        except httpx.TimeoutException as error:
            logger.error(f'❌ Timeout error to Zoho API: {error}')
            raise Exception(f'Zoho API request timed out. Please try again.')
        except Exception as error:
            logger.error(f'❌ Error downloading invoice PDF: {error}')
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


# Create global instance (default, no platform_name)
zoho_service = ZohoBillingService()


def get_zoho_service(platform_name: Optional[str] = None) -> ZohoBillingService:
    """
    Get Zoho service instance based on platform_name.
    
    Args:
        platform_name: Platform name (e.g., 'prism7', 'accsell', 'zaptag').
            If one of these, returns service with that platform's Zoho config.
        
    Returns:
        ZohoBillingService instance configured for the specified platform
    """
    # Only use platform-specific config for known platforms; otherwise default (unchanged from previous flow)
    if platform_name:
        lower = platform_name.lower()
        if lower in ("prism7", "accsell", "zaptag"):
            return ZohoBillingService(platform_name=lower)
    return zoho_service
