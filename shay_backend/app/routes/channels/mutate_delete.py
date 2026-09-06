"""
DELETE /{channel_id} — delete_channel: cascading delete of a channel and all
related data.

Split out of mutate.py in wave B3 of the Raven style-compliance line-count
pass (see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) to bring mutate.py
under 150 lines; originally split out of app/routes/channels.py (2,630
lines) in Phase 5. The cascade-delete steps themselves were further split
out to mutate_delete_cascade.py to bring this file under 150 lines too.
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.services.audit_service import log as audit_log_write
from .helpers import validate_uuid
from .mutate_delete_cascade import cascade_delete_channel_data

router = APIRouter()


@router.delete("/{channel_id}")
async def delete_channel(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete channel and all related data"""
    user = await get_current_user_required(request, db)

    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")

    # Get channel
    stmt = select(Channel).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )

    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )

    try:
        await audit_log_write(db, user.id, "channel.deleted", "channel", channel_uuid, channel_id=channel_uuid)
        # Delete related records first (in order of dependencies), then the
        # channel itself.
        await cascade_delete_channel_data(db, channel, channel_uuid)

        # Commit all changes
        await db.commit()

        return {"message": "Channel and all related data deleted successfully"}

    except Exception as e:
        await db.rollback()
        print(f"Error during channel deletion: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting channel: {str(e)}"
        )
