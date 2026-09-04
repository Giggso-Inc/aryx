"""
Embedding-status mixin for MLService.

Split out of the former app/services/ml_service.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a). This mixin owns
`check_embedding_status`, a GET against the ML API's status endpoint.
Combined with RequestEmbeddingMixin and DeleteMixin by MLService in
client.py.

Note (pre-existing, characterized as-is): unlike
`request_embedding_processing` (which falls back to `settings.ML_API_KEY`
directly), this method falls back to `self.ml_api_key` — a value cached at
`MLService.__init__` time via `getattr(settings, 'ML_API_KEY', '')`. The two
are usually equal but diverge if `settings.ML_API_KEY` changes after the
service instance is constructed.
"""

import json
import logging
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)


class StatusMixin:
    """GET /api/v1/embedding/status — check embedding processing status."""

    async def check_embedding_status(self, vault_unique_ids: List[str], jwt_token: str = None) -> Dict[str, Any]:
        """
        Check the status of embedding processing

        Args:
            vault_unique_ids: List of vault unique IDs to check

        Returns:
            Dict containing the status information
        """
        # Prepare payload
        payload = {"vault_unique_ids": vault_unique_ids}

        # Prepare headers - use JWT token if provided, otherwise fall back to ML_API_KEY
        auth_token = jwt_token if jwt_token else self.ml_api_key
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}" if auth_token else "",
        }

        # Construct full URL
        full_url = f"{self.ml_api_url}/api/v1/embedding/status"

        # Log ML API details BEFORE making the request
        logger.info("=" * 80)
        logger.info("🔍 ML API REQUEST - STATUS CHECK")
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
                response = await client.get(full_url, params=payload, headers=headers)

                # Log response details
                logger.info("=" * 80)
                logger.info("📥 ML API STATUS RESPONSE")
                logger.info("=" * 80)
                logger.info(f"📊 Status Code: {response.status_code}")
                logger.info(f"📋 Response Headers: {dict(response.headers)}")
                logger.info(f"📄 Response Body: {response.text}")
                logger.info("=" * 80)

                if response.status_code == 200:
                    try:
                        result = response.json()
                        logger.info(
                            f"✅ Successfully checked embedding status for {len(vault_unique_ids)} datasources"
                        )
                        logger.info(f"📊 ML API Status Data: {json.dumps(result, indent=2)}")
                        return {"success": True, "data": result}
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Failed to parse ML API status response as JSON: {e}")
                        return {
                            "success": False,
                            "message": "Invalid JSON response from ML API",
                            "error": f"JSON decode error: {e}",
                        }
                else:
                    logger.error(f"❌ ML API status check returned error: {response.status_code} - {response.text}")
                    return {
                        "success": False,
                        "message": f"ML API error: {response.status_code}",
                        "error": response.text,
                    }

        except Exception as e:
            logger.error("=" * 80)
            logger.error("💥 ML API STATUS CHECK ERROR")
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
                "message": "Failed to check embedding status",
                "error": str(e),
            }
