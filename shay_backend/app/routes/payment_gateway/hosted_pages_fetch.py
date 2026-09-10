"""
Zoho hosted-page fetch-by-id endpoint (mounted at /api/v1/payment-gateway):
  GET /zoho/subscriptions/fetchByHostedId/{hostedPageId}  fetch_by_hosted_id

Split out of hosted_pages.py to keep each file under the ~150-line target.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, status, Request

from app.middleware.auth_middleware import get_current_user_required
from app.schemas.common import SuccessResponse
from app.services.zoho_service import get_zoho_service

router = APIRouter()


@router.get("/zoho/subscriptions/fetchByHostedId/{hostedPageId}", response_model=SuccessResponse[dict])
async def fetch_by_hosted_id(
    hostedPageId: str,
    request: Request,
    platform_name: Optional[str] = None
) -> SuccessResponse[dict]:
    """
    Retrieve hosted page data by hosted page ID.

    This endpoint fetches hosted page information from Zoho.

    Args:
        platform_name: Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration.
    """
    try:
        # Get current user for authentication
        user = await get_current_user_required(request)

        # Verify user is company admin
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only company admins can access hosted page data"
            )

        # Get appropriate Zoho service instance based on platform_name (for future Zoho API calls)
        zoho_service_instance = get_zoho_service(platform_name)

        # For now, return a placeholder response as per Node.js implementation
        # In a real implementation, this would fetch data from Zoho API using zoho_service_instance
        base_url = zoho_service_instance.base_url.replace('/billing/v1', '') if zoho_service_instance.base_url else 'https://zoho.com'
        hosted_page_data = {
            "hostedPageId": hostedPageId,
            "status": "active",
            "url": f"{base_url}/hosted-page/{hostedPageId}"
        }

        return SuccessResponse(
            success=True,
            data=hosted_page_data,
            message="Hosted page retrieved successfully",
            code=status.HTTP_200_OK
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve hosted page: {str(e)}"
        )
