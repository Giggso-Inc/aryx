"""Customer name formatting + basic customer CRUD against Zoho."""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class CustomersMixin:
    """Customer name formatting + create/list/get."""

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
