"""API-failure notification endpoint: POST /notify-api-failure."""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.services.email_service import email_service
from app.schemas.error_notification import (
    ErrorNotificationRequest,
    ErrorNotificationResponse,
)

router = APIRouter()


@router.post("/notify-api-failure", response_model=ErrorNotificationResponse)
async def notify_api_failure(
    error_notification: ErrorNotificationRequest,
    db: AsyncSession = Depends(get_db)
) -> ErrorNotificationResponse:
    """
    Send email notification to customer support when an API failure occurs

    This endpoint can be called from error handlers or when critical API failures
    are detected to notify the support team for investigation.
    """
    try:
        # Determine support email (request override, then env SUPPORT_EMAIL, then SMTP_FROM)
        support_email = error_notification.support_email or settings.SUPPORT_EMAIL or settings.SMTP_FROM

        # Use platform_name from request if provided, otherwise use config default
        platform_name = error_notification.platform_name or settings.PLATFORM_NAME

        # Prepare error data
        error_data = {
            'api_endpoint': error_notification.api_endpoint,
            'error_message': error_notification.error_message,
            'error_type': error_notification.error_type or 'Unknown Error',
            'user_id': error_notification.user_id or 'N/A',
            'company_id': error_notification.company_id or 'N/A',
            'request_method': error_notification.request_method or 'N/A',
            'request_body': error_notification.request_body or 'N/A',
            'stack_trace': error_notification.stack_trace or 'N/A',
            'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
            'platform_name': platform_name
        }

        # Send error notification email
        email_sent = email_service.send_error_notification_email(
            to_email=support_email,
            error_data=error_data,
            platform_url=settings.PLATFORM_URL
        )

        if email_sent:
            return ErrorNotificationResponse(
                success=True,
                message="Error notification email sent successfully to support team.",
                email_sent=True,
                support_email=support_email
            )
        else:
            return ErrorNotificationResponse(
                success=False,
                message="Failed to send error notification email. Please try again later.",
                email_sent=False,
                support_email=support_email
            )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send error notification: {str(e)}"
        )
