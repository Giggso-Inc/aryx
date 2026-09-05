"""POST / — create a new approval request for a thread message."""

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import generate_approval_id
from app.core.config import settings
from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.approval import Approval
from app.models.channel_member import ChannelMember
from app.models.message import Message, Thread
from app.models.user import User
from app.schemas.approval import ApprovalCreate, ApprovalResponse
from app.services.audit_service import log as audit_log_write
from app.services.link_shortener_service import link_shortener_service

from .notifications_created_process import process_approval_notifications

router = APIRouter()


@router.post("/", response_model=ApprovalResponse)
async def create_approval(
    approval_data: ApprovalCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ApprovalResponse:
    """
    Create a new approval request for a thread message.

    This endpoint creates an approval request for a specific message in a thread.
    It automatically detects the thread_id from the message_id if not provided,
    and generates title/description if not specified.

    Args:
        approval_data (ApprovalCreate): The approval request data
        request (Request): FastAPI request object for authentication
        db (AsyncSession): Database session for data operations

    Returns:
        ApprovalResponse: The created approval with all details

    Raises:
        HTTPException: 404 if message/thread not found
        HTTPException: 400 if approver is not a channel member
        HTTPException: 409 if thread already has a pending approval
    """
    user = await get_current_user_required(request, db)

    # Get message first to determine thread_id if not provided
    message_stmt = select(Message).where(Message.id == approval_data.message_id)
    message_result = await db.execute(message_stmt)
    message = message_result.scalar_one_or_none()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )

    # Use provided thread_id or auto-detect from message
    thread_id = approval_data.thread_id or str(message.thread_id)

    # Validate thread exists and user has access
    thread_stmt = select(Thread).where(Thread.id == thread_id)
    thread_result = await db.execute(thread_stmt)
    thread = thread_result.scalar_one_or_none()

    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )

    # Validate message belongs to the thread
    if str(message.thread_id) != thread_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message does not belong to the specified thread"
        )

    # Validate approver is a channel member
    approver_member_stmt = select(ChannelMember).where(
        and_(
            ChannelMember.channel_id == thread.channel_id,
            ChannelMember.user_id == approval_data.approver_user_id,
            ChannelMember.is_active == True
        )
    )
    approver_member_result = await db.execute(approver_member_stmt)
    approver_member = approver_member_result.scalar_one_or_none()

    if not approver_member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Approver must be an active member of the channel"
        )

    # Check if there's already an active approval for this thread (via message IDs in thread)
    thread_msg_ids_stmt = select(Message.id).where(Message.thread_id == thread_id)
    thread_msg_ids_result = await db.execute(thread_msg_ids_stmt)
    thread_msg_ids = [row[0] for row in thread_msg_ids_result.all()]

    if thread_msg_ids:
        existing_approval_stmt = select(Approval).where(
            and_(
                Approval.message_id.in_(thread_msg_ids),
                Approval.is_active == "Y",
                Approval.status == "pending"
            )
        )
        existing_approval_result = await db.execute(existing_approval_stmt)
        existing_approval = existing_approval_result.scalar_one_or_none()

        if existing_approval:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="There is already a pending approval for this thread"
            )

    # Auto-generate title and description if not provided
    title = approval_data.title
    if not title:
        # Use first 50 characters of message content or default title
        message_preview = message.content[:50] + "..." if len(message.content) > 50 else message.content
        title = f"Approval for: {message_preview}"

    description = approval_data.description
    if not description:
        description = f"Approval request for message in thread: {thread.title or 'Untitled Thread'}"

    # Get approver user information for tracking
    approver_user_stmt = select(User).where(User.id == approval_data.approver_user_id)
    approver_user_result = await db.execute(approver_user_stmt)
    approver_user = approver_user_result.scalar_one_or_none()

    # channel_id resolved from thread for notifications (not stored on Approval)
    resolved_channel_id = thread.channel_id

    # Create approval (linked only via message_id; no channel_id/thread_id columns)
    current_time = datetime.now(timezone.utc).replace(tzinfo=None)
    approval = Approval(
        id=generate_approval_id(),
        message_id=approval_data.message_id,
        requested_by_user_id=user.id,  # Keep as UUID
        approver_user_id=approval_data.approver_user_id,  # Keep as UUID
        title=title,
        description=description,
        status="pending",
        is_active="Y",
        approval_metadata={
            'initial_assignment': {
                'assigned_to': str(approval_data.approver_user_id),
                'assigned_to_name': approver_user.name if approver_user else None,
                'assigned_by': str(user.id),
                'assigned_by_name': user.name if hasattr(user, 'name') else None,
                'assigned_at': current_time.isoformat(),
                'status': 'pending'
            }
        },
        created_at=current_time,
        updated_at=current_time
    )

    db.add(approval)
    await audit_log_write(db, user.id, "approval.created", "approval", approval.id, channel_id=thread.channel_id, thread_id=thread.id)
    await db.commit()
    await db.refresh(approval)

    # Process approval notifications in background
    if resolved_channel_id and approval.approver_user_id:
        # Use the canonical frontend root for real-time notifications.
        platform_url = settings.PLATFORM_URL

        # Construct redirect URL (shortened; store thread_id/channel_id for move-safe links)
        redirect_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{resolved_channel_id}/{thread_id}?openApproval=true", db,
            thread_id=thread_id, channel_id=resolved_channel_id, entity_type="approval",
        ) if platform_url else "#"
        # Construct notification settings URL (shortened; channel-level)
        notification_settings_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{resolved_channel_id}?openSettings=true&tab=notification", db,
            channel_id=resolved_channel_id, entity_type="channel",
        ) if platform_url else "#"

        background_tasks.add_task(
            process_approval_notifications,
            str(user.id),  # Approval creator ID
            str(approval.approver_user_id),  # Approver user ID
            str(resolved_channel_id),  # Channel ID
            redirect_url,  # Pre-constructed redirect URL
            notification_settings_url  # Pre-constructed notification settings URL
        )

    # Convert UUID fields to strings for the response
    return ApprovalResponse(
        id=str(approval.id),
        message_id=str(approval.message_id) if approval.message_id else None,
        requested_by_user_id=str(approval.requested_by_user_id) if approval.requested_by_user_id else None,
        approver_user_id=str(approval.approver_user_id) if approval.approver_user_id else None,
        status=approval.status,
        title=approval.title,
        description=approval.description,
        approval_notes=approval.approval_notes,
        rejection_reason=approval.rejection_reason,
        comment=approval.comment,
        is_active=approval.is_active,
        created_at=approval.created_at,
        updated_at=approval.updated_at,
        approved_at=approval.approved_at,
        rejected_at=approval.rejected_at
    )
