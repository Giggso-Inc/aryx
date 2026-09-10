"""Invoice listing/get/PDF-download against Zoho."""

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class InvoicesMixin:
    """List/get invoices and download an invoice PDF."""

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
