"""
POST /zoho/webhook/subscription   zoho_subscription_webhook
(mounted at /api/v1/payment-gateway)
"""

import json
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status, Request

from app.schemas.common import SuccessResponse
from app.services.zoho_service import get_zoho_service

router = APIRouter()


@router.post("/zoho/webhook/subscription", response_model=SuccessResponse[dict])
async def zoho_subscription_webhook(
    webhook_data: Dict[str, Any],
    request: Request
) -> SuccessResponse[dict]:
    """
    Webhook endpoint for Zoho subscription updates.

    Called by Zoho when subscription status changes.
    Note: Webhooks come from Zoho, not from UI, so platform_name may not be in the request.
    If needed, platform_name can be determined from subscription data in the database.
    """
    try:
        # Extract platform_name from webhook_data if present (for future use)
        platform_name = webhook_data.get("platform_name")

        # Get appropriate Zoho service instance if platform_name is provided
        # (for future Zoho API calls if needed)
        if platform_name:
            zoho_service_instance = get_zoho_service(platform_name)

        # Verify webhook signature (implement proper verification)
        # For now, we'll just log the webhook data

        print(f"Zoho webhook received: {json.dumps(webhook_data, indent=2)}")
        if platform_name:
            print(f"Platform name from webhook: {platform_name}")

        # Process webhook data and update subscription status
        # This would typically involve:
        # 1. Verifying webhook signature
        # 2. Updating subscription status in database
        # 3. Sending notifications if needed

        return SuccessResponse(
            success=True,
            data={"webhook_processed": True},
            message="Webhook processed successfully",
            code=status.HTTP_200_OK
        )

    except Exception as e:
        print(f"Error processing Zoho webhook: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process webhook: {str(e)}"
        )
