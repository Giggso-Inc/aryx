"""
Auth-token refresh and the generic authenticated-request dispatcher shared
by every higher-level Zoho API method.
"""

import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class AuthMixin:
    """Token refresh + generic `make_request` HTTP dispatcher."""

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
