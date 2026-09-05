"""
POST /emailnotifysettings/test/trigger — trigger_daily_summary_scheduler_test
(mounted at /api/v1/notifications).

Grouped separately from the email-settings CRUD endpoints because it is a
thin manual-test hook for the daily summary scheduler, not a settings
resource operation.
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required

router = APIRouter()


@router.post("/emailnotifysettings/test/trigger")
async def trigger_daily_summary_scheduler_test(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Manually trigger the daily summary email scheduler for testing.

    This endpoint allows you to manually trigger the scheduler to test
    if emails are being sent correctly.
    """
    from app.services.daily_summary_scheduler import daily_summary_scheduler

    # Get current authenticated user (optional - for logging)
    try:
        current_user = await get_current_user_required(request)
        user_info = f"Triggered by user: {current_user.email_id}"
    except:
        user_info = "Triggered anonymously"

    try:
        if not daily_summary_scheduler.is_running:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Scheduler is not running"
            )

        # Manually trigger the process
        await daily_summary_scheduler.process_daily_summaries()

        return {
            "status": "success",
            "message": "Scheduler triggered manually - check logs for details",
            "triggered_by": user_info
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"❌ Error triggering scheduler: {error_traceback}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error triggering scheduler: {str(e)}"
        )
