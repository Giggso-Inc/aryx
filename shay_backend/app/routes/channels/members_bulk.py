"""
POST /{channel_id}/members/bulk-csv — CSV bulk user addition endpoint.

Split out of the original app/routes/channels.py (2,630 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Stated exception: kept as one ~300-line file rather than split further.
The CSV parsing, per-row upsert loop, and the two email-notification
branches (Accsell/Zaptag vs. admin-notify) share the same request-scoped
state (channel, current_user, created_members/new_members lists) tightly
enough that splitting them into separate files would mean passing that
whole bundle of state across module boundaries for no real readability
gain — it is one coherent operation, not several unrelated ones.
"""

import csv
import io
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status, Request, Depends, Query, File, UploadFile
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import generate_channel_id
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.services.audit_service import log as audit_log_write
from app.services.email_service import email_service
from app.schemas.channel_member import ChannelMemberResponse, ChannelMemberList
from .helpers import validate_uuid, get_channel_admins

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

    # Validate file type
    if not csv_file.filename or not csv_file.filename.lower().endswith('.csv'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a CSV file"
        )

    # Read CSV file content
    try:
        csv_content = await csv_file.read()
        csv_text = csv_content.decode('utf-8')
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid CSV file content"
        )

    # Parse CSV content
    try:
        csv_reader = csv.DictReader(io.StringIO(csv_text))

        # Validate required columns
        if 'gmail_id' not in csv_reader.fieldnames or 'role' not in csv_reader.fieldnames:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSV must contain 'gmail_id' and 'role' columns"
            )

        # Read and validate CSV data
        csv_data = []
        for row_num, row in enumerate(csv_reader, start=2):  # Start from 2 since row 1 is headers
            gmail_id = row.get('gmail_id', '').strip()
            role = row.get('role', '').strip()

            if not gmail_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Row {row_num}: gmail_id cannot be empty"
                )

            if not role:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Row {row_num}: role cannot be empty"
                )

            # Convert to lowercase for comparison, but accept any case variation
            role_lower = role.lower()
            if role_lower not in ['user', 'admin']:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Row {row_num}: role must be 'User' or 'Admin' (case-insensitive), got '{role}'"
                )

            csv_data.append((gmail_id, role))

    except csv.Error as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid CSV format: {str(e)}"
        )

    if not csv_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV file is empty or contains no valid data"
        )

    # Process users and track results
    created_members: List[ChannelMember] = []
    new_members: List[ChannelMember] = []  # Track only newly created members (not updated existing ones)
    errors: List[str] = []
    already_members: List[str] = []

    for gmail_id, role in csv_data:
        try:
            # Find user by email_id (gmail_id)
            user_stmt = select(User).where(
                and_(
                    User.email_id == gmail_id,
                    User.company_id == channel.company_id,
                    User.is_active == True
                )
            )
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()

            if not user:
                # User doesn't exist in DB, return error as requested
                errors.append(f"Email ID '{gmail_id}' does not exist in the database")
                continue

            # User exists in DB, check if already in channel
            existing_stmt = select(ChannelMember).where(
                and_(
                    ChannelMember.channel_id == channel.id,
                    ChannelMember.user_id == user.id
                )
            )
            existing_result = await db.execute(existing_stmt)
            existing = existing_result.scalar_one_or_none()

            if existing:
                # User already in channel, update role if different
                if existing.role != role:
                    existing.role = role
                    existing.updated_at = datetime.utcnow()
                    created_members.append(existing)
                else:
                    already_members.append(f"User {gmail_id} already in channel with {role} role")
            else:
                # User exists but not in channel, add them (this is a NEW member)
                member = ChannelMember(
                    id=generate_channel_id(),
                    channel_id=channel.id,
                    user_id=user.id,
                    role=role,
                    permissions={},  # Default permissions
                    is_active=True,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(member)
                created_members.append(member)
                new_members.append(member)  # Track as new member for notifications

        except Exception as e:
            errors.append(f"Error processing user {gmail_id}: {str(e)}")
            continue

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

    # Email: Accsell/Zaptag → requirement flow only (each added user gets email with View Channel); others → previous flow (notify channel admins)
    if new_members:
        try:
            new_member_user_ids = [member.user_id for member in new_members]
            new_member_users_stmt = select(User).where(User.id.in_(new_member_user_ids))
            new_member_users_result = await db.execute(new_member_users_stmt)
            new_member_users = {u.id: u for u in new_member_users_result.scalars().all()}
            # [DEBUG] Log query param and resolved value for bulk add (platform_name from query)
            platform_name_value = platform_name or settings.PLATFORM_NAME
            platform_lower = str(platform_name_value or '').strip().lower()
            print(f"📧 [channel bulk-add] platform_name param={platform_name!r}, resolved={platform_name_value!r}, platform_lower={platform_lower!r}, branch={'accsell/zaptag (to added user)' if platform_lower in ('accsell', 'zaptag') else 'admin (to admins)'}, new_members_count={len(new_members)}")
            if platform_lower in ('accsell', 'zaptag'):
                # Accsell/Zaptag: requirement flow only - send to each added user with "You have been added" + View Channel button
                for member in new_members:
                    user = new_member_users.get(member.user_id)
                    if user:
                        notification_data_user = {
                            'channel_id': str(channel.id),
                            'channel_name': channel.name,
                            'user_name': user.name or user.email_id.split('@')[0],
                            'user_email': user.email_id,
                            'user_role': member.role,
                            'added_by': current_user.name or current_user.email_id.split('@')[0],
                            'platform_name': platform_name_value,
                            'send_to_added_user': True
                        }
                        # View Channel URL: use SHAY_PLATFORM_URL when platform is Accsell and set, else PLATFORM_URL
                        base_url = (settings.SHAY_PLATFORM_URL or settings.PLATFORM_URL) if platform_lower == 'accsell' else settings.PLATFORM_URL
                        # [DEBUG] Confirm payload before calling email service (bulk)
                        print(f"📧 [channel bulk-add] Sending to added user: to_emails=[{user.email_id}], send_to_added_user={notification_data_user.get('send_to_added_user')!r}, platform_url={base_url!r}")
                        email_sent_user = email_service.send_channel_member_notification(
                            to_emails=[user.email_id],
                            notification_data=notification_data_user,
                            platform_url=base_url
                        )
                        if email_sent_user:
                            print(f"✅ Channel member notification (added user) sent to {user.email_id}")
                        else:
                            print(f"⚠️ Channel member notification (added user) failed to send")
            else:
                # Previous flow: send email notifications to channel admins (unchanged for non-Accsell/Zaptag; no send_to_added_user)
                print(f"📧 Preparing to notify channel admins about {len(new_members)} new member(s)...")
                channel_admins = await get_channel_admins(channel.id, db)
                if channel_admins:
                    admin_emails = [admin.email_id for admin in channel_admins if admin.email_id]
                    if admin_emails:
                        for member in new_members:
                            user = new_member_users.get(member.user_id)
                            if user:
                                # Do not add send_to_added_user here; email_service uses its absence for admin subject/body
                                notification_data = {
                                    'channel_name': channel.name,
                                    'user_name': user.name or user.email_id.split('@')[0],
                                    'user_email': user.email_id,
                                    'user_role': member.role,
                                    'added_by': current_user.name or current_user.email_id.split('@')[0],
                                    'platform_name': platform_name_value
                                }
                                email_sent = email_service.send_channel_member_notification(
                                    to_emails=admin_emails,
                                    notification_data=notification_data,
                                    platform_url=settings.PLATFORM_URL
                                )
                                if email_sent:
                                    print(f"✅ Channel member notification emails sent for {user.email_id}")
                                else:
                                    print(f"⚠️ Failed to send channel member notification emails for {user.email_id}")
                else:
                    print(f"ℹ️ No channel admins found to notify")
        except Exception as email_error:
            # Log email error but don't fail the member addition
            print(f"⚠️ Error sending channel member notifications (non-critical): {email_error}")
            import traceback
            print(f"📋 Email error traceback: {traceback.format_exc()}")

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
