"""
Message routes for thread and message management with AI integration
"""

import asyncio
import logging
import os
import re
from typing import List, Optional, Set
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_, text, bindparam, update

from app.core.database import get_db, AsyncSessionLocal
from app.core.auth import generate_message_id, generate_workspace_id
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.services.socket_client_service import get_socket_service
from app.services.file_storage import get_file_storage_service
from app.services.email_service import email_service
from app.models.user import User
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.app_account import AppAccount
from app.models.message import Message, Thread
from app.models.ai_response import AIResponse
from app.models.realtime_notification import RealtimeNotification
from app.schemas.message import (
    MessageCreate,
    MessageUpdate,
    MessageDelete,
    MessageResponse,
    ThreadCreate,
    ThreadUpdate,
    ThreadResponse,
    ThreadList,
    MessageList,
    ThreadSummary,
    UserBean,
    MLMessageRequest,
    MLMessageResponse,
    PhoneThreadRequest,
    PhoneThreadResponse,
    Citation,
    ThreadMoveRequest,
    ThreadMoveResponse,
    HideThreadMessagesResponse,
)
from app.models.approval import Approval
from app.models.task import Task
from app.models.attachment import Attachment
from app.models.email_attachment import EmailAttachment
from app.models.shortened_url import ShortenedUrl
from app.services.link_shortener_service import link_shortener_service
from sqlalchemy import update, or_
from sqlalchemy.sql import func as sa_func

logger = logging.getLogger(__name__)
router = APIRouter()


async def emit_message_created_event(channel_id: str, thread_id: str, message_id: str):
    """
    Emit message created socket event (type 11) - PURE EMISSION ONLY
    
    Args:
        channel_id: Channel ID where message was created
        thread_id: Thread ID where message was created  
        message_id: ID of the created message
    """
    try:
        socket_service = get_socket_service()
        if socket_service and socket_service.is_socket_connected():
            await socket_service.send_message_created_event(
                channel_id=channel_id,
                thread_id=thread_id,
                message_id=message_id
            )
        else:
            # Queue the event if socket is not connected
            from app.services.socket_event_handler import get_socket_event_handler
            event_handler = get_socket_event_handler()
            if event_handler:
                event_data = {
                    "type": 11,
                    "data": {
                        "channelId": channel_id,
                        "threadId": thread_id,
                        "messageId": message_id
                    }
                }
                event_handler.queue_event("shay_realtime", event_data)
    except Exception as e:
        print(f"Error emitting message created event: {e}")


async def emit_thread_created_event(channel_id: str, thread_id: str):
    """
    Emit thread created socket event (type 8) - PURE EMISSION ONLY
    
    Args:
        channel_id: Channel ID where thread was created
        thread_id: ID of the created thread
    """
    try:
        socket_service = get_socket_service()
        if socket_service and socket_service.is_socket_connected():
            await socket_service.send_thread_created_event(
                channel_id=channel_id,
                thread_id=thread_id
            )
        else:
            # Queue the event if socket is not connected
            from app.services.socket_event_handler import get_socket_event_handler
            event_handler = get_socket_event_handler()
            if event_handler:
                event_data = {
                    "type": 8,
                    "data": {
                        "channelId": channel_id,
                        "threadId": thread_id
                    }
                }
                event_handler.queue_event("shay_realtime", event_data)
    except Exception as e:
        print(f"Error emitting thread created event: {e}")


def parse_mentions_from_content(content: str) -> Set[str]:
    """
    Parse mentions from message content.
    Extracts @username patterns from the content.
    Mentions use user names, not emails.
    Handles formats like:
    - @username
    
    Args:
        content: Message content string
        
    Returns:
        Set of mentioned user names (without @ symbol)
    """
    if not content:
        return set()
    
    # Pattern to match @username
    # Matches @ followed by alphanumeric characters, dots, hyphens, underscores
    # We'll extract each @mention separately
    mention_pattern = r'@([a-zA-Z0-9._-]+)'
    mentions = re.findall(mention_pattern, content)
    
    # Return unique mentions as a set
    return set(mentions)


async def get_users_by_mentions(mentions: Set[str], db: AsyncSession) -> List[User]:
    """
    Find users by their name from mentions.
    Mentions in content use user names, not emails.
    
    Args:
        mentions: Set of mention identifiers (user names)
        db: Database session
        
    Returns:
        List of User objects that match the mentions (unique users only)
    """
    if not mentions:
        return []
    
    found_user_ids = set()  # Track found user IDs to avoid duplicates
    users = []
    
    for mention in mentions:
        # Find users by name (case-insensitive matching)
        # Try exact match first
        stmt = select(User).where(func.lower(User.name) == func.lower(mention))
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if user and user.id not in found_user_ids:
            users.append(user)
            found_user_ids.add(user.id)
            continue
        
        # If exact match not found, try partial match (contains)
        stmt = select(User).where(func.lower(User.name).contains(func.lower(mention)))
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if user and user.id not in found_user_ids:
            users.append(user)
            found_user_ids.add(user.id)
    
    return users


async def should_send_mention_notification(
    mentioned_user: User,
    channel_id: UUID,
    db: AsyncSession
) -> bool:
    """
    Check if mention notification should be sent to a user.
    
    Logic:
    1. If no data exists in gg_realtime_notification, send notification (default: mention enabled)
    2. If data exists:
       - Check is_notifications_enabled - if false, don't send
       - If true, check is_mention_enabled - if false, don't send
       - If both true, send notification
    
    Args:
        mentioned_user: User who was mentioned
        channel_id: Channel ID where the mention occurred
        db: Database session
        
    Returns:
        bool: True if notification should be sent, False otherwise
    """
    # Check if notification preferences exist for this user and channel
    stmt = select(RealtimeNotification).where(
        and_(
            RealtimeNotification.user_id == mentioned_user.id,
            RealtimeNotification.channel_id == channel_id
        )
    )
    result = await db.execute(stmt)
    notification_pref = result.scalar_one_or_none()
    
    # If no data exists, send notification (default behavior - mention is enabled)
    if not notification_pref:
        return True
    
    # If data exists, check the flags
    # First check master switch
    if not notification_pref.is_notifications_enabled:
        return False
    
    # Then check mention-specific flag
    if not notification_pref.is_mention_enabled:
        return False
    
    # Both flags are true, send notification
    return True


