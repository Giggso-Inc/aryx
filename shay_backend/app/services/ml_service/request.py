"""
Embedding-request mixin for MLService.

Split out of the former app/services/ml_service.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a). This mixin owns
`request_embedding_processing`, the POST that kicks off ML embedding for a
set of vault-token datasources. Combined with StatusMixin and DeleteMixin
by MLService in client.py.
"""

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class RequestEmbeddingMixin:
    """POST /shay/email/embeddings — request ML embedding processing."""

    async def request_embedding_processing(
        self,
        vault_unique_ids: List[str],
        user_id: str,
        company_id: str,
        channel_id: str,
        embedded_vault_unique_ids: List[str] = None,
        jwt_token: str = None,
        embedd_type: str = "textual",
        table_name: Optional[str] = None,
        table_names: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
        openai_vault_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Request embedding processing from ML API

        Args:
            vault_unique_ids: List of vault unique IDs to process
            user_id: User ID who requested the processing
            company_id: Company ID for context
            channel_id: Channel ID from the request
            embedded_vault_unique_ids: List of already embedded vault unique IDs
            jwt_token: JWT token for authentication (optional, falls back to ML_API_KEY)
            embedd_type: Type of embedding ("textual" or "tabular")
            table_name: Optional table name for database datasources
            thread_id: Optional thread ID for thread-level embeddings (internal/bulk); when set, storage is thread-scoped
            openai_vault_token: Optional vault_unique_id from gg_vault (vault_type='gpt_token') for the company; sent as openaiVaultToken to ML API

        Returns:
            Dict containing the response from ML API
        """
        # Prepare payload with camelCase and new fields
        payload = {
            "channelId": channel_id,
            "dataSourcesVaultTokens": vault_unique_ids,
            "embeddedDataSourceVaultTokens": embedded_vault_unique_ids or [],
            "userId": user_id,
            "companyId": company_id,
            "embeddType": embedd_type,
        }
        # Include threadId for thread-level embedding storage (internal/bulk API)
        if thread_id:
            payload["threadId"] = thread_id
        # Add table_names to payload if provided, otherwise add table_name if provided
        if table_names:
            payload["tableNames"] = table_names
        elif table_name:
            payload["tableName"] = table_name
        # Add OpenAI vault token from gg_vault (gpt_token) for ML layer when available
        if openai_vault_token:
            payload["openaiVaultToken"] = openai_vault_token

        # Prepare headers - use JWT token if provided, otherwise fall back to ML_API_KEY
        auth_token = jwt_token if jwt_token else settings.ML_API_KEY
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}" if auth_token else "",
        }

        # Construct full URL
        full_url = f"{self.ml_api_url}/shay/email/embeddings"

        # Log ML API details BEFORE making the request
        logger.info("=" * 80)
        logger.info("🚀 ML API REQUEST - EMBEDDING PROCESSING")
        logger.info("=" * 80)
        logger.info(f"📡 ML API URL: {full_url}")
        logger.info(
            f"🔑 Auth Token: {'JWT Token (***' + auth_token[-4:] + ')' if jwt_token else ('API Key (***' + self.ml_api_key[-4:] + ')' if self.ml_api_key else 'NOT SET')}"
        )
        logger.info(f"⏱️  Timeout: {self.timeout} seconds")
        logger.info(f"📦 Payload: {json.dumps(payload, indent=2)}")
        logger.info(
            f"📋 Headers: {json.dumps({k: v if k != 'Authorization' else 'Bearer ***' for k, v in headers.items()}, indent=2)}"
        )
        logger.info("=" * 80)
        logger.info("🔄 Attempting to connect to ML API...")
        logger.info("=" * 80)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(full_url, json=payload, headers=headers)

                # Log response details
                logger.info("=" * 80)
                logger.info("📥 ML API RESPONSE")
                logger.info("=" * 80)
                logger.info(f"📊 Status Code: {response.status_code}")
                logger.info(f"📋 Response Headers: {dict(response.headers)}")
                logger.info(f"📄 Response Body: {response.text}")
                logger.info("=" * 80)

                if response.status_code == 200:
                    try:
                        result = response.json()
                        logger.info(
                            f"✅ Successfully requested embedding processing for {len(vault_unique_ids)} datasources"
                        )
                        logger.info(f"📊 ML API Response Data: {json.dumps(result, indent=2)}")
                        return {
                            "success": True,
                            "message": "Embedding processing requested successfully",
                            "data": result,
                        }
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Failed to parse ML API response as JSON: {e}")
                        return {
                            "success": False,
                            "message": "Invalid JSON response from ML API",
                            "error": f"JSON decode error: {e}",
                        }
                else:
                    logger.error(f"❌ ML API returned error: {response.status_code} - {response.text}")
                    return {
                        "success": False,
                        "message": f"ML API error: {response.status_code}",
                        "error": response.text,
                    }

        except httpx.TimeoutException:
            logger.error("=" * 80)
            logger.error("⏰ ML API TIMEOUT ERROR")
            logger.error("=" * 80)
            logger.error(f"⏱️  Timeout after {self.timeout} seconds")
            logger.error(f"📡 URL: {full_url}")
            logger.error(f"📦 Payload that failed: {json.dumps(payload, indent=2)}")
            logger.error(
                f"📋 Headers that failed: {json.dumps({k: v if k != 'Authorization' else 'Bearer ***' for k, v in headers.items()}, indent=2)}"
            )
            logger.error("=" * 80)
            return {
                "success": False,
                "message": "Timeout while calling ML API",
                "error": "Request timed out",
            }
        except httpx.RequestError as e:
            logger.error("=" * 80)
            logger.error("🌐 ML API REQUEST ERROR")
            logger.error("=" * 80)
            logger.error(f"📡 URL: {full_url}")
            logger.error(f"❌ Error: {str(e)}")
            logger.error(f"🔍 Error Type: {type(e).__name__}")
            logger.error(f"📦 Payload that failed: {json.dumps(payload, indent=2)}")
            logger.error(
                f"📋 Headers that failed: {json.dumps({k: v if k != 'Authorization' else 'Bearer ***' for k, v in headers.items()}, indent=2)}"
            )
            logger.error("=" * 80)
            return {
                "success": False,
                "message": "Failed to connect to ML API",
                "error": str(e),
            }
        except Exception as e:
            logger.error("=" * 80)
            logger.error("💥 ML API UNEXPECTED ERROR")
            logger.error("=" * 80)
            logger.error(f"📡 URL: {full_url}")
            logger.error(f"❌ Error: {str(e)}")
            logger.error(f"🔍 Error Type: {type(e).__name__}")
            logger.error(f"📦 Payload that failed: {json.dumps(payload, indent=2)}")
            logger.error(
                f"📋 Headers that failed: {json.dumps({k: v if k != 'Authorization' else 'Bearer ***' for k, v in headers.items()}, indent=2)}"
            )
            logger.error("=" * 80)
            return {
                "success": False,
                "message": "Unexpected error occurred",
                "error": str(e),
            }
