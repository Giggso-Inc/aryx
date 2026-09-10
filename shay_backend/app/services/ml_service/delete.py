"""
Embedding-deletion mixin for MLService.

Split out of the former app/services/ml_service.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a). This mixin owns
`delete_embeddings`, a POST against the ML API's delete-embeddings
endpoint. Combined with RequestEmbeddingMixin and StatusMixin by MLService
in client.py.
"""

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class DeleteMixin:
    """POST /dataai/shay/deleteEmbeddings — delete embeddings for a channel."""

    async def delete_embeddings(
        self,
        channel_id: str,
        data_sources_vault_tokens: Optional[List[str]] = None,
        embedding_type: str = "textual",
        jwt_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Delete embeddings from ML API

        Args:
            channel_id: Channel ID
            data_sources_vault_tokens: List of vault unique IDs to delete embeddings for (optional)
            embedding_type: Type of embedding ("textual" or "tabular")
            jwt_token: JWT token for authentication (optional, falls back to ML_API_KEY)

        Returns:
            Dict containing the response from ML API with success/error status
        """
        # Prepare payload with camelCase
        payload = {
            "channelId": channel_id,
            "dataSourcesVaultTokens": data_sources_vault_tokens if data_sources_vault_tokens else None,
            "embeddingType": embedding_type,
        }

        # Prepare headers - use JWT token if provided, otherwise fall back to ML_API_KEY
        auth_token = jwt_token if jwt_token else self.ml_api_key
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}" if auth_token else "",
        }

        full_url = f"{self.ml_api_url}/dataai/shay/deleteEmbeddings"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(full_url, json=payload, headers=headers)

                if response.status_code == 200:
                    try:
                        result = response.json()
                        logger.info(f" Successfully deleted embeddings for channel {channel_id}")
                        logger.info(f"ML API Response Data: {json.dumps(result, indent=2)}")
                        return {
                            "success": True,
                            "message": "Embeddings deleted successfully",
                            "data": result,
                        }
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse ML API response as JSON: {e}")
                        return {
                            "success": False,
                            "message": "Invalid JSON response from ML API",
                            "error": f"JSON decode error: {e}",
                        }
                else:
                    logger.error(f" ML API returned error: {response.status_code} - {response.text}")
                    return {
                        "success": False,
                        "message": f"ML API error: {response.status_code}",
                        "error": response.text,
                    }

        except httpx.TimeoutException:
            return {
                "success": False,
                "message": "Timeout while calling ML API",
                "error": "Request timed out",
            }
        except httpx.RequestError as e:
            return {
                "success": False,
                "message": "Failed to connect to ML API",
                "error": str(e),
            }
        except Exception as e:
            return {
                "success": False,
                "message": "Unexpected error occurred",
                "error": str(e),
            }