async def send_mention_notification_email(
    mentioned_user: User,
    comment_author: User,
    channel: Channel,
    comment_content: str,
    redirect_url: str,
    notification_settings_url: str,
    db: AsyncSession
) -> bool:
    """
    Send mention notification email to the mentioned user.
    
    Args:
        mentioned_user: User who was mentioned
        comment_author: User who posted the comment
        channel: Channel where the mention occurred
        comment_content: The comment content
        redirect_url: URL to redirect to view the message/thread
        notification_settings_url: URL to notification settings page
        db: Database session
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Load the mention notification template
        template = email_service._load_template('mention_notification.html')
        
        # Get platform name from config
        platform_name = settings.PLATFORM_NAME
        
        # Prepare template variables
        template_variables = {
            'user': comment_author.name or comment_author.email_id or 'Someone',
            'user_email': comment_author.email_id or '',
            'user_role': comment_author.role or 'user',
            'channel_name': channel.name or 'the channel',
            'comment': comment_content,
            'platform_name': platform_name,
            'redirect_url': redirect_url,
            'notification_settings_url': notification_settings_url,
            'current_year': datetime.now().year,
            'logo_html': email_service._get_embedded_logo_html(),
        }
        
        # Process template with variables
        processed_html = template.format(**template_variables)
        
        # Create email message (HTML only, no plain text)
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        msg = MIMEMultipart('alternative')
        msg['From'] = email_service.from_email
        msg['To'] = mentioned_user.email_id
        msg['Subject'] = f"{comment_author.name or 'Someone'} mentioned you in {channel.name or 'a channel'}"
        
        # Attach HTML version only (no plain text)
        msg.attach(MIMEText(processed_html, 'html'))
        
        # Send email
        result = email_service._send_email(msg)
        
        if result:
            print(f"✅ Mention notification email sent successfully to {mentioned_user.email_id}")
        else:
            print(f"❌ Failed to send mention notification email to {mentioned_user.email_id}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error sending mention notification email to {mentioned_user.email_id}: {e}")
        import traceback
        print(f"📋 Error traceback: {traceback.format_exc()}")
        return False


async def process_mention_notifications(
    content: str,
    comment_author_id: str,
    channel_id: str,
    redirect_url: str,
    notification_settings_url: str
) -> None:
    """
    Process mention notifications for a message.
    Parses mentions, checks notification preferences, and sends emails.
    This function creates its own database session for background processing.
    
    Args:
        content: Message content
        comment_author_id: UUID string of the user who posted the comment
        channel_id: UUID string of the channel where the message was posted
        redirect_url: Pre-constructed URL to redirect to view the message/thread
        notification_settings_url: Pre-constructed URL to notification settings page
    """
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get comment author
            author_stmt = select(User).where(User.id == UUID(comment_author_id))
            author_result = await db.execute(author_stmt)
            comment_author = author_result.scalar_one_or_none()
            
            if not comment_author:
                print(f"⚠️ Comment author not found: {comment_author_id}")
                return
            
            # Get channel
            channel_stmt = select(Channel).where(Channel.id == UUID(channel_id))
            channel_result = await db.execute(channel_stmt)
            channel = channel_result.scalar_one_or_none()
            
            if not channel:
                print(f"⚠️ Channel not found: {channel_id}")
                return
            
            # Parse mentions from content
            mentions = parse_mentions_from_content(content)
            
            if not mentions:
                return  # No mentions found
            
            # Get users by mentions
            mentioned_users = await get_users_by_mentions(mentions, db)
            
            if not mentioned_users:
                return  # No users found for mentions
            
            # Process each mentioned user
            for mentioned_user in mentioned_users:
                # Skip if user mentions themselves
                if mentioned_user.id == comment_author.id:
                    continue
                
                # Check if notification should be sent
                should_send = await should_send_mention_notification(
                    mentioned_user,
                    channel.id,
                    db
                )
                
                if should_send:
                    # Send notification email with pre-constructed URLs
                    await send_mention_notification_email(
                        mentioned_user,
                        comment_author,
                        channel,
                        content,
                        redirect_url,
                        notification_settings_url,
                        db
                    )
        
        except Exception as e:
            print(f"❌ Error processing mention notifications: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")


async def get_or_create_system_user(db: AsyncSession) -> User:
    """Get or create a system user for system messages"""
    # Check if system user exists
    stmt = select(User).where(User.email_id == settings.SYSTEM_USER_EMAIL)
    result = await db.execute(stmt)
    system_user = result.scalar_one_or_none()
    
    if not system_user:
        # Create system user if it doesn't exist
        from app.core.auth import generate_user_id
        
        system_user = User(
            id=generate_user_id(),
            name=settings.SYSTEM_USER_NAME,
            email_id=settings.SYSTEM_USER_EMAIL,
            role=settings.SYSTEM_USER_ROLE,
            is_active=True,
            is_verified=True,
            oauth_provider="system"
        )
        
        db.add(system_user)
        await db.commit()
        await db.refresh(system_user)
    
    return system_user


@router.post("/threads", response_model=ThreadResponse)
async def create_thread(
    thread_data: ThreadCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Create a new thread"""
    user = await get_current_user_required(request)
    
    # Get channel
    stmt = select(Channel).where(Channel.id == thread_data.channel_id)
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
    
    # Create thread
    thread = Thread(
        id=generate_workspace_id(),  # Reusing workspace ID generator for thread
        title=thread_data.title,
        description=thread_data.description,
        channel_id=thread_data.channel_id,
        ai_enabled=channel.ai_enabled  # Inherit AI settings from channel
    )
    
    db.add(thread)
    await audit_log_write(db, user.id, "thread.created", "thread", thread.id, channel_id=thread.channel_id, thread_id=thread.id)
    await db.commit()
    await db.refresh(thread)
    
    # Convert UUID fields to strings for response
    # Prepare response data
    response = ThreadResponse(
        id=str(thread.id),
        title=thread.title,
        description=thread.description,
        channel_id=str(thread.channel_id),
        is_active=thread.is_active,
        is_archived=thread.is_archived,
        message_count=thread.message_count,
        last_message_at=thread.last_message_at,
        ai_enabled=thread.ai_enabled,
        ai_summary=thread.ai_summary,
        created_at=thread.created_at,
        updated_at=thread.updated_at
    )
    
    # Emit socket event at the END - PURE EMISSION ONLY
    await emit_thread_created_event(
        channel_id=str(thread.channel_id),
        thread_id=str(thread.id)
    )
    
    return response


