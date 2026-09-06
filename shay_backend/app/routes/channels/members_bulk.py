"""
POST /{channel_id}/members/bulk-csv — CSV bulk user addition endpoint.

Split out of the original app/routes/channels.py (2,630 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5. Further split in
wave B2: CSV parsing/validation moved to members_bulk_csv.py, the per-row
upsert loop to members_bulk_upsert.py, and the email-notification branches
to members_bulk_notify.py. What remains here is the request orchestration
itself (auth, channel fetch, commit+audit, response assembly) — it still
owns the commit and the audit_log_write call so that the test's patch on
"app.routes.channels.members_bulk.audit_log_write" keeps working.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, status, Request, Depends, Query, File, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.services.audit_service import log as audit_log_write
# email_service is imported here (unused directly) so that
# tests/test_channels_characterization.py can patch
# "app.routes.channels.members_bulk.email_service.send_channel_member_notification" —
# it patches the attribute on the shared singleton object, which also takes
# effect for members_bulk_notify.py's own reference to the same object.
from app.services.email_service import email_service  # noqa: F401
from app.schemas.channel_member import ChannelMemberResponse, ChannelMemberList
from .helpers import validate_uuid
from .members_bulk_csv import parse_bulk_csv_file
from .members_bulk_upsert import upsert_members_from_csv
from .members_bulk_notify import send_bulk_add_notifications

router = APIRouter()


# CSV bulk user addition endpoint - adds multiple users by uploading CSV file with email addresses
@router.post("/{channel_id}/members/bulk-csv", response_model=ChannelMemberList)
async def add_channel_members_bulk_csv(
    channel_id: str,
    request: Request,
    csv_file: UploadFile = File(..., description="CSV file with gmail_id and role columns"),
    platform_name: Optional[str] = Query(None, description="Platform name for email notifications (optional, defaults to config value)"),
    db: AsyncSession = Depends(get_db),
) -> ChannelMemberList:
    """
    Grant access to multiple users for a channel by uploading a CSV file.

    This endpoint allows company admins or users with workspace management permissions to add multiple
    members to a channel by uploading a CSV file containing gmail_id and roles.

    CSV Format:
    gmail_id,role
    user1@gmail.com,Admin
    user2@gmail.com,User
    user3@gmail.com,User

    Required columns:
    - gmail_id: The Gmail address of the user
    - role: The role for the user in the channel (User or Admin, case-insensitive)

    The function will:
    1. Check if users already exist in the channel
    2. If users exist in DB but not in channel, add them directly
    3. If users don't exist in DB, return an error message

    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 13/08/2025
    """
    current_user = await get_current_user_required(request)

    # Validate channel_id as UUID
    channel_uuid = validate_uuid(channel_id, "channel ID")

    # Fetch channel
    stmt = select(Channel).where(Channel.id == channel_uuid)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    # Authorization: user must be company admin or able to manage within same company
    if not current_user.is_admin and str(current_user.company_id) != str(channel.company_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-company access denied")
    if not current_user.is_admin and not current_user.can_manage_workspace(str(channel.company_id)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    csv_data = await parse_bulk_csv_file(csv_file)

    # Process users and track results
    created_members, new_members, errors, already_members = await upsert_members_from_csv(
        db, channel, csv_data
    )

    # Commit all changes
    try:
        if created_members:
            await audit_log_write(db, current_user.id, "channel.members_bulk_added", "channel", channel.id, channel_id=channel.id, details={"count": len(created_members)})
        await db.commit()
        for member in created_members:
            await db.refresh(member)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error while adding members: {str(e)}"
        )

    await send_bulk_add_notifications(db, channel, current_user, new_members, platform_name)

    # Prepare response
    items = [
        ChannelMemberResponse(
            id=str(m.id),
            channel_id=str(m.channel_id),
            user_id=str(m.user_id),
            role=m.role,
            is_active=m.is_active,
        )
        for m in created_members
    ]

    # Build comprehensive response message
    response_parts = []
    if created_members:
        response_parts.append(f"Successfully added {len(created_members)} members to the channel")
    if already_members:
        response_parts.append(f"{len(already_members)} users were already channel members")
    if errors:
        response_parts.append(f"{len(errors)} errors occurred during processing")

    response_message = ". ".join(response_parts) if response_parts else "No actions taken"

    return ChannelMemberList(
        items=items,
        total=len(items),
        message=response_message,
        errors=errors if errors else None
    )
