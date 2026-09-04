"""Zoho access-token retrieval for frontend use: GET /zoho/access-token."""

from typing import Optional
from fastapi import APIRouter, HTTPException, status
from app.schemas.common import SuccessResponse
from app.services.zoho_service import get_zoho_service

router = APIRouter()


@router.get("/zoho/access-token")
async def get_zoho_access_token(
    platform_name: Optional[str] = None
) -> SuccessResponse[dict]:
    """
    Get Zoho access token for frontend use.

    This endpoint provides Zoho access tokens for client-side operations.

    Args:
        platform_name: Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration.
    """
    try:
        # Get appropriate Zoho service instance based on platform_name
        zoho_service_instance = get_zoho_service(platform_name)

        # Use the service's configuration (supports prism7, accsell, zaptag env vars)
        if not zoho_service_instance.refresh_token:
            config_type = zoho_service_instance.get_config_var_name("ZOHO_REFRESH_TOKEN")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{config_type} environment variable is required"
            )
        if not zoho_service_instance.client_id:
            config_type = zoho_service_instance.get_config_var_name("ZOHO_CLIENT_ID")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{config_type} environment variable is required"
            )
        if not zoho_service_instance.client_secret:
            config_type = zoho_service_instance.get_config_var_name("ZOHO_CLIENT_SECRET")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{config_type} environment variable is required"
            )
        if not zoho_service_instance.token_url:
            config_type = zoho_service_instance.get_config_var_name("ZOHO_TOKEN_URL")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{config_type} environment variable is required"
            )

        # Get access token using the service's refresh_auth_token method
        access_token = await zoho_service_instance.refresh_auth_token()

        return SuccessResponse(
            success=True,
            data={
                "access_token": access_token,
                "token_type": "Bearer"
            },
            message="Zoho access token retrieved successfully",
            code=status.HTTP_200_OK
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get Zoho access token: {str(e)}"
        )