@router.post("/threads/by-phone", response_model=PhoneThreadResponse)
async def get_or_create_thread_by_phone(
    payload: PhoneThreadRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get or create a thread mapped to the provided phone number."""
    phone_number = payload.phone_number.strip()
    
    # Validate and convert UUIDs from request payload
    try:
        channel_id = UUID(payload.channel_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid channel_id format. Must be a valid UUID."
        ) from exc
    
    user = await get_current_user_required(request)
    
    # Get and validate channel
    stmt = select(Channel).where(Channel.id == channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found."
        )
    
    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel."
        )
    
    # Check if thread already exists
    stmt = select(Thread).where(
        and_(
            Thread.channel_id == channel_id,
            Thread.title == phone_number
        )
    )
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()
    
    if thread:
        return PhoneThreadResponse(
            thread_id=str(thread.id),
            phone_number=phone_number,
            is_new=False
        )
    
    # Create new thread
    thread = Thread(
        id=generate_workspace_id(),
        title=phone_number,
        description=None,
        channel_id=channel_id,
        ai_enabled=channel.ai_enabled
    )
    
    db.add(thread)
    await audit_log_write(db, user.id, "thread.created", "thread", thread.id, channel_id=thread.channel_id, thread_id=thread.id)
    await db.commit()
    await db.refresh(thread)
    
    await emit_thread_created_event(
        channel_id=str(thread.channel_id),
        thread_id=str(thread.id)
    )
    
    return PhoneThreadResponse(
        thread_id=str(thread.id),
        phone_number=phone_number,
        is_new=True
    )


@router.get("/threads", response_model=ThreadList)
async def list_threads(
    channel_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    is_archived: Optional[bool] = Query(False, description="Filter by archived status. True for archived threads, False for active threads"),
    sort_by: Optional[str] = Query("last_message_at", description="Sort by: created_at, updated_at, last_message_at, message_count"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc (ascending) or desc (descending)")
):
    """List threads in a channel
    
    Query Parameters:
    - channel_id: Required - ID of the channel
    - page: Page number (default: 1)
    - size: Page size (default: 10, max: 100)
    - search: Search by thread title
    - is_archived: Filter by archived status (default: false for active threads)
    - sort_by: last_message_at (default), created_at, updated_at, message_count
    - sort_order: asc (ascending) or desc (descending, default)
    """
    user = await get_current_user_required(request)
    
    # Get channel
    stmt = select(Channel).where(Channel.id == channel_id)
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
    
    # Build query
    query = select(Thread).where(Thread.channel_id == channel_id)
    
    # Add archived status filter
    query = query.where(Thread.is_archived == is_archived)
    
    # Add search filter
    if search:
        query = query.where(Thread.title.ilike(f"%{search}%"))
    
    # Add sorting
    if sort_by == "created_at":
        if sort_order.lower() == "asc":
            query = query.order_by(Thread.created_at.asc())
        else:
            query = query.order_by(Thread.created_at.desc())
    elif sort_by == "updated_at":
        if sort_order.lower() == "asc":
            query = query.order_by(Thread.updated_at.asc())
        else:
            query = query.order_by(Thread.updated_at.desc())
    elif sort_by == "last_message_at":
        if sort_order.lower() == "asc":
            query = query.order_by(func.coalesce(Thread.last_message_at, Thread.created_at).asc())
        else:
            query = query.order_by(func.coalesce(Thread.last_message_at, Thread.created_at).desc())
    elif sort_by == "message_count":
        if sort_order.lower() == "asc":
            query = query.order_by(Thread.message_count.asc())
        else:
            query = query.order_by(Thread.message_count.desc())
    else:  # Default: sort by last_message_at
        if sort_order.lower() == "asc":
            query = query.order_by(func.coalesce(Thread.last_message_at, Thread.created_at).asc())
        else:
            query = query.order_by(func.coalesce(Thread.last_message_at, Thread.created_at).desc())
    
    # Add pagination
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)
    
    # Execute query
    result = await db.execute(query)
    threads = result.scalars().all()
    
    # Get total count
    count_query = select(func.count(Thread.id)).where(Thread.channel_id == channel_id)
    
    # Add archived status filter to count query
    count_query = count_query.where(Thread.is_archived == is_archived)
    
    if search:
        count_query = count_query.where(Thread.title.ilike(f"%{search}%"))
    
    count_result = await db.execute(count_query)
    total = count_result.scalar()
    
    # Get first message ID for each thread
    thread_responses = []
    for thread in threads:
        # Get the first message in this thread (lowest sequence_number)
        first_message_query = select(Message.id).where(
            Message.thread_id == thread.id
        ).order_by(Message.sequence_number.asc()).limit(1)
        
        first_message_result = await db.execute(first_message_query)
        first_message = first_message_result.scalar_one_or_none()
        first_message_id = str(first_message) if first_message else None
        
        thread_response = ThreadResponse(
            id=str(thread.id),
            title=thread.title,
            description=thread.description,
            channel_id=str(thread.channel_id),
            is_active=thread.is_active,
            is_archived=thread.is_archived,
            message_count=thread.message_count,
            last_message_at=thread.last_message_at,
            ai_enabled=thread.ai_enabled,
            ai_summary=thread.ai_summary,
            first_message_id=first_message_id,
            created_at=thread.created_at,
            updated_at=thread.updated_at
        )
        thread_responses.append(thread_response)
    
    return ThreadList(
        threads=thread_responses,
        total=total,
        page=page,
        size=size
    )


@router.get("/threads/{thread_id}", response_model=ThreadResponse)
async def get_thread_details(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get thread details by thread ID"""
    user = await get_current_user_required(request)
    
    # Get thread
    stmt = select(Thread).where(Thread.id == thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )
    
    # Get channel
    stmt = select(Channel).where(Channel.id == thread.channel_id)
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
    
    # Get the first message in this thread (lowest sequence_number)
    first_message_query = select(Message.id).where(
        Message.thread_id == thread.id
    ).order_by(Message.sequence_number.asc()).limit(1)
    
    first_message_result = await db.execute(first_message_query)
    first_message = first_message_result.scalar_one_or_none()
    first_message_id = str(first_message) if first_message else None
    
    # Return thread details in the same structure as ThreadResponse
    return ThreadResponse(
        id=str(thread.id),
        title=thread.title,
        description=thread.description,
        channel_id=str(thread.channel_id),
        is_active=thread.is_active,
        is_archived=thread.is_archived,
        message_count=thread.message_count,
        last_message_at=thread.last_message_at,
        ai_enabled=thread.ai_enabled,
        ai_summary=thread.ai_summary,
        first_message_id=first_message_id,
        created_at=thread.created_at,
        updated_at=thread.updated_at
    )


@router.post("/", response_model=MessageResponse)
async def create_message(
    message_data: MessageCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new message and trigger AI processing.
    
    This endpoint creates a new message in a thread and can trigger AI processing based on
    the message type. It supports user messages, system messages, and AI responses.
    
    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 13/08/2025
    """
    user = await get_current_user_required(request)
    
    # Get thread
    stmt = select(Thread).where(Thread.id == message_data.thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )
    
    # Get channel
    stmt = select(Channel).where(Channel.id == thread.channel_id)
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
    
    # Get next sequence number
    seq_query = select(func.max(Message.sequence_number)).where(Message.thread_id == message_data.thread_id)
    seq_result = await db.execute(seq_query)
    max_seq = seq_result.scalar() or 0
    next_seq = max_seq + 1
    
    # Determine user_id and query_id based on message type
    user_id = user.id
    query_id = None
    
    if message_data.message_type == "system":
        # For system messages, use system user's ID and validate query_id
        system_user = await get_or_create_system_user(db)
        user_id = system_user.id
        
        if not message_data.query_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="query_id is required for system messages"
            )
        
        # Validate that the query message exists and is a user message
        query_stmt = select(Message).where(
            and_(
                Message.id == message_data.query_id,
                Message.thread_id == message_data.thread_id,
                Message.message_type == "user"
            )
        )
        query_result = await db.execute(query_stmt)
        query_message = query_result.scalar_one_or_none()
        
        if not query_message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Query message not found or invalid"
            )
        
        query_id = message_data.query_id
    
    # Convert attachment_ids to UUIDs if provided
    attachment_uuids = None
    if message_data.attachment_ids:
        from uuid import UUID as UUIDType
        try:
            attachment_uuids = [UUIDType(attachment_id) for attachment_id in message_data.attachment_ids]
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid attachment ID format: {str(e)}"
            )
    
    # Create message
    message = Message(
        id=generate_message_id(),
        content=message_data.content,
        message_type=message_data.message_type,
        thread_id=message_data.thread_id,
        user_id=user_id,
        query_id=query_id,
        sequence_number=next_seq,
        attachment_ids=attachment_uuids  # Store attachment_ids array in message
    )
    
    db.add(message)
    
    # Handle attachments if provided
    if message_data.attachment_ids:
        from app.models.attachment import Attachment
        from uuid import UUID as UUIDType
        
        # Validate and link attachments
        for attachment_id in message_data.attachment_ids:
            try:
                attachment_uuid = UUIDType(attachment_id)
                attachment_stmt = select(Attachment).where(
                    and_(
                        Attachment.id == attachment_uuid,
                        Attachment.channel_id == thread.channel_id,
                        Attachment.user_id == user_id  # Ensure user owns the attachment
                    )
                )
                attachment_result = await db.execute(attachment_stmt)
                attachment = attachment_result.scalar_one_or_none()
                
                if attachment:
                    # Link attachment to message
                    attachment.message_id = message.id
                else:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Attachment {attachment_id} not found or access denied"
                    )
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid attachment ID format: {attachment_id}"
                )
    
    # Update thread metadata
    thread.message_count += 1
    thread.last_message_at = datetime.utcnow()
    
    # Update channel metadata
    channel.message_count += 1
    channel.last_message_at = datetime.utcnow()
    await audit_log_write(db, user.id, "message.created", "message", message.id, channel_id=thread.channel_id, thread_id=message.thread_id, details={"message_type": message_data.message_type})
    await db.commit()
    await db.refresh(message)
    
    # Trigger AI processing if enabled
    if channel.ai_enabled and thread.ai_enabled and message_data.message_type == "user":
        background_tasks.add_task(trigger_ai_processing, message.id)
    
    # Process mention notifications for user messages only
    if message_data.message_type == "user" and message_data.content:
        # Get platform URL from environment variables for real-time notifications
        platform_url = os.environ.get("PLATFORM_URL") or settings.PLATFORM_URL
        
        # Construct redirect URL to view the thread (shortened; store thread_id/channel_id for move-safe links)
        redirect_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{channel.id}", db,
            thread_id=thread.id, channel_id=channel.id, entity_type="mention",
        ) if platform_url else "#"
        # Construct notification settings URL (shortened; channel-level)
        notification_settings_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{channel.id}?openSettings=true&tab=notification", db,
            channel_id=channel.id, entity_type="channel",
        ) if platform_url else "#"
        
        # Process mentions in background to avoid blocking the response
        background_tasks.add_task(
            process_mention_notifications,
            message_data.content,
            str(user.id),  # The user ID who posted the comment
            str(channel.id),  # The channel ID where the message was posted
            redirect_url,  # Pre-constructed redirect URL
            notification_settings_url  # Pre-constructed notification settings URL
        )
    
    # Get user details for the message
    user_details = None
    if message.user_id:
        user_stmt = select(User).where(User.id == message.user_id)
        user_result = await db.execute(user_stmt)
        user_obj = user_result.scalar_one_or_none()
        if user_obj:
            user_details = UserBean(
                id=str(user_obj.id),
                email=user_obj.email_id,
                name=user_obj.name,
                role=user_obj.role,
                avatar_url=user_obj.avatar_url
            )
    
    # Get attachment details for the message
    attachment_details = []
    if message_data.attachment_ids:
        from app.schemas.message import AttachmentDetails
        
        attachment_stmt = select(Attachment).where(Attachment.message_id == message.id)
        attachment_result = await db.execute(attachment_stmt)
        attachments = attachment_result.scalars().all()
        
        for attachment in attachments:
            attachment_details.append(AttachmentDetails(
                id=str(attachment.id),
                filename=attachment.filename,
                original_filename=attachment.original_filename,
                file_size=attachment.file_size,
                mime_type=attachment.mime_type,
                file_extension=attachment.file_extension,
                storage_url=attachment.storage_url,
                is_public=attachment.is_public,
                is_processed=attachment.is_processed,
                processing_status=attachment.processing_status,
                content_summary=attachment.content_summary,
                created_at=attachment.created_at
            ))
    
    # Prepare response data
    response = MessageResponse(
        id=str(message.id),
        content=message.content,
        message_type=message.message_type,
        thread_id=str(message.thread_id),
        channel_id=str(thread.channel_id),
        user_id=str(message.user_id) if message.user_id else None,
        query_id=str(message.query_id) if message.query_id else None,
        userBean=user_details,
        is_ai_processed=message.is_ai_processed,
        ai_provider=message.ai_provider,
        ai_model=message.ai_model,
        ai_processing_time=message.ai_processing_time,
        is_visible=message.is_visible,
        is_pinned=message.is_pinned,
        sequence_number=message.sequence_number,
        attachment_ids=[str(aid) for aid in message.attachment_ids] if message.attachment_ids else None,
        attachments=attachment_details if attachment_details else None,
        citations=[Citation(name=c["name"], type=c["type"]) for c in message.citations] if message.citations else None,
        usage_metrics=message.usage_metrics,
        created_at=message.created_at,
        updated_at=message.updated_at
    )

    # Emit socket event at the END - PURE EMISSION ONLY
    await emit_message_created_event(
        channel_id=str(thread.channel_id),
        thread_id=str(message.thread_id),
        message_id=str(message.id)
    )

    return response


@router.get("/{thread_id}", response_model=MessageList)
async def get_thread_messages(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100)
):
    """Get messages in a thread"""
    user = await get_current_user_required(request)
    
    # Get thread
    stmt = select(Thread).where(Thread.id == thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )
    
    # Get channel
    stmt = select(Channel).where(Channel.id == thread.channel_id)
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
    
    # Get messages
    query = select(Message).where(Message.thread_id == thread_id)
    offset = (page - 1) * size
    query = query.offset(offset).limit(size).order_by(Message.sequence_number)
    
    result = await db.execute(query)
    messages = result.scalars().all()
    
    # Get total count
    count_query = select(func.count(Message.id)).where(Message.thread_id == thread_id)
    count_result = await db.execute(count_query)
    total = count_result.scalar()
    
    # Get user details for all messages
    user_ids = [m.user_id for m in messages if m.user_id]
    users = {}
    if user_ids:
        user_stmt = select(User).where(User.id.in_(user_ids))
        user_result = await db.execute(user_stmt)
        user_list = user_result.scalars().all()
        users = {str(u.id): u for u in user_list}
    
    # Get attachment details for all messages
    message_ids = [str(m.id) for m in messages]
    attachments_by_message = {}
    if message_ids:
        from app.models.attachment import Attachment
        from app.schemas.message import AttachmentDetails
        
        attachment_stmt = select(Attachment).where(Attachment.message_id.in_(message_ids))
        attachment_result = await db.execute(attachment_stmt)
        attachments = attachment_result.scalars().all()
        
        for attachment in attachments:
            message_id = str(attachment.message_id)
            if message_id not in attachments_by_message:
                attachments_by_message[message_id] = []
            
            attachments_by_message[message_id].append(AttachmentDetails(
                id=str(attachment.id),
                filename=attachment.filename,
                original_filename=attachment.original_filename,
                file_size=attachment.file_size,
                mime_type=attachment.mime_type,
                file_extension=attachment.file_extension,
                storage_url=attachment.storage_url,
                is_public=attachment.is_public,
                is_processed=attachment.is_processed,
                processing_status=attachment.processing_status,
                content_summary=attachment.content_summary,
                created_at=attachment.created_at
            ))
    
    return MessageList(
        messages=[
            MessageResponse(
                id=str(m.id),
                content=m.content,
                message_type=m.message_type,
                thread_id=str(m.thread_id),
                channel_id=str(thread.channel_id),
                user_id=str(m.user_id) if m.user_id else None,
                query_id=str(m.query_id) if m.query_id else None,
                userBean=UserBean(
                    id=str(m.user_id),
                    email=users.get(str(m.user_id)).email_id if m.user_id and users.get(str(m.user_id)) else None,
                    name=users.get(str(m.user_id)).name if m.user_id and users.get(str(m.user_id)) else None,
                    role=users.get(str(m.user_id)).role if m.user_id and users.get(str(m.user_id)) else None,
                    avatar_url=users.get(str(m.user_id)).avatar_url if m.user_id and users.get(str(m.user_id)) else None
                ) if m.user_id and users.get(str(m.user_id)) else None,
                is_ai_processed=m.is_ai_processed,
                ai_provider=m.ai_provider,
                ai_model=m.ai_model,
                ai_processing_time=m.ai_processing_time,
                is_visible=m.is_visible,
                is_pinned=m.is_pinned,
                sequence_number=m.sequence_number,
                attachment_ids=[str(aid) for aid in m.attachment_ids] if m.attachment_ids else None,
                attachments=attachments_by_message.get(str(m.id), None),
                citations=[Citation(name=c["name"], type=c["type"]) for c in m.citations] if m.citations else None,
                usage_metrics=m.usage_metrics,
                created_at=m.created_at,
                updated_at=m.updated_at
            ) for m in messages
        ],
        total=total,
        page=page,
        size=size
    )


@router.post(
    "/message/{message_id}/hide",
    response_model=HideThreadMessagesResponse,
)
async def hide_thread_messages(
    message_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Hide a message (soft-hide: sets is_visible=false). Channel and thread are derived from the message.
    When all messages in a thread are hidden, the thread can be hidden by the caller/other service.
    """
    user = await get_current_user_required(request)
    try:
        message_uuid = UUID(message_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid message_id format",
        )
    # Fetch message and derive channel via thread
    msg_stmt = select(Message).where(Message.id == message_uuid)
    msg_result = await db.execute(msg_stmt)
    message = msg_result.scalar_one_or_none()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )
    thread_stmt = select(Thread).where(Thread.id == message.thread_id)
    thread_result = await db.execute(thread_stmt)
    msg_thread = thread_result.scalar_one_or_none()
    channel_stmt = select(Channel).where(Channel.id == msg_thread.channel_id) if msg_thread else None
    if channel_stmt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found",
        )
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found",
        )
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel",
        )
    now = datetime.utcnow()
    stmt = (
        update(Message)
        .where(Message.id == message_uuid)
        .values(is_visible=False, updated_at=now)
    )
    result = await db.execute(stmt)
    hidden_count = result.rowcount
    await audit_log_write(db, user.id, "message.hidden", "message", message_uuid, channel_id=message.channel_id, thread_id=message.thread_id)
    await db.commit()
    return HideThreadMessagesResponse(
        success=True,
        message="Message hidden",
        hidden_count=hidden_count,
        message_id=message_id,
    )


@router.get("/message/{message_id}", response_model=MessageResponse)
async def get_message_details(
    message_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get message details by message ID"""
    user = await get_current_user_required(request)
    
    # Get message
    stmt = select(Message).where(Message.id == message_id)
    result = await db.execute(stmt)
    message = result.scalar_one_or_none()
    
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )
    
    # Get thread
    stmt = select(Thread).where(Thread.id == message.thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )
    
    # Get channel
    stmt = select(Channel).where(Channel.id == thread.channel_id)
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
    
    # Get user details for the message
    user_details = None
    if message.user_id:
        user_stmt = select(User).where(User.id == message.user_id)
        user_result = await db.execute(user_stmt)
        user_obj = user_result.scalar_one_or_none()
        if user_obj:
            user_details = UserBean(
                id=str(user_obj.id),
                email=user_obj.email_id,
                name=user_obj.name,
                role=user_obj.role,
                avatar_url=user_obj.avatar_url
            )
    
    # Get attachment details for the message
    attachment_details = []
    if message.attachment_ids:
        from app.models.attachment import Attachment
        from app.schemas.message import AttachmentDetails
        
        attachment_stmt = select(Attachment).where(Attachment.message_id == message.id)
        attachment_result = await db.execute(attachment_stmt)
        attachments = attachment_result.scalars().all()
        
        for attachment in attachments:
            attachment_details.append(AttachmentDetails(
                id=str(attachment.id),
                filename=attachment.filename,
                original_filename=attachment.original_filename,
                file_size=attachment.file_size,
                mime_type=attachment.mime_type,
                file_extension=attachment.file_extension,
                storage_url=attachment.storage_url,
                is_public=attachment.is_public,
                is_processed=attachment.is_processed,
                processing_status=attachment.processing_status,
                content_summary=attachment.content_summary,
                created_at=attachment.created_at
            ))
    
    # Return message details in the same structure as MessageResponse (include citations and usage_metrics from DB)
    return MessageResponse(
        id=str(message.id),
        content=message.content,
        message_type=message.message_type,
        thread_id=str(message.thread_id),
        channel_id=str(thread.channel_id),
        user_id=str(message.user_id) if message.user_id else None,
        query_id=str(message.query_id) if message.query_id else None,
        userBean=user_details,
        is_ai_processed=message.is_ai_processed,
        ai_provider=message.ai_provider,
        ai_model=message.ai_model,
        ai_processing_time=message.ai_processing_time,
        is_visible=message.is_visible,
        is_pinned=message.is_pinned,
        sequence_number=message.sequence_number,
        attachment_ids=[str(aid) for aid in message.attachment_ids] if message.attachment_ids else None,
        attachments=attachment_details if attachment_details else None,
        citations=[Citation(name=c["name"], type=c["type"]) for c in message.citations] if message.citations else None,
        usage_metrics=message.usage_metrics,
        created_at=message.created_at,
        updated_at=message.updated_at
    )


@router.post("/update", response_model=MessageResponse)
async def update_message(
    message_update: MessageUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Update an existing message (internal comment).
    
    This endpoint allows updating message content, message type, and attachments.
    It handles both scenarios: with attachments and without attachments.
    
    Author: System
    Version: 1.0.0
    """
    user = await get_current_user_required(request)
    
    # Validate message_id and thread_id
    try:
        message_uuid = UUID(message_update.message_id)
        thread_uuid = UUID(message_update.thread_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid message_id or thread_id format"
        )
    
    # Get message
    stmt = select(Message).where(Message.id == message_uuid)
    result = await db.execute(stmt)
    message = result.scalar_one_or_none()
    
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )
    
    # Validate message belongs to the specified thread
    if message.thread_id != thread_uuid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message does not belong to the specified thread"
        )
    
    # Get thread
    stmt = select(Thread).where(Thread.id == thread_uuid)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )
    
    # Get channel
    stmt = select(Channel).where(Channel.id == thread.channel_id)
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
    
    # Check if user can edit this message (only the creator or admin can edit)
    if message.user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only edit your own messages"
        )
    
    # Update message content and type
    message.content = message_update.content
    message.message_type = message_update.message_type
    
    # Update optional fields if provided
    if message_update.is_visible is not None:
        message.is_visible = message_update.is_visible
    if message_update.is_pinned is not None:
        message.is_pinned = message_update.is_pinned
    
    # Handle attachments
    from app.models.attachment import Attachment
    from uuid import UUID as UUIDType
    from app.schemas.message import AttachmentDetails
    
    # Get current attachments
    current_attachment_ids = set(message.attachment_ids) if message.attachment_ids else set()
    
    # Process new attachment_ids
    new_attachment_uuids = []
    if message_update.attachment_ids is not None:
        # Convert string IDs to UUIDs
        for attachment_id in message_update.attachment_ids:
            try:
                attachment_uuid = UUIDType(attachment_id)
                new_attachment_uuids.append(attachment_uuid)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid attachment ID format: {attachment_id}"
                )
        
        # Validate and link new attachments
        new_attachment_ids_set = set(new_attachment_uuids)
        for attachment_uuid in new_attachment_uuids:
            attachment_stmt = select(Attachment).where(
                and_(
                    Attachment.id == attachment_uuid,
                    Attachment.channel_id == thread.channel_id,
                    Attachment.user_id == user.id  # Ensure user owns the attachment
                )
            )
            attachment_result = await db.execute(attachment_stmt)
            attachment = attachment_result.scalar_one_or_none()
            
            if not attachment:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Attachment {attachment_uuid} not found or access denied"
                )
            
            # Link attachment to message
            attachment.message_id = message.id
        
        # Unlink attachments that are no longer in the list
        attachments_to_unlink = current_attachment_ids - new_attachment_ids_set
        if attachments_to_unlink:
            unlink_stmt = select(Attachment).where(
                and_(
                    Attachment.id.in_(attachments_to_unlink),
                    Attachment.message_id == message.id
                )
            )
            unlink_result = await db.execute(unlink_stmt)
            attachments_to_remove = unlink_result.scalars().all()
            for attachment in attachments_to_remove:
                attachment.message_id = None
        
        # Update message.attachment_ids array
        # Empty list means remove all attachments, use None for empty array in database
        message.attachment_ids = new_attachment_uuids if new_attachment_uuids else None
    # If attachment_ids is None (not provided in request), don't change existing attachments
    
    # Update timestamp
    message.updated_at = datetime.utcnow()
    await audit_log_write(db, user.id, "message.updated", "message", message.id, channel_id=message.channel_id, thread_id=message.thread_id)
    await db.commit()
    await db.refresh(message)
    
    # Get user details for the message
    user_details = None
    if message.user_id:
        user_stmt = select(User).where(User.id == message.user_id)
        user_result = await db.execute(user_stmt)
        user_obj = user_result.scalar_one_or_none()
        if user_obj:
            user_details = UserBean(
                id=str(user_obj.id),
                email=user_obj.email_id,
                name=user_obj.name,
                role=user_obj.role,
                avatar_url=user_obj.avatar_url
            )
    
    # Get attachment details for the message
    attachment_details = []
    if message.attachment_ids:
        attachment_stmt = select(Attachment).where(Attachment.message_id == message.id)
        attachment_result = await db.execute(attachment_stmt)
        attachments = attachment_result.scalars().all()
        
        for attachment in attachments:
            attachment_details.append(AttachmentDetails(
                id=str(attachment.id),
                filename=attachment.filename,
                original_filename=attachment.original_filename,
                file_size=attachment.file_size,
                mime_type=attachment.mime_type,
                file_extension=attachment.file_extension,
                storage_url=attachment.storage_url,
                is_public=attachment.is_public,
                is_processed=attachment.is_processed,
                processing_status=attachment.processing_status,
                content_summary=attachment.content_summary,
                created_at=attachment.created_at
            ))
    
    # Prepare response data
    response = MessageResponse(
        id=str(message.id),
        content=message.content,
        message_type=message.message_type,
        thread_id=str(message.thread_id),
        channel_id=str(thread.channel_id),
        user_id=str(message.user_id) if message.user_id else None,
        query_id=str(message.query_id) if message.query_id else None,
        userBean=user_details,
        is_ai_processed=message.is_ai_processed,
        ai_provider=message.ai_provider,
        ai_model=message.ai_model,
        ai_processing_time=message.ai_processing_time,
        is_visible=message.is_visible,
        is_pinned=message.is_pinned,
        sequence_number=message.sequence_number,
        attachment_ids=[str(aid) for aid in message.attachment_ids] if message.attachment_ids else None,
        attachments=attachment_details if attachment_details else None,
        citations=[Citation(name=c["name"], type=c["type"]) for c in message.citations] if message.citations else None,
        usage_metrics=message.usage_metrics,
        created_at=message.created_at,
        updated_at=message.updated_at
    )

    # Emit socket event for message update
    await emit_message_created_event(
        channel_id=str(thread.channel_id),
        thread_id=str(message.thread_id),
        message_id=str(message.id)
    )

    return response


@router.delete("/delete", response_model=dict)
async def delete_message(
    message_delete: MessageDelete,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete an existing message (internal comment).
    
    This endpoint deletes a message and handles cleanup:
    - Unlinks attachments from the message
    - Deletes associated AI responses
    - Updates thread and channel message counts
    
    Author: System
    Version: 1.0.0
    """
    user = await get_current_user_required(request)
    
    # Validate message_id and thread_id
    try:
        message_uuid = UUID(message_delete.message_id)
        thread_uuid = UUID(message_delete.thread_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid message_id or thread_id format"
        )
    
    # Get message
    stmt = select(Message).where(Message.id == message_uuid)
    result = await db.execute(stmt)
    message = result.scalar_one_or_none()
    
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )
    
    # Validate message belongs to the specified thread
    if message.thread_id != thread_uuid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message does not belong to the specified thread"
        )
    
    # Get thread
    stmt = select(Thread).where(Thread.id == thread_uuid)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )
    
    # Get channel
    stmt = select(Channel).where(Channel.id == thread.channel_id)
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
    
    # Check if user can delete this message (only the creator or admin can delete)
    if message.user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own messages"
        )
    
    from app.models.attachment import Attachment
    
    # Find and delete any messages that reference this message as query_id (e.g. AI responses in gg_messages)
    dependent_stmt = select(Message).where(Message.query_id == message.id)
    dependent_result = await db.execute(dependent_stmt)
    dependent_messages = dependent_result.scalars().all()
    
    deleted_attachments_count = 0
    deleted_dependent_ai_count = 0
    for dep_msg in dependent_messages:
        # Unlink attachments from dependent message
        if dep_msg.attachment_ids:
            dep_att_stmt = select(Attachment).where(Attachment.message_id == dep_msg.id)
            dep_att_result = await db.execute(dep_att_stmt)
            dep_attachments = dep_att_result.scalars().all()
            for att in dep_attachments:
                try:
                    storage_service = get_file_storage_service()
                    await storage_service.delete_file(att.file_path)
                    deleted_attachments_count += 1
                except Exception:
                    pass
                att.message_id = None
        # Delete AI responses for this dependent message
        dep_ai_stmt = select(AIResponse).where(AIResponse.message_id == dep_msg.id)
        dep_ai_result = await db.execute(dep_ai_stmt)
        dep_ai = dep_ai_result.scalars().all()
        for ai in dep_ai:
            await db.delete(ai)
            deleted_dependent_ai_count += 1
        await db.delete(dep_msg)
    
    # Delete attachments from S3 and unlink from the main message
    if message.attachment_ids:
        attachment_stmt = select(Attachment).where(Attachment.message_id == message.id)
        attachment_result = await db.execute(attachment_stmt)
        attachments = attachment_result.scalars().all()
        
        # Delete files from S3/storage
        storage_service = get_file_storage_service()
        for attachment in attachments:
            try:
                # Delete file from S3/storage
                print(f"Attempting to delete file from storage: {attachment.file_path}")
                print(f"Storage provider: {storage_service.provider.__class__.__name__}")
                result = await storage_service.delete_file(attachment.file_path)
                if result:
                    deleted_attachments_count += 1
                    print(f"Successfully deleted file: {attachment.file_path}")
                else:
                    print(f"Failed to delete file (returned False): {attachment.file_path}")
            except Exception as e:
                print(f"Failed to delete file {attachment.file_path} from storage: {e}")
                import traceback
                traceback.print_exc()
                # Continue with unlinking even if S3 deletion fails
            
            # Unlink attachment from message
            attachment.message_id = None
    
    # Delete AI responses associated with this message
    ai_responses_stmt = select(AIResponse).where(AIResponse.message_id == message.id)
    ai_responses_result = await db.execute(ai_responses_stmt)
    ai_responses = ai_responses_result.scalars().all()
    
    for ai_response in ai_responses:
        await db.delete(ai_response)
    
    await audit_log_write(db, user.id, "message.deleted", "message", message.id, channel_id=message.channel_id, thread_id=message.thread_id)
    # Delete the main message
    await db.delete(message)
    
    # Update thread metadata (decrease message count: main message + any dependent messages with query_id = this message)
    total_deleted = 1 + len(dependent_messages)
    if thread.message_count >= total_deleted:
        thread.message_count -= total_deleted
    else:
        thread.message_count = 0
    
    # Update last_message_at if this was the last message
    last_message_query = select(Message).where(Message.thread_id == thread_uuid).order_by(Message.sequence_number.desc()).limit(1)
    last_message_result = await db.execute(last_message_query)
    last_message = last_message_result.scalar_one_or_none()
    
    if last_message:
        thread.last_message_at = last_message.created_at
    else:
        thread.last_message_at = None
    
    # Update channel metadata (decrease message count by total deleted: main + dependents)
    if channel.message_count >= total_deleted:
        channel.message_count -= total_deleted
    else:
        channel.message_count = 0
    
    # Update channel last_message_at
    channel_last_message_query = select(Message).where(Message.thread_id.in_(
        select(Thread.id).where(Thread.channel_id == channel.id)
    )).order_by(Message.created_at.desc()).limit(1)
    channel_last_message_result = await db.execute(channel_last_message_query)
    channel_last_message = channel_last_message_result.scalar_one_or_none()

    if channel_last_message:
        channel.last_message_at = channel_last_message.created_at
    else:
        channel.last_message_at = None

    # Store IDs before deletion for socket event
    channel_id_str = str(thread.channel_id)
    thread_id_str = str(message.thread_id)
    message_id_str = str(message.id)
    
    await db.commit()
    
    # Emit socket event for message deletion
    await emit_message_created_event(
        channel_id=channel_id_str,
        thread_id=thread_id_str,
        message_id=message_id_str
    )
    
    return {
        "message": "Message deleted successfully",
        "message_id": message_delete.message_id,
        "thread_id": message_delete.thread_id,
        "deleted_attachments": deleted_attachments_count,
        "deleted_ai_responses": len(ai_responses) + deleted_dependent_ai_count,
        "deleted_query_id_messages": len(dependent_messages),
    }


@router.get("/threads/{thread_id}/summary", response_model=ThreadSummary)
async def get_thread_summary(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get thread summary"""
    user = await get_current_user_required(request)
    
    # Get thread
    stmt = select(Thread).where(Thread.id == thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )
    
    # Get channel
    stmt = select(Channel).where(Channel.id == thread.channel_id)
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
    
    return ThreadSummary(
        thread_id=thread.id,
        title=thread.title,
        message_count=thread.message_count,
        last_message_at=thread.last_message_at,
        ai_summary=thread.ai_summary,
        created_at=thread.created_at
    )


@router.put("/threads/{thread_id}", response_model=ThreadResponse)
async def update_thread(
    thread_id: str,
    thread_update: ThreadUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Update a thread"""
    user = await get_current_user_required(request)
    
    # Get thread
    stmt = select(Thread).where(Thread.id == thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )
    
    # Get channel
    stmt = select(Channel).where(Channel.id == thread.channel_id)
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
    
    # Update thread fields
    if thread_update.title is not None:
        thread.title = thread_update.title
    if thread_update.description is not None:
        thread.description = thread_update.description
    if thread_update.is_active is not None:
        thread.is_active = thread_update.is_active
    if thread_update.is_archived is not None:
        thread.is_archived = thread_update.is_archived
    if thread_update.ai_enabled is not None:
        thread.ai_enabled = thread_update.ai_enabled
    if thread_update.ai_summary is not None:
        thread.ai_summary = thread_update.ai_summary
    
    # Update timestamp
    thread.updated_at = datetime.utcnow()
    await audit_log_write(db, user.id, "thread.updated", "thread", thread.id, channel_id=thread.channel_id, thread_id=thread.id)
    await db.commit()
    await db.refresh(thread)
    
    return ThreadResponse.from_orm(thread)


@router.post("/threads/move", response_model=ThreadMoveResponse)
async def move_thread(
    payload: ThreadMoveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Move a thread from one regular channel to another. Both channels must be
    message-type; validations include same workspace and active thread.
    """
    # Require authenticated user (avoids Depends(get_current_user) which triggers FastAPI response-field error on AsyncSession)
    user = await get_current_user_required(request, db)

    thread_id = payload.thread_id

    # A. Load and validate the thread
    stmt = select(Thread).where(Thread.id == thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    old_channel_id = thread.channel_id
    if old_channel_id == payload.new_channel_id:
        raise HTTPException(status_code=400, detail="Thread is already in this channel")

    # B. Validate both channels exist and are regular (message-type)
    stmt_src = select(Channel).where(Channel.id == old_channel_id)
    result_src = await db.execute(stmt_src)
    source_channel = result_src.scalar_one_or_none()
    stmt_dest = select(Channel).where(Channel.id == payload.new_channel_id)
    result_dest = await db.execute(stmt_dest)
    dest_channel = result_dest.scalar_one_or_none()
    if not source_channel or not dest_channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    # Regular channel = "message" type (DB may store as string "message" or integer 1)
    def _is_message_channel(ch):
        if ch.channel_type is None:
            return False
        s = str(ch.channel_type).lower()
        return s == "message" or (isinstance(ch.channel_type, int) and ch.channel_type == 1)
    if not _is_message_channel(source_channel) or not _is_message_channel(dest_channel):
        raise HTTPException(
            status_code=400,
            detail="Thread moves are only allowed between regular (message-type) channels",
        )
    if source_channel.workspace_id != dest_channel.workspace_id:
        raise HTTPException(status_code=400, detail="Cannot move thread across workspaces")

    # Permission: caller must have access to source channel
    if not source_channel.is_accessible_by_user(str(user.company_id), user.role or ""):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to source channel",
        )

    # C. Validate thread is active
    if not thread.is_active or thread.is_archived:
        raise HTTPException(
            status_code=400,
            detail="Only active, non-archived threads can be moved",
        )

    updated_counts = {}
    new_channel_id = payload.new_channel_id

    try:
        # D1. gg_threads
        stmt = (
            update(Thread)
            .where(Thread.id == thread_id)
            .values(channel_id=new_channel_id, updated_at=datetime.utcnow())
        )
        r = await db.execute(stmt)
        updated_counts["gg_threads"] = r.rowcount or 0

        # D2. gg_messages
        stmt = (
            update(Message)
            .where(Message.thread_id == thread_id)
            .values(updated_at=datetime.utcnow())
        )
        r = await db.execute(stmt)
        updated_counts["gg_messages"] = r.rowcount or 0

        # D3. gg_approvals — no thread_id or channel_id columns; linked only via message_id
        updated_counts["gg_approvals"] = 0

        # D4. gg_tasks — no thread_id or channel_id columns; linked only via message_id
        updated_counts["gg_tasks"] = 0

        # D5. gg_email_attachments
        stmt = (
            update(EmailAttachment)
            .where(EmailAttachment.thread_id == thread_id, EmailAttachment.channel_id == old_channel_id)
            .values(channel_id=new_channel_id, updated_at=datetime.utcnow())
        )
        r = await db.execute(stmt)
        updated_counts["gg_email_attachments"] = r.rowcount or 0

        # D6. gg_attachments (no thread_id; link via message_id)
        msg_subq = select(Message.id).where(Message.thread_id == thread_id)
        stmt = (
            update(Attachment)
            .where(
                Attachment.channel_id == old_channel_id,
                Attachment.message_id.in_(msg_subq),
            )
            .values(channel_id=new_channel_id, updated_at=datetime.utcnow())
        )
        r = await db.execute(stmt)
        updated_counts["gg_attachments"] = r.rowcount or 0

        # D7. gg_shortened_urls — replace old path with new path in original_url; update optional columns when present
        old_path = f"/threads/{old_channel_id}/{thread_id}"
        new_path = f"/threads/{new_channel_id}/{thread_id}"
        stmt = (
            update(ShortenedUrl)
            .where(ShortenedUrl.original_url.contains(old_path))
            .values(
                original_url=sa_func.replace(ShortenedUrl.original_url, old_path, new_path),
                thread_id=thread_id,
                channel_id=new_channel_id,
                last_updated_at=datetime.utcnow(),
            )
        )
        r = await db.execute(stmt)
        updated_counts["gg_shortened_urls"] = r.rowcount or 0

        await audit_log_write(db, user.id, "thread.moved", "thread", thread.id, channel_id=new_channel_id, thread_id=thread.id, details={"old_channel_id": str(old_channel_id), "new_channel_id": str(new_channel_id)})
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return ThreadMoveResponse(
        thread_id=payload.thread_id,
        old_channel_id=old_channel_id,
        new_channel_id=payload.new_channel_id,
        updated_counts=updated_counts,
    )


@router.delete("/threads/{thread_id}")
async def delete_thread(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Delete a thread and all its messages"""
    user = await get_current_user_required(request)
    
    # Get thread
    stmt = select(Thread).where(Thread.id == thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_one_or_none()
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )
    
    # Get channel
    stmt = select(Channel).where(Channel.id == thread.channel_id)
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
    
    # Check if user has admin role for deletion
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can delete threads"
        )
    
    # Get message count for confirmation
    message_count_query = select(func.count(Message.id)).where(Message.thread_id == thread_id)
    message_count_result = await db.execute(message_count_query)
    message_count = message_count_result.scalar()
    
    await audit_log_write(db, user.id, "thread.deleted", "thread", thread.id, channel_id=thread.channel_id, thread_id=thread.id)
    # 1. gg_messages – delete so they don’t point at a missing thread
    delete_messages_stmt = select(Message).where(Message.thread_id == thread_id)
    messages_result = await db.execute(delete_messages_stmt)
    messages = messages_result.scalars().all()
    for message in messages:
        await db.delete(message)
    # 2–5. Email-related tables: only for email channels; single txn, no swallowed exceptions
    is_email_channel = (
        channel.channel_type is not None
        and str(channel.channel_type).strip().lower() == "email"
    )
    if not is_email_channel:
        # Fallback: treat as email channel if this channel has an active email AppAccount
        email_acct = await db.execute(
            select(AppAccount).where(
                and_(
                    AppAccount.channel_id == channel.id,
                    AppAccount.api_key == "email",
                    AppAccount.is_active == True,
                )
            ).limit(1)
        )
        is_email_channel = email_acct.scalar_one_or_none() is not None
    if is_email_channel:
        # Use thread.id (UUID) so WHERE thread_id = :tid matches DB column type
        tid_uuid = thread.id
        # Get email_ids for this thread before we clear gg_emails.thread_id (for gg_email_hash fallback)
        email_ids_result = await db.execute(
            text("SELECT email_id FROM gg_emails WHERE thread_id = :tid"),
            {"tid": tid_uuid},
        )
        thread_email_ids = [row[0] for row in email_ids_result.fetchall() if row and row[0]]
        # 2. gg_email_attachments – DELETE where thread_id = <thread_id>
        await db.execute(text("DELETE FROM gg_email_attachments WHERE thread_id = :tid"), {"tid": tid_uuid})
        # 3. gg_case_id – DELETE where thread_id = <thread_id>
        await db.execute(text("DELETE FROM gg_case_id WHERE thread_id = :tid"), {"tid": tid_uuid})
        # 4. gg_emails – unlink and clear ml_processed_at only; leave thread_created true so scheduler doesn’t treat as “needs thread”
        r_emails = await db.execute(
            text("UPDATE gg_emails SET thread_id = NULL, ml_processed_at = NULL WHERE thread_id = :tid"),
            {"tid": tid_uuid},
        )
        emails_updated = getattr(r_emails, "rowcount", None)
        if emails_updated is not None and emails_updated == 0:
            logger.warning("delete_thread: gg_emails UPDATE matched 0 rows for thread_id=%s", thread_id)
        else:
            logger.debug("delete_thread: gg_emails updated %s rows for thread_id=%s", emails_updated, thread_id)
        # 5. gg_email_hash – unlink and clear ml_processed (by thread_id; fallback by email_id if 0 rows)
        r_hash = await db.execute(
            text("UPDATE gg_email_hash SET thread_id = NULL, ml_processed = false WHERE thread_id = :tid"),
            {"tid": tid_uuid},
        )
        hash_updated = getattr(r_hash, "rowcount", None)
        if hash_updated is not None and hash_updated == 0 and thread_email_ids:
            # Fallback: table may link by email_id only; update by this thread’s email_ids
            stmt_hash_by_email = text(
                "UPDATE gg_email_hash SET thread_id = NULL, ml_processed = false WHERE email_id IN :email_ids"
            ).bindparams(bindparam("email_ids", expanding=True))
            r_hash2 = await db.execute(stmt_hash_by_email, {"email_ids": thread_email_ids})
            hash_updated = getattr(r_hash2, "rowcount", None)
            logger.debug("delete_thread: gg_email_hash fallback by email_id updated %s rows for thread_id=%s", hash_updated, thread_id)
        if hash_updated is not None and hash_updated == 0:
            logger.warning("delete_thread: gg_email_hash UPDATE matched 0 rows for thread_id=%s", thread_id)
        else:
            logger.debug("delete_thread: gg_email_hash updated %s rows for thread_id=%s", hash_updated, thread_id)
    else:
        # Not an email channel; skip gg_email_* cleanup (only gg_messages, gg_ai_responses, gg_threads are deleted)
        logger.debug("delete_thread: non-email channel, skipping gg_emails/gg_email_hash cleanup for thread_id=%s", thread_id)
    # 6. gg_ai_responses
    ai_responses_stmt = select(AIResponse).where(AIResponse.thread_id == thread_id)
    ai_responses_result = await db.execute(ai_responses_stmt)
    ai_responses = ai_responses_result.scalars().all()
    for ai_response in ai_responses:
        await db.delete(ai_response)
    # 7. gg_threads – delete the thread row last
    await db.delete(thread)
    
    await db.commit()
    
    return {
        "message": "Thread deleted successfully",
        "thread_id": thread_id,
        "deleted_messages": message_count,
        "deleted_ai_responses": len(ai_responses)
    }


@router.post("/ml-store", response_model=MLMessageResponse)
async def store_ml_messages(
    ml_data: MLMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Store both user query and ML response in a single API call.
    
    This endpoint is designed for ML services to store both the user's query
    and the generated response in the database. It creates two messages:
    1. A user message with the prompt (saved with authenticated user)
    2. A system message with the response, linked to the user message (saved with system user)
    
    Author: Karthick Chandrasekar
    Version: 1.0.0
    Last date modified: 2025-09-02
    """
    try:
        # Get authenticated user for the prompt message
        user = await get_current_user_required(request)
        # Convert string UUID to UUID object
        try:
            thread_uuid = UUID(ml_data.thread_id)
        except ValueError:
            return MLMessageResponse(
                status="failed",
                message="Invalid thread_id format",
                data=[]
            )
        
        # Get thread
        stmt = select(Thread).where(Thread.id == thread_uuid)
        result = await db.execute(stmt)
        thread = result.scalar_one_or_none()
        
        if not thread:
            return MLMessageResponse(
                status="failed",
                message="Thread not found",
                data=[]
            )
        
        # Get channel
        stmt = select(Channel).where(Channel.id == thread.channel_id)
        result = await db.execute(stmt)
        channel = result.scalar_one_or_none()
        
        if not channel:
            return MLMessageResponse(
                status="failed",
                message="Channel not found",
                data=[]
            )
        
        # Get system user for the response
        system_user = await get_or_create_system_user(db)
        
        # Get next sequence numbers
        seq_query = select(func.max(Message.sequence_number)).where(Message.thread_id == thread_uuid)
        seq_result = await db.execute(seq_query)
        max_seq = seq_result.scalar() or 0
        
        # Create user message with the prompt (using authenticated user); mark as AI-processed since ML stored it
        user_message_id = UUID(generate_message_id())
        user_message = Message(
            id=user_message_id,
            content=ml_data.prompt,
            message_type="user",
            thread_id=thread_uuid,
            user_id=user.id,  # Use authenticated user for the prompt
            query_id=None,
            sequence_number=max_seq + 1,
            is_ai_processed=True,  # This message was processed by ML (response stored via this API)
        )
        db.add(user_message)
        max_seq += 1
        
        # Create system response message linked to the user message
        system_message_id = UUID(generate_message_id())
        
        citations_data = None
        citations_for_response = None
        if ml_data.citations:
            citations_data = [
                {
                    "name": citation.name,
                    "type": citation.type
                }
                for citation in ml_data.citations
            ]
            # Keep the original Citation objects for response
            citations_for_response = ml_data.citations

        # Persist usage_metrics from request for system message (token_usage, time_usage, etc.)
        usage_metrics_data = ml_data.usage_metrics if ml_data.usage_metrics else None
        usage_metrics_for_response = usage_metrics_data
        # Derive ai_processing_time from usage_metrics if present (e.g. time_usage in ms)
        ai_processing_time_ms = None
        if isinstance(usage_metrics_data, dict) and usage_metrics_data.get("time_usage") is not None:
            try:
                ai_processing_time_ms = int(usage_metrics_data["time_usage"])
            except (TypeError, ValueError):
                pass
        
        system_message = Message(
            id=system_message_id,
            content=ml_data.response,
            message_type="system",
            thread_id=thread_uuid,
            user_id=system_user.id,
            query_id=user_message_id,  # Link to the user message we just created
            sequence_number=max_seq + 1,
            citations=citations_data,  # Store citations for system messages only
            usage_metrics=usage_metrics_data,  # Store usage_metrics for system messages only
            is_ai_processed=True,  # System message is the AI response
            ai_processing_time=ai_processing_time_ms,
        )
        db.add(system_message)
        
        # Update thread metadata
        thread.message_count += 2  # We're adding 2 messages
        thread.last_message_at = datetime.utcnow()
        
        # Update channel metadata
        channel.message_count += 2  # We're adding 2 messages
        channel.last_message_at = datetime.utcnow()
        await audit_log_write(db, user.id, "message.created", "message", user_message.id, channel_id=thread.channel_id, thread_id=thread_uuid, details={"source": "ml-store", "message_type": "user"})
        await audit_log_write(db, user.id, "message.created", "message", system_message.id, channel_id=thread.channel_id, thread_id=thread_uuid, details={"source": "ml-store", "message_type": "system"})
        await db.commit()
        
        # Refresh messages to get the created data
        await db.refresh(user_message)
        await db.refresh(system_message)
        
        # Emit socket events for both messages - PURE EMISSION ONLY
        await emit_message_created_event(
            channel_id=str(thread.channel_id),
            thread_id=str(user_message.thread_id),
            message_id=str(user_message.id)
        )
        await emit_message_created_event(
            channel_id=str(thread.channel_id),
            thread_id=str(system_message.thread_id),
            message_id=str(system_message.id)
        )
        
        # Prepare response data
        response_data = []
        
        # Add user message to response (using authenticated user info)
        user_bean = UserBean(
            id=str(user.id),
            email=user.email_id,
            name=user.name,
            role=user.role,
            avatar_url=user.avatar_url
        )
        
        response_data.append(MessageResponse(
            id=str(user_message.id),
            content=user_message.content,
            message_type=user_message.message_type,
            thread_id=str(user_message.thread_id),
            channel_id=str(thread.channel_id),
            user_id=str(user_message.user_id),
            query_id=str(user_message.query_id) if user_message.query_id else None,
            userBean=user_bean,
            is_ai_processed=user_message.is_ai_processed,
            ai_provider=user_message.ai_provider,
            ai_model=user_message.ai_model,
            ai_processing_time=user_message.ai_processing_time,
            is_visible=user_message.is_visible,
            is_pinned=user_message.is_pinned,
            sequence_number=user_message.sequence_number,
            attachment_ids=[str(aid) for aid in user_message.attachment_ids] if user_message.attachment_ids else None,
            citations=None,  # User messages don't have citations
            usage_metrics=None,  # User messages don't have usage_metrics
            created_at=user_message.created_at,
            updated_at=user_message.updated_at
        ))
        
        # Add system message to response
        system_bean = UserBean(
            id=str(system_user.id),
            email=system_user.email_id,
            name=system_user.name,
            role=system_user.role,
            avatar_url=system_user.avatar_url
        )
        
        # Use citations from request (already in Citation format) or from database
        citations_response = None
        if citations_for_response:
            # Use the citations we already have from the request
            citations_response = citations_for_response
        elif system_message.citations and len(system_message.citations) > 0:
            # Fallback: convert from JSONB if not available from request
            citations_response = [
                Citation(name=citation["name"], type=citation["type"])
                for citation in system_message.citations
            ]

        # Use usage_metrics from request or from database (after persist)
        usage_metrics_response = usage_metrics_for_response if usage_metrics_for_response is not None else (system_message.usage_metrics or None)
        
        response_data.append(MessageResponse(
            id=str(system_message.id),
            content=system_message.content,
            message_type=system_message.message_type,
            thread_id=str(system_message.thread_id),
            channel_id=str(thread.channel_id),
            user_id=str(system_message.user_id),
            query_id=str(system_message.query_id),
            userBean=system_bean,
            is_ai_processed=system_message.is_ai_processed,
            ai_provider=system_message.ai_provider,
            ai_model=system_message.ai_model,
            ai_processing_time=system_message.ai_processing_time,
            is_visible=system_message.is_visible,
            is_pinned=system_message.is_pinned,
            sequence_number=system_message.sequence_number,
            attachment_ids=[str(aid) for aid in system_message.attachment_ids] if system_message.attachment_ids else None,
            citations=citations_response,  # Include citations for system messages
            usage_metrics=usage_metrics_response,  # Include usage_metrics for system messages
            created_at=system_message.created_at,
            updated_at=system_message.updated_at
        ))
        
        return MLMessageResponse(
            status="success",
            message="Response received successfully",
            data=response_data
        )
        
    except Exception as e:
        # Rollback any changes
        await db.rollback()
        return MLMessageResponse(
            status="failed",
            message=f"There is some issue while getting connection to database: {str(e)}",
            data=[]
        )


async def trigger_ai_processing(message_id: str):
    """Trigger AI processing for a message"""
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get message
            stmt = select(Message).where(Message.id == message_id)
            result = await db.execute(stmt)
            message = result.scalar_one_or_none()
            
            if not message:
                return

            # Get thread to derive channel
            stmt = select(Thread).where(Thread.id == message.thread_id)
            result = await db.execute(stmt)
            ai_thread = result.scalar_one_or_none()
            if not ai_thread:
                return

            # Get channel
            stmt = select(Channel).where(Channel.id == ai_thread.channel_id)
            result = await db.execute(stmt)
            channel = result.scalar_one_or_none()
            
            if not channel or not channel.ai_enabled:
                return
            
            # Get workspace for AI settings
            stmt = select(Workspace).where(Workspace.id == channel.workspace_id)
            result = await db.execute(stmt)
            workspace = result.scalar_one_or_none()
            
            if not workspace:
                return
            
            # Create AI response record
            ai_response = AIResponse(
                id=generate_message_id(),  # Reusing message ID generator
                message_id=message_id,
                thread_id=message.thread_id,
                workspace_id=workspace.id,
                ai_provider=workspace.ai_provider,
                ai_model=workspace.ai_model,
                response_content="",  # Will be filled by AI callback
                status="pending"
            )
            
            db.add(ai_response)
            await db.commit()
            
            # TODO: Implement actual AI webhook call
            # For now, we'll just simulate the process
            
        except Exception as e:
            print(f"Error triggering AI processing: {e}")
            # Update AI response with error
            stmt = select(AIResponse).where(AIResponse.message_id == message_id)
            result = await db.execute(stmt)
            ai_response = result.scalar_one_or_none()
            
            if ai_response:
                ai_response.status = "failed"
                ai_response.error_message = str(e)
                await db.commit() 

