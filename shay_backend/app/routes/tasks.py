"""
Task routes for CRUD operations and task management

This module defines FastAPI routes for comprehensive task management including
creation, updates, status changes, and checklist integration.

File: app/routes/tasks.py
Version: 1.0.0
Author: Karthick Chandrasekar
Date: 18-08-2025

Features:
- Full CRUD operations for tasks
- Status management with new values (Open, In Progress, On Hold, Close)
- Priority management (Low, Medium, High, Critical, Blocker)
- Checklist integration during task creation
- Thread-specific task management
- Comprehensive access control and validation
"""

import os
import uuid
from datetime import datetime, date, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.expression import literal
from sqlalchemy.dialects.postgresql import JSONB as PgJSONB
from uuid import UUID

from app.core.database import get_db
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.utils.channel_access import check_channel_access_by_thread
from app.services.audit_service import log as audit_log_write
from app.services.email_service import email_service
from app.services.link_shortener_service import link_shortener_service
from app.models.realtime_notification import RealtimeNotification

def format_due_date_for_response(due_date):
    """Helper function to format due_date for API responses"""
    if not due_date:
        return None
    
    if hasattr(due_date, 'isoformat'):
        # If it's a datetime object, use isoformat
        return due_date.isoformat()
    else:
        # If it's a date object, convert to datetime first
        from datetime import datetime
        return datetime.combine(due_date, datetime.min.time()).isoformat()
from app.models.user import User
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.message import Message, Thread
from app.models.company import Company
from app.schemas.task import (
    TaskCreate,
    TaskUpdate,
    TaskResponse,
    TaskList,
    TaskStats,
    TaskAssignmentRequest,
    TaskStatusUpdateRequest,
    TaskFilterRequest,
    TaskListResponse,
    EnhancedTaskResponse,
    TaskDetails,
    TaskHistoryItem,
    TaskCountResponse
)

router = APIRouter()


async def get_channel_members_with_task_notifications_enabled(
    channel_id: UUID,
    task_creator_id: UUID,
    db: AsyncSession
) -> List[User]:
    """
    Get all channel members who have task notifications enabled.
    Excludes the task creator.
    
    Logic:
    - Get all active channel members
    - For each member, check gg_realtime_notification table
    - Only include if:
      1. Data exists in table
      2. is_notifications_enabled = true
      3. is_task_enabled = true
    - Exclude task creator
    
    Args:
        channel_id: Channel ID
        task_creator_id: User ID who created the task (will be excluded)
        db: Database session
        
    Returns:
        List of User objects who have task notifications enabled
    """
    # Get all active channel members
    channel_members_stmt = select(ChannelMember).where(
        and_(
            ChannelMember.channel_id == channel_id,
            ChannelMember.is_active == True
        )
    )
    channel_members_result = await db.execute(channel_members_stmt)
    channel_members = channel_members_result.scalars().all()
    
    if not channel_members:
        return []
    
    # Get user IDs from channel members
    member_user_ids = [member.user_id for member in channel_members]
    
    # Get notification preferences for all members in this channel
    notification_prefs_stmt = select(RealtimeNotification).where(
        and_(
            RealtimeNotification.channel_id == channel_id,
            RealtimeNotification.user_id.in_(member_user_ids)
        )
    )
    notification_prefs_result = await db.execute(notification_prefs_stmt)
    notification_prefs = notification_prefs_result.scalars().all()
    
    # Create a map of user_id -> notification preference
    notification_map = {pref.user_id: pref for pref in notification_prefs}
    
    # Filter members who have notifications enabled
    enabled_user_ids = []
    for member in channel_members:
        # Skip task creator
        if member.user_id == task_creator_id:
            continue
        
        # Check if notification preference exists
        notification_pref = notification_map.get(member.user_id)
        
        # Only send if data exists AND both flags are enabled
        if notification_pref:
            if notification_pref.is_notifications_enabled and notification_pref.is_task_enabled:
                enabled_user_ids.append(member.user_id)
    
    if not enabled_user_ids:
        return []
    
    # Get user details for enabled members
    users_stmt = select(User).where(User.id.in_(enabled_user_ids))
    users_result = await db.execute(users_stmt)
    users = users_result.scalars().all()
    
    return list(users)


async def send_task_assignment_notification_email(
    recipient_user: User,
    task_creator: User,
    assigned_user: User,
    channel: Channel,
    task_title: str,
    redirect_url: str,
    notification_settings_url: str,
    db: AsyncSession
) -> bool:
    """
    Send task assignment notification email to a channel member.
    
    Args:
        recipient_user: User who will receive the notification
        task_creator: User who created/assigned the task
        assigned_user: User who was assigned the task
        channel: Channel where the task was created
        task_title: Title of the task
        redirect_url: URL to redirect to view the task
        notification_settings_url: URL to notification settings page
        db: Database session
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Load the task notification template
        template = email_service._load_template('task_notification.html')
        
        # Get platform name from config
        platform_name = settings.PLATFORM_NAME
        
        # Prepare template variables
        template_variables = {
            'user': task_creator.name or task_creator.email_id or 'Someone',
            'assigned_user': assigned_user.name or assigned_user.email_id or 'User',
            'assigned_user_email': assigned_user.email_id or '',
            'assigned_user_role': assigned_user.role or 'user',
            'channel_name': channel.name or 'the channel',
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
        msg['To'] = recipient_user.email_id
        msg['Subject'] = f"Task assigned in {channel.name or 'a channel'}"
        
        # Attach HTML version only (no plain text)
        msg.attach(MIMEText(processed_html, 'html'))
        
        # Send email
        result = email_service._send_email(msg)
        
        if result:
            print(f"✅ Task assignment notification email sent successfully to {recipient_user.email_id}")
        else:
            print(f"❌ Failed to send task assignment notification email to {recipient_user.email_id}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error sending task assignment notification email to {recipient_user.email_id}: {e}")
        import traceback
        print(f"📋 Error traceback: {traceback.format_exc()}")
        return False


async def send_task_reassignment_notification_email(
    recipient_user: User,
    reassigner: User,
    reassigned_user: User,
    channel: Channel,
    redirect_url: str,
    notification_settings_url: str,
    db: AsyncSession
) -> bool:
    """
    Send task reassignment notification email to a channel member.
    
    Args:
        recipient_user: User who will receive the notification
        reassigner: User who reassigned the task
        reassigned_user: User who was reassigned to the task
        channel: Channel where the task was reassigned
        redirect_url: URL to redirect to view the task
        notification_settings_url: URL to notification settings page
        db: Database session
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Load the task reassign notification template
        template = email_service._load_template('task_reassign_notification.html')
        
        # Get platform name from config
        platform_name = settings.PLATFORM_NAME
        
        # Prepare template variables
        template_variables = {
            'user': reassigner.name or reassigner.email_id or 'Someone',
            'reassigned_user': reassigned_user.name or reassigned_user.email_id or 'User',
            'reassigned_user_email': reassigned_user.email_id or '',
            'reassigned_user_role': reassigned_user.role or 'user',
            'channel_name': channel.name or 'the channel',
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
        msg['To'] = recipient_user.email_id
        msg['Subject'] = f"Task reassigned in {channel.name or 'a channel'}"
        
        # Attach HTML version only (no plain text)
        msg.attach(MIMEText(processed_html, 'html'))
        
        # Send email
        result = email_service._send_email(msg)
        
        if result:
            print(f"✅ Task reassignment notification email sent successfully to {recipient_user.email_id}")
        else:
            print(f"❌ Failed to send task reassignment notification email to {recipient_user.email_id}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error sending task reassignment notification email to {recipient_user.email_id}: {e}")
        import traceback
        print(f"📋 Error traceback: {traceback.format_exc()}")
        return False


async def process_task_reassignment_notifications(
    reassigner_id: str,
    reassigned_user_id: str,
    channel_id: str,
    redirect_url: str,
    notification_settings_url: str
) -> None:
    """
    Process task reassignment notifications for channel members.
    This function creates its own database session for background processing.
    
    Args:
        reassigner_id: UUID string of the user who reassigned the task
        reassigned_user_id: UUID string of the user reassigned to the task
        channel_id: UUID string of the channel where task was reassigned
        redirect_url: Pre-constructed URL to redirect to view the task
        notification_settings_url: Pre-constructed URL to notification settings page
    """
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get reassigner
            reassigner_stmt = select(User).where(User.id == UUID(reassigner_id))
            reassigner_result = await db.execute(reassigner_stmt)
            reassigner = reassigner_result.scalar_one_or_none()
            
            if not reassigner:
                print(f"⚠️ Reassigner not found: {reassigner_id}")
                return
            
            # Get reassigned user
            reassigned_stmt = select(User).where(User.id == UUID(reassigned_user_id))
            reassigned_result = await db.execute(reassigned_stmt)
            reassigned_user = reassigned_result.scalar_one_or_none()
            
            if not reassigned_user:
                print(f"⚠️ Reassigned user not found: {reassigned_user_id}")
                return
            
            # Get channel
            channel_stmt = select(Channel).where(Channel.id == UUID(channel_id))
            channel_result = await db.execute(channel_stmt)
            channel = channel_result.scalar_one_or_none()
            
            if not channel:
                print(f"⚠️ Channel not found: {channel_id}")
                return
            
            # Get channel members with task notifications enabled
            enabled_members = await get_channel_members_with_task_notifications_enabled(
                channel.id,
                reassigner.id,
                db
            )
            
            if not enabled_members:
                print(f"ℹ️ No channel members with task notifications enabled for channel {channel_id}")
                return
            
            # Send notification to each enabled member with pre-constructed URLs
            for member in enabled_members:
                await send_task_reassignment_notification_email(
                    member,
                    reassigner,
                    reassigned_user,
                    channel,
                    redirect_url,
                    notification_settings_url,
                    db
                )
        
        except Exception as e:
            print(f"❌ Error processing task reassignment notifications: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")


async def process_task_assignment_notifications(
    task_creator_id: str,
    assigned_user_id: str,
    channel_id: str,
    task_title: str,
    redirect_url: str,
    notification_settings_url: str
) -> None:
    """
    Process task assignment notifications for channel members.
    This function creates its own database session for background processing.
    
    Args:
        task_creator_id: UUID string of the user who created the task
        assigned_user_id: UUID string of the user assigned to the task
        channel_id: UUID string of the channel where task was created
        task_title: Title of the task
        redirect_url: Pre-constructed URL to redirect to view the task
        notification_settings_url: Pre-constructed URL to notification settings page
    """
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get task creator
            creator_stmt = select(User).where(User.id == UUID(task_creator_id))
            creator_result = await db.execute(creator_stmt)
            task_creator = creator_result.scalar_one_or_none()
            
            if not task_creator:
                print(f"⚠️ Task creator not found: {task_creator_id}")
                return
            
            # Get assigned user
            assigned_stmt = select(User).where(User.id == UUID(assigned_user_id))
            assigned_result = await db.execute(assigned_stmt)
            assigned_user = assigned_result.scalar_one_or_none()
            
            if not assigned_user:
                print(f"⚠️ Assigned user not found: {assigned_user_id}")
                return
            
            # Get channel
            channel_stmt = select(Channel).where(Channel.id == UUID(channel_id))
            channel_result = await db.execute(channel_stmt)
            channel = channel_result.scalar_one_or_none()
            
            if not channel:
                print(f"⚠️ Channel not found: {channel_id}")
                return
            
            # Get channel members with task notifications enabled
            enabled_members = await get_channel_members_with_task_notifications_enabled(
                channel.id,
                task_creator.id,
                db
            )
            
            if not enabled_members:
                print(f"ℹ️ No channel members with task notifications enabled for channel {channel_id}")
                return
            
            # Send notification to each enabled member with pre-constructed URLs
            for member in enabled_members:
                await send_task_assignment_notification_email(
                    member,
                    task_creator,
                    assigned_user,
                    channel,
                    task_title,
                    redirect_url,
                    notification_settings_url,
                    db
                )
        
        except Exception as e:
            print(f"❌ Error processing task assignment notifications: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")


def convert_checklists_to_dict(checklists):
    """Convert checklist objects to dictionary format safely"""
    if not checklists:
        return []
    
    result = []
    for checklist in checklists:
        if hasattr(checklist, 'to_dict'):
            result.append(checklist.to_dict())
        else:
            # Fallback: create dict manually if to_dict method is not available
            result.append({
                'id': str(checklist.id) if hasattr(checklist, 'id') else None,
                'task_id': str(checklist.task_id) if hasattr(checklist, 'task_id') else None,
                'text': checklist.text if hasattr(checklist, 'text') else '',
                'order_index': checklist.order_index if hasattr(checklist, 'order_index') else 0,
                'is_completed': checklist.is_completed if hasattr(checklist, 'is_completed') else False,
                'completed_at': checklist.completed_at.isoformat() if hasattr(checklist, 'completed_at') and checklist.completed_at else None,
                'completed_by': str(checklist.completed_by) if hasattr(checklist, 'completed_by') and checklist.completed_by else None,
                'checklist_metadata': checklist.checklist_metadata if hasattr(checklist, 'checklist_metadata') else None,
                'created_at': checklist.created_at.isoformat() if hasattr(checklist, 'created_at') and checklist.created_at else None,
                'updated_at': checklist.updated_at.isoformat() if hasattr(checklist, 'updated_at') and checklist.updated_at else None
            })
    return result


def build_task_response(task: Task, include_details: bool = False) -> Dict[str, Any]:
    """Build a safe serializable response for a Task without mutating ORM relationships"""
    response = {
        'id': task.id,
        'title': task.title,
        'description': task.description,
        'status': task.status,
        'source': task.source,
        'due_date': format_due_date_for_response(task.due_date),
        'priority': task.priority,
        'tags': task.tags,
        'task_metadata': task.task_metadata,
        'created_at': task.created_at,
        'updated_at': task.updated_at,
        'completed_at': getattr(task, 'completed_at', None),
        'checklists': [],  # Initialize as empty to avoid lazy loading issues
    }
    
    # Note: channel/workspace details are no longer available as ORM relationships on Task.
    # They are resolved via message_id in load_task_details() and build_task_context().

    return response


async def load_task_details(task: Task, db: AsyncSession) -> Dict[str, Any]:
    """Load additional user and context details for a task"""
    details = {}
    
    # Load assigned user details
    if task.assigned_to:
        user_stmt = select(User).where(User.id == task.assigned_to)
        user_result = await db.execute(user_stmt)
        assigned_user = user_result.scalar_one_or_none()
        if assigned_user:
            details['assigned_user'] = {
                'id': assigned_user.id,
                'name': assigned_user.name,
                'email_id': assigned_user.email_id,
                'avatar_url': assigned_user.avatar_url,
                'role': assigned_user.role
            }
    
    # Load created by user details
    if hasattr(task, 'created_by') and task.created_by:
        user_stmt = select(User).where(User.id == task.created_by)
        user_result = await db.execute(user_stmt)
        created_by_user = user_result.scalar_one_or_none()
        if created_by_user:
            details['created_by'] = {
                'id': created_by_user.id,
                'name': created_by_user.name,
                'email_id': created_by_user.email_id,
                'avatar_url': created_by_user.avatar_url,
                'role': created_by_user.role
            }
    
    # Load channel/workspace details via message_id
    if hasattr(task, 'message_id') and task.message_id:
        msg_stmt = select(Message).where(Message.id == task.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg and msg.channel_id:
            channel_stmt = select(Channel).where(Channel.id == msg.channel_id)
            channel_result = await db.execute(channel_stmt)
            channel = channel_result.scalar_one_or_none()
            if channel:
                details['channel'] = {
                    'id': channel.id,
                    'name': channel.name,
                    'description': channel.description,
                    'is_public': channel.is_public,
                    'is_active': channel.is_active,
                    'workspace_id': str(channel.workspace_id) if channel.workspace_id else None
                }
            if msg.workspace_id:
                workspace_stmt = select(Workspace).where(Workspace.id == msg.workspace_id)
                workspace_result = await db.execute(workspace_stmt)
                workspace = workspace_result.scalar_one_or_none()
                if workspace:
                    details['workspace'] = {
                        'id': workspace.id,
                        'name': workspace.name,
                        'description': workspace.description
                    }

    return details


def extract_task_history(task: Task) -> Dict[str, Any]:
    """Extract minimal task history from existing task data"""
    history = {
        'status_changes': [],
        'priority_changes': [],
        'assignee_changes': []
    }
    
    # Add current status as initial status
    history['status_changes'].append({
        'status': task.status,
        'changed_at': task.created_at.isoformat() if task.created_at else None,
        'changed_by': str(task.created_by) if task.created_by else None
    })
    
    # Add current priority as initial priority
    history['priority_changes'].append({
        'priority': task.priority,
        'changed_at': task.created_at.isoformat() if task.created_at else None,
        'changed_by': str(task.created_by) if task.created_by else None
    })
    
    # Add current assignee as initial assignment
    if task.assigned_to:
        history['assignee_changes'].append({
            'assigned_to': str(task.assigned_to),
            'changed_at': task.created_at.isoformat() if task.created_at else None,
            'changed_by': str(task.created_by) if task.created_by else None
        })
    
    # Extract status changes from metadata if available
    if task.task_metadata and isinstance(task.task_metadata, dict):
        if 'status_changes' in task.task_metadata:
            status_changes = task.task_metadata['status_changes']
            if isinstance(status_changes, list):
                for change in status_changes:
                    if isinstance(change, dict):
                        history['status_changes'].append({
                            'status': change.get('status'),
                            'changed_at': change.get('changed_at'),
                            'changed_by': change.get('changed_by'),
                            'comments': change.get('comments')
                        })
        
        # Extract priority changes from metadata if available
        if 'priority_changes' in task.task_metadata:
            priority_changes = task.task_metadata['priority_changes']
            if isinstance(priority_changes, list):
                for change in priority_changes:
                    if isinstance(change, dict):
                        history['priority_changes'].append({
                            'priority': change.get('priority'),
                            'changed_at': change.get('changed_at'),
                            'changed_by': change.get('changed_by'),
                            'comments': change.get('comments')
                        })
    
    return history


async def build_task_details(task: Task, db: AsyncSession) -> Dict[str, Any]:
    """Build detailed task information"""
    
    # Get assignee user details
    assignee_data = None
    if task.assigned_to:
        try:
            user_stmt = select(User).where(User.id == task.assigned_to)
            user_result = await db.execute(user_stmt)
            assignee_user = user_result.scalar_one_or_none()
            
            if assignee_user and hasattr(assignee_user, 'id'):
                assignee_data = {
                    'id': str(assignee_user.id),
                    'name': getattr(assignee_user, 'name', 'Unknown'),
                    'email_id': getattr(assignee_user, 'email_id', ''),
                    'avatar_url': getattr(assignee_user, 'avatar_url', ''),
                    'username': getattr(assignee_user, 'username', 'unknown')
                }

        except Exception as e:
            print(f"Error fetching assignee user: {e}")
            assignee_data = None
    
    # Get creator user details
    creator_data = None
    if task.created_by:
        try:
            creator_stmt = select(User).where(User.id == task.created_by)
            creator_result = await db.execute(creator_stmt)
            creator_user = creator_result.scalar_one_or_none()
            
            if creator_user and hasattr(creator_user, 'id'):
                creator_data = {
                    'id': str(creator_user.id),
                    'name': getattr(creator_user, 'name', 'Unknown'),
                    'email_id': getattr(creator_user, 'email_id', ''),
                    'avatar_url': getattr(creator_user, 'avatar_url', ''),
                    'username': getattr(creator_user, 'username', 'unknown')
                }

        except Exception as e:
            print(f"Error fetching creator user: {e}")
            creator_data = None
    
    return {
        'task_name': task.title,
        'status': task.status,
        'assignee': assignee_data,
        'created_by': creator_data,
        'priority': task.priority,
        'description': task.description,
        'due_date': format_due_date_for_response(task.due_date),
        'created_at': task.created_at,
        'updated_at': task.updated_at,
        'source': task.source,
        'tags': task.tags,
        'task_metadata': task.task_metadata
    }


async def build_task_history(task: Task, db: AsyncSession) -> List[Dict[str, Any]]:
    """Build task history timeline"""
    history = []
    
    # Simple approach: Always add basic task creation and assignment history
    # This ensures we always have some history even if user lookups fail
    
    from datetime import timedelta
    
    # 1. Task creation (always add)
    creation_timestamp = task.created_at
    if hasattr(task, 'created_at') and task.created_at:
        # Subtract 1 second to make task creation appear after assignment
        creation_timestamp = task.created_at - timedelta(seconds=1)
    
    history.append({
        'action': 'Task Created',
        'details': f'Task "{task.title}" created',
        'timestamp': creation_timestamp,
        'user': None,
        'metadata': {
            'priority': task.priority,
            'source': task.source or 'manual'
        }
    })
    
    # 2. Task assignment (always add if we can get user details)
    try:
        # Get task details to get user information
        task_details = await load_task_details(task, db)
        assignee_user = task_details.get('assigned_user')
        creator_user = task_details.get('created_by')
        
        # Update task creation with user details if available
        if creator_user:
            history[0]['details'] = f'Task "{task.title}" created by {creator_user.get("name", "Unknown")}'
            history[0]['user'] = creator_user
        
        # Add assignment history if we have assignee
        if assignee_user:
            due_date_info = ""
            if task.due_date:
                # Handle both date and datetime objects
                if hasattr(task.due_date, 'strftime'):
                    due_date_info = f" Due: {task.due_date.strftime('%m-%d-%Y %I:%M %p')}"
                else:
                    # For date objects, add default time
                    from datetime import datetime
                    dt = datetime.combine(task.due_date, datetime.min.time())
                    due_date_info = f" Due: {dt.strftime('%m-%d-%Y %I:%M %p')}"
            
            # Use a slightly later timestamp for assignment to appear first
            assignment_timestamp = task.created_at
            if hasattr(task, 'created_at') and task.created_at:
                # Add 1 second to make assignment appear before task creation
                assignment_timestamp = task.created_at + timedelta(seconds=1)
            
            history.append({
                'action': 'Assigned to',
                'details': f'Assigned to {assignee_user.get("name", "Unknown")}@{assignee_user.get("username", "unknown")}{due_date_info} Priority: {task.priority}',
                'timestamp': assignment_timestamp,
                'user': assignee_user,
                'metadata': {
                    'priority': task.priority,
                    'due_date': format_due_date_for_response(task.due_date)
                }
            })
    
    except Exception as e:
        print(f"Error getting user details for task history: {e}")
        # Keep the basic history we already created
    
    # 3. Status changes from metadata
    if task.task_metadata and 'status_changes' in task.task_metadata:
        for status_change in task.task_metadata['status_changes']:
            # Get user who made the change
            change_user_stmt = select(User).where(User.id == status_change['changed_by'])
            change_user_result = await db.execute(change_user_stmt)
            change_user = change_user_result.scalar_one_or_none()
            
            if change_user and hasattr(change_user, 'id'):
                from datetime import datetime
                history.append({
                    'action': 'Status Changed',
                    'details': f'Changed status to {status_change["status"]}',
                    'timestamp': datetime.fromisoformat(status_change['changed_at'].replace('Z', '+00:00')).replace(tzinfo=None),
                    'user': {
                        'id': str(change_user.id),
                        'name': getattr(change_user, 'name', 'Unknown'),
                        'email_id': getattr(change_user, 'email_id', ''),
                        'avatar_url': getattr(change_user, 'avatar_url', ''),
                        'username': getattr(change_user, 'username', 'unknown')
                    },
                    'metadata': {
                        'old_status': task.status,
                        'new_status': status_change['status'],
                        'comments': status_change.get('comments')
                    }
                })
    
    # 4. Priority changes (if any)
    if task.task_metadata and 'priority_changes' in task.task_metadata:
        for priority_change in task.task_metadata['priority_changes']:
            change_user_stmt = select(User).where(User.id == priority_change['changed_by'])
            change_user_result = await db.execute(change_user_stmt)
            change_user = change_user_result.scalar_one_or_none()
            
            if change_user and hasattr(change_user, 'id'):
                history.append({
                    'action': 'Priority Changed',
                    'details': f'Changed priority to {priority_change["priority"]}',
                    'timestamp': datetime.fromisoformat(priority_change['changed_at'].replace('Z', '+00:00')).replace(tzinfo=None),
                    'user': {
                        'id': str(change_user.id),
                        'name': getattr(change_user, 'name', 'Unknown'),
                        'email_id': getattr(change_user, 'email_id', ''),
                        'avatar_url': getattr(change_user, 'avatar_url', ''),
                        'username': getattr(change_user, 'username', 'unknown')
                    },
                    'metadata': {
                        'old_priority': task.priority,
                        'new_priority': priority_change['priority'],
                        'comments': priority_change.get('comments')
                    }
                })
    
    # 5. Assignee changes (reassignments)
    if task.task_metadata and 'assignee_changes' in task.task_metadata:
        for assignee_change in task.task_metadata['assignee_changes']:
            # Get user who made the change
            change_user_stmt = select(User).where(User.id == assignee_change['changed_by'])
            change_user_result = await db.execute(change_user_stmt)
            change_user = change_user_result.scalar_one_or_none()
            
            # Get previous assignee details
            previous_assignee_name = "Unknown"
            if assignee_change.get('previous_assignee'):
                prev_user_stmt = select(User).where(User.id == assignee_change['previous_assignee'])
                prev_user_result = await db.execute(prev_user_stmt)
                prev_user = prev_user_result.scalar_one_or_none()
                if prev_user:
                    previous_assignee_name = getattr(prev_user, 'name', 'Unknown')
            
            # Get new assignee details
            new_assignee_name = "Unknown"
            if assignee_change.get('new_assignee'):
                new_user_stmt = select(User).where(User.id == assignee_change['new_assignee'])
                new_user_result = await db.execute(new_user_stmt)
                new_user = new_user_result.scalar_one_or_none()
                if new_user:
                    new_assignee_name = getattr(new_user, 'name', 'Unknown')
            
            if change_user and hasattr(change_user, 'id'):
                from datetime import datetime
                history.append({
                    'action': 'Reassigned',
                    'details': f'Reassigned from {previous_assignee_name} to {new_assignee_name}',
                    'timestamp': datetime.fromisoformat(assignee_change['changed_at'].replace('Z', '+00:00')).replace(tzinfo=None),
                    'user': {
                        'id': str(change_user.id),
                        'name': getattr(change_user, 'name', 'Unknown'),
                        'email_id': getattr(change_user, 'email_id', ''),
                        'avatar_url': getattr(change_user, 'avatar_url', ''),
                        'username': getattr(change_user, 'username', 'unknown')
                    },
                    'metadata': {
                        'previous_assignee': assignee_change.get('previous_assignee'),
                        'new_assignee': assignee_change.get('new_assignee'),
                        'action': assignee_change.get('action', 'reassigned')
                    }
                })
    
    # Sort history by timestamp (newest first)
    history.sort(key=lambda x: x['timestamp'], reverse=True)
    
    return history


async def build_task_context(task: Task, db: AsyncSession) -> Dict[str, Any]:
    """Build task context information by resolving through message_id"""
    context = {}

    if not (hasattr(task, 'message_id') and task.message_id):
        return context

    try:
        msg_stmt = select(Message).where(Message.id == task.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()

        if not msg:
            return context

        # Workspace context
        if msg.workspace_id:
            try:
                workspace_stmt = select(Workspace).where(Workspace.id == msg.workspace_id)
                workspace_result = await db.execute(workspace_stmt)
                workspace = workspace_result.scalar_one_or_none()
                if workspace and hasattr(workspace, 'id'):
                    context['workspace'] = {
                        'id': str(workspace.id),
                        'name': getattr(workspace, 'name', 'Unknown'),
                        'description': getattr(workspace, 'description', '')
                    }
            except Exception as e:
                print(f"Error fetching workspace context: {e}")

        # Channel context
        if msg.channel_id:
            try:
                channel_stmt = select(Channel).where(Channel.id == msg.channel_id)
                channel_result = await db.execute(channel_stmt)
                channel = channel_result.scalar_one_or_none()
                if channel and hasattr(channel, 'id'):
                    context['channel'] = {
                        'id': str(channel.id),
                        'name': getattr(channel, 'name', 'Unknown'),
                        'description': getattr(channel, 'description', ''),
                        'type': getattr(channel, 'type', 'unknown'),
                        'is_private': getattr(channel, 'is_private', False)
                    }
            except Exception as e:
                print(f"Error fetching channel context: {e}")

        # Thread context
        if msg.thread_id:
            try:
                thread_stmt = select(Thread).where(Thread.id == msg.thread_id)
                thread_result = await db.execute(thread_stmt)
                thread = thread_result.scalar_one_or_none()
                if thread and hasattr(thread, 'id'):
                    context['thread'] = {
                        'id': str(thread.id),
                        'title': getattr(thread, 'title', 'Unknown'),
                        'description': getattr(thread, 'description', '')
                    }
            except Exception as e:
                print(f"Error fetching thread context: {e}")

    except Exception as e:
        print(f"Error building task context from message: {e}")

    return context


@router.post("/", response_model=TaskResponse)
async def create_task(
    task_data: TaskCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Create a new task with automatic context resolution from message_id"""
    user = await get_current_user_required(request, db)
    
    # Get the message and validate access (message_id is now mandatory)
    message_stmt = select(Message).where(Message.id == task_data.message_id)
    message_result = await db.execute(message_stmt)
    message = message_result.scalar_one_or_none()
    
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )
    
    # Get context from message
    workspace_id = message.workspace_id
    channel_id = message.channel_id
    thread_id = message.thread_id
    message_id = task_data.message_id

    # Validate workspace access
    workspace_stmt = select(Workspace).where(Workspace.id == workspace_id)
    workspace_result = await db.execute(workspace_stmt)
    workspace = workspace_result.scalar_one_or_none()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found"
        )

    # Check if user has access to workspace
    if workspace.company_id != user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to workspace"
        )

    # Validate channel access
    channel_stmt = select(Channel).where(Channel.id == channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )

    # Check if user has access to channel
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )
    
    # Validate assigned user
    assigned_user_stmt = select(User).where(User.id == task_data.assigned_to)
    assigned_user_result = await db.execute(assigned_user_stmt)
    assigned_user = assigned_user_result.scalar_one_or_none()
    
    if not assigned_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assigned user not found"
        )
    
    # Check if assigned user is in the same company
    if assigned_user.company_id != user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot assign task to user from different company"
        )
    
    # Validate that assigned user is a member of the channel
    from app.models.channel_member import ChannelMember
    channel_member_stmt = select(ChannelMember).where(
        and_(
            ChannelMember.channel_id == channel_id,
            ChannelMember.user_id == task_data.assigned_to,
            ChannelMember.is_active == True
        )
    )
    channel_member_result = await db.execute(channel_member_stmt)
    channel_member = channel_member_result.scalar_one_or_none()
    
    if not channel_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Assigned user must be a member of the channel to receive tasks"
        )
    
    # Check if there's already an active task in this thread (via messages sharing the same thread)
    # Fetch all message IDs in the same thread and check for active tasks linked to them
    thread_messages_stmt = select(Message.id).where(Message.thread_id == thread_id)
    thread_messages_result = await db.execute(thread_messages_stmt)
    thread_message_ids = [row[0] for row in thread_messages_result.all()]

    if thread_message_ids:
        existing_task_stmt = select(Task).where(
            and_(
                Task.message_id.in_(thread_message_ids),
                Task.status.in_(["Open", "In Progress", "On Hold"])  # Active statuses
            )
        )
        existing_task_result = await db.execute(existing_task_stmt)
        existing_task = existing_task_result.scalar_one_or_none()

        if existing_task:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot create task: Thread already has an active task '{existing_task.title}' (ID: {existing_task.id}) with status '{existing_task.status}'. Only one active task allowed per thread."
            )

    assigned_to = task_data.assigned_to

    # Create task linked via message_id only (no workspace_id/channel_id/thread_id columns)
    task = Task(
        id=uuid.uuid4(),  # Pass UUID object directly, not string
        title=task_data.title,
        description=task_data.description,
        assigned_to=assigned_to,
        created_by=user.id,  # Set the user who created the task
        status=task_data.status or "Open",
        source=task_data.source or "manual",
        due_date=task_data.due_date,
        message_id=message_id,
        priority=task_data.priority,
        tags=task_data.tags,
        task_metadata=task_data.task_metadata
    )
    
    db.add(task)
    await audit_log_write(db, user.id, "task.created", "task", task.id, channel_id=channel_id, thread_id=thread_id)
    await db.commit()
    # Don't refresh the task to avoid potential async issues
    
    # Handle optional message content and attachments
    if task_data.message_content or task_data.attachment_ids:
        from app.core.auth import generate_message_id
        from app.models.attachment import Attachment
        
        # Create a new message with the provided content
        new_message = Message(
            id=generate_message_id(),
            content=task_data.message_content or f"Task created: {task_data.title}",
            message_type="user",
            thread_id=thread_id,
            channel_id=channel_id,
            workspace_id=workspace_id,
            user_id=user.id,
            sequence_number=message.sequence_number + 1  # Add after the original message
        )
        
        db.add(new_message)
        
        # Update channel metadata
        channel.message_count += 1
        channel.last_message_at = datetime.utcnow()
        
        await db.commit()
        await db.refresh(new_message)
        
        # Link attachments to the new message if provided
        if task_data.attachment_ids:
            for attachment_id in task_data.attachment_ids:
                try:
                    attachment_uuid = uuid.UUID(attachment_id)
                    attachment_stmt = select(Attachment).where(
                        and_(
                            Attachment.id == attachment_uuid,
                            Attachment.channel_id == channel_id,
                            Attachment.user_id == user.id  # Ensure user owns the attachment
                        )
                    )
                    attachment_result = await db.execute(attachment_stmt)
                    attachment = attachment_result.scalar_one_or_none()
                    
                    if attachment:
                        # Link attachment to the new message
                        attachment.message_id = new_message.id
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
            
            await db.commit()
        
        # Update task to reference the new message
        task.message_id = new_message.id
        await db.commit()
    
    # Create checklists if provided
    if task_data.checklists:
        from app.models.checklist import Checklist
        
        for i, checklist_item in enumerate(task_data.checklists):
            checklist = Checklist(
                id=uuid.uuid4(),  # Pass UUID object directly, not string
                task_id=task.id,  # task.id should already be UUID object
                text=checklist_item.get('text', f'Checklist Item {i+1}'),
                order_index=checklist_item.get('order_index', i),
                checklist_metadata=checklist_item.get('checklist_metadata')
            )
            db.add(checklist)
        
        await db.commit()
    
    # Refresh the task object to ensure all fields are properly loaded
    await db.refresh(task)
    
    # Process task assignment notifications in background
    if task.assigned_to and channel_id and thread_id:
        # Get platform URL from environment variables for real-time notifications
        platform_url = os.environ.get("PLATFORM_URL") or settings.PLATFORM_URL

        try:
            # Construct redirect URL (shortened; store thread_id/channel_id for move-safe links)
            redirect_url = await link_shortener_service.shorten(
                f"{platform_url}/threads/{channel_id}/{thread_id}?openTask=true", db,
                thread_id=thread_id, channel_id=channel_id, entity_type="task",
            ) if platform_url else "#"
            # Construct notification settings URL (shortened; channel-level)
            notification_settings_url = await link_shortener_service.shorten(
                f"{platform_url}/threads/{channel_id}?openSettings=true&tab=notification", db,
                channel_id=channel_id, entity_type="channel",
            ) if platform_url else "#"

        except Exception as e:
            print(f"Error constructing redirect URL: {e}")
            redirect_url = "#"
            notification_settings_url = "#"

        background_tasks.add_task(
            process_task_assignment_notifications,
            str(user.id),  # Task creator ID
            str(task.assigned_to),  # Assigned user ID
            str(channel_id),  # Channel ID
            task.title,  # Task title
            redirect_url,  # Pre-constructed redirect URL
            notification_settings_url  # Pre-constructed notification settings URL
        )

    # Build simple response to avoid async issues
    response = {
        'id': str(task.id),
        'title': task.title,
        'description': task.description,
        'status': task.status,
        'source': task.source,
        'due_date': format_due_date_for_response(task.due_date),
        'priority': task.priority,
        'tags': task.tags,
        'task_metadata': task.task_metadata,
        'assigned_to': str(task.assigned_to) if task.assigned_to else None,
        'created_by': str(task.created_by) if task.created_by else None,
        'message_id': str(task.message_id) if task.message_id else None,
        'created_at': task.created_at,
        'updated_at': task.updated_at,
        'completed_at': getattr(task, 'completed_at', None),
        'checklists': []
    }

    return response





@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=100, description="Page size"),
    status: Optional[str] = Query(None, description="Filter by status (comma-separated for multiple values, e.g., 'Open,In Progress,On Hold')"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    assigned_to: Optional[str] = Query(None, description="Filter by assigned user"),
    workspace_id: Optional[str] = Query(None, description="Filter by workspace (resolved via message)"),
    channel_id: Optional[str] = Query(None, description="Filter by channel (resolved via message)"),
    thread_id: Optional[str] = Query(None, description="Filter by thread (resolved via message)"),
    source: Optional[str] = Query(None, description="Filter by source"),
    tags: Optional[str] = Query(None, description="Filter by tags (comma-separated)"),
    created_by: Optional[str] = Query(None, description="Filter by task creator")
):
    """List tasks with enhanced details, history, and first task per thread limit"""
    user = await get_current_user_required(request, db)

    # Get channels where the user is a member (active channels only)
    user_channels_query = select(ChannelMember.channel_id).where(
        and_(
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True
        )
    )

    user_channels_result = await db.execute(user_channels_query)
    user_channel_ids = [str(c) for c in user_channels_result.scalars().all()]

    print(f"User {user.id} is a member of {len(user_channel_ids)} active channels")
    print(f"Channel IDs: {user_channel_ids}")

    if not user_channel_ids:
        return TaskListResponse(
            tasks=[],
            total=0,
            page=page,
            size=size,
            has_more=False
        )
    
    # Task model no longer has channel_id/thread_id/workspace_id columns.
    # Access control: get message IDs in user's channels, then find tasks by message_id.
    # Collect message IDs visible to the user (messages in their channels).
    user_messages_query = select(Message.id).where(
        Message.channel_id.in_(user_channel_ids)
    )
    if thread_id:
        # Check channel access via thread_id before filtering
        await check_channel_access_by_thread(db, user, thread_id)
        user_messages_query = user_messages_query.where(Message.thread_id == thread_id)
    if channel_id:
        user_messages_query = user_messages_query.where(Message.channel_id == channel_id)

    user_messages_result = await db.execute(user_messages_query)
    visible_message_ids = [row[0] for row in user_messages_result.all()]

    if not visible_message_ids:
        return TaskListResponse(
            tasks=[],
            total=0,
            page=page,
            size=size,
            has_more=False
        )

    # Build base query restricted to tasks linked to visible messages
    base_conditions = [Task.message_id.in_(visible_message_ids)]

    # Apply simple column filters
    if status:
        status_list = [s.strip() for s in status.split(",") if s.strip()]
        if status_list:
            base_conditions.append(Task.status.in_(status_list))

    if priority:
        base_conditions.append(Task.priority == priority)

    if assigned_to:
        base_conditions.append(Task.assigned_to == assigned_to)

    if source:
        base_conditions.append(Task.source == source)

    if created_by:
        base_conditions.append(Task.created_by == created_by)

    if tags:
        tag_list = [tag.strip() for tag in tags.split(",")]
        base_conditions.append(Task.tags.op("@>")(literal(tag_list, type_=PgJSONB())))

    # Handle task fetching
    if thread_id:
        # If thread_id is specified, get the latest task from that specific thread
        print(f"Fetching latest task from specific thread: {thread_id}")
        try:
            task_query = select(Task).where(
                and_(*base_conditions)
            ).order_by(desc(Task.created_at)).limit(1)

            task_result = await db.execute(task_query)
            task = task_result.scalar_one_or_none()
            tasks = [task] if task else []
            if task:
                print(f"Found task in specified thread: {task.title}")
            else:
                print(f"No tasks found in specified thread: {thread_id}")

        except Exception as e:
            print(f"Error fetching task from specific thread {thread_id}: {e}")
            tasks = []

    else:
        # Fetch all tasks from visible messages
        print("No thread_id filter - directly fetching tasks from user's channels")
        print(f"User ID: {user.id}")
        print(f"User channel count: {len(user_channel_ids)}")

        try:
            direct_task_query = select(Task).where(
                and_(*base_conditions)
            ).order_by(desc(Task.created_at))

            print(f"Direct task query: {direct_task_query}")

            direct_result = await db.execute(direct_task_query)
            tasks = list(direct_result.scalars().all())

            print(f"Direct query found {len(tasks)} tasks from user's channels")

            # Remove duplicates based on task ID
            seen_ids = set()
            unique_tasks = []
            for task in tasks:
                if str(task.id) not in seen_ids:
                    seen_ids.add(str(task.id))
                    unique_tasks.append(task)

            tasks = unique_tasks
            print(f"Combined total: {len(tasks)} unique tasks")

            # Sort tasks by creation date (latest first) for better UX
            if tasks:
                tasks.sort(key=lambda x: x.created_at, reverse=True)
                print(f"Tasks sorted by creation date (latest first)")

        except Exception as e:
            print(f"Error in direct task query: {e}")
            import traceback
            traceback.print_exc()
            tasks = []

    # Apply post-fetch filters
    filtered_tasks = []
    for task in tasks:
        # Exclude tasks with no message_id (orphans)
        if task.message_id is None:
            continue
        # Note: status/priority/assigned_to/source/created_by/tags filters already applied above
        filtered_tasks.append(task)
    
    # Apply pagination
    total = len(filtered_tasks)
    start_idx = (page - 1) * size
    end_idx = start_idx + size
    paginated_tasks = filtered_tasks[start_idx:end_idx]
    
    # Build enhanced responses
    enhanced_responses = []
    
    for i, task in enumerate(paginated_tasks):
        try:
            # Ensure we have a fresh database session
            await db.refresh(task)
            
        # Load checklists
            try:
                await db.refresh(task, attribute_names=['checklists'])
            except Exception as e:
                print(f"Warning: Could not load checklists for task {task.id}: {e}")
                task.checklists = []
        
            # Build task details with error handling
            try:
                task_details = await build_task_details(task, db)
            except Exception as e:
                print(f"Error building task details for {task.id}: {e}")
                import traceback
                traceback.print_exc()
                # Fallback task details
                task_details = {
                    'task_name': task.title,
                    'status': task.status,
                    'assignee': None,
                    'created_by': None,
                    'priority': task.priority,
                    'description': task.description,
                    'due_date': format_due_date_for_response(task.due_date),
                    'created_at': task.created_at.isoformat() if task.created_at else None,
                    'updated_at': task.updated_at.isoformat() if task.updated_at else None,
                    'source': task.source or 'manual',
                    'tags': task.tags,
                    'task_metadata': task.task_metadata
                }
            
            # Build task history with error handling
            try:
                task_history = await build_task_history(task, db)
            except Exception as e:
                print(f"Error building task history for {task.id}: {e}")
                import traceback
                traceback.print_exc()
                task_history = []
            
            # Build context information with error handling
            try:
                context = await build_task_context(task, db)
            except Exception as e:
                print(f"Error building task context for {task.id}: {e}")
                import traceback
                traceback.print_exc()
                context = {}
            
            # Build enhanced response
            enhanced_response = {
                'id': str(task.id),
                'task_details': task_details,
                'task_history': task_history,
                'checklists': convert_checklists_to_dict(getattr(task, 'checklists', [])),
                'context': context
            }
            
            enhanced_responses.append(enhanced_response)
            
        except Exception as e:
            print(f"Error building enhanced response for task {i+1} (ID: {getattr(task, 'id', 'Unknown')}): {e}")
            import traceback
            traceback.print_exc()
            
            # Add a basic response if building enhanced response fails
            try:
                basic_response = {
                    'id': str(getattr(task, 'id', 'unknown')),
                    'task_details': {
                        'task_name': getattr(task, 'title', 'Unknown'),
                        'status': getattr(task, 'status', 'Unknown'),
                        'assignee': None,
                        'created_by': None,
                        'priority': getattr(task, 'priority', 'Unknown'),
                        'description': getattr(task, 'description', ''),
                        'due_date': format_due_date_for_response(task.due_date),
                        'created_at': getattr(task, 'created_at', None),
                        'updated_at': getattr(task, 'updated_at', None),
                        'source': getattr(task, 'source', ''),
                        'tags': getattr(task, 'tags', []),
                        'task_metadata': getattr(task, 'task_metadata', {})
                    },
                    'task_history': [],
                    'checklists': [],
                    'context': {}
                }
                enhanced_responses.append(basic_response)
            except Exception as basic_error:
                print(f"Error creating basic response for task {i+1}: {basic_error}")
                continue
    
    has_more = end_idx < total
    
    return TaskListResponse(
        tasks=enhanced_responses,
        total=total,
        page=page,
        size=size,
        has_more=has_more
    )


@router.get("/count", response_model=TaskCountResponse)
async def get_task_count(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get total count of tasks for the current user - uses same logic as list endpoint"""
    user = await get_current_user_required(request, db)
    
    # Get channels where the user is a member (active channels only)
    user_channels_query = select(ChannelMember.channel_id).where(
        and_(
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True
        )
    )
    
    user_channels_result = await db.execute(user_channels_query)
    user_channel_ids = [str(c) for c in user_channels_result.scalars().all()]
    
    if not user_channel_ids:
        return TaskCountResponse(task_count=0)

    # Use the same logic as list_tasks endpoint:
    # Count tasks linked to messages in user's channels.
    visible_message_ids_query = select(Message.id).where(
        Message.channel_id.in_(user_channel_ids)
    )
    visible_msg_result = await db.execute(visible_message_ids_query)
    visible_message_ids = [row[0] for row in visible_msg_result.all()]

    if not visible_message_ids:
        return TaskCountResponse(task_count=0)

    count_query = select(func.count(Task.id)).where(
        Task.message_id.in_(visible_message_ids)
    )
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    return TaskCountResponse(task_count=total_count)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific task by ID"""
    user = await get_current_user_required(request, db)
    
    # Get task without eager loading to avoid collection issues
    stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Check access through message -> channel membership
    if task.message_id:
        msg_stmt = select(Message).where(Message.id == task.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg and msg.channel_id:
            channel_member_stmt = select(ChannelMember).where(
                and_(
                    ChannelMember.channel_id == msg.channel_id,
                    ChannelMember.user_id == user.id,
                    ChannelMember.is_active == True
                )
            )
            channel_member_result = await db.execute(channel_member_stmt)
            channel_member = channel_member_result.scalar_one_or_none()
            if not channel_member and str(task.created_by) != str(user.id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to task"
                )

    # Load checklists separately to avoid collection eager loading issues
    await db.refresh(task, attribute_names=['checklists'])

    # Load additional details manually
    details = await load_task_details(task, db)

    # Extract task history
    task_history = extract_task_history(task)

    # Build response with details
    response = build_task_response(task, include_details=False)
    response.update(details)

    # Add task history to response
    response['task_history'] = task_history

    return response


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    task_data: TaskUpdate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Update a task"""
    user = await get_current_user_required(request, db)
    
    # Get task without eager loading to avoid collection issues
    stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Resolve channel_id from message for access checks
    task_channel_id = None
    task_thread_id = None
    task_workspace_id = None
    if task.message_id:
        msg_stmt = select(Message).where(Message.id == task.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg:
            task_channel_id = msg.channel_id
            task_thread_id = msg.thread_id
            task_workspace_id = msg.workspace_id

    # Check access through channel membership
    if task_channel_id:
        channel_member_stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id == task_channel_id,
                ChannelMember.user_id == user.id,
                ChannelMember.is_active == True
            )
        )
        channel_member_result = await db.execute(channel_member_stmt)
        channel_member = channel_member_result.scalar_one_or_none()
        if not channel_member and str(task.created_by) != str(user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to task"
            )

    # Validate assigned user if provided
    if task_data.assigned_to:
        user_stmt = select(User).where(User.id == task_data.assigned_to)
        user_result = await db.execute(user_stmt)
        assigned_user = user_result.scalar_one_or_none()

        if not assigned_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Assigned user not found"
            )

        # Check if assigned user is in the same company
        if assigned_user.company_id != user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot assign task to user from different company"
            )

        # Validate that assigned user is a member of the channel (resolved via message)
        if task_channel_id:
            from app.models.channel_member import ChannelMember
            channel_member_stmt = select(ChannelMember).where(
                and_(
                    ChannelMember.channel_id == task_channel_id,
                    ChannelMember.user_id == task_data.assigned_to,
                    ChannelMember.is_active == True
                )
            )
            channel_member_result = await db.execute(channel_member_stmt)
            channel_member = channel_member_result.scalar_one_or_none()

            if not channel_member:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Assigned user must be a member of the channel to receive tasks"
                )
    
    # Update task fields
    update_data = task_data.dict(exclude_unset=True)
    
    # Check for reassignment before updating
    is_reassignment = False
    previous_assignee = None
    if 'assigned_to' in update_data and task.assigned_to != update_data['assigned_to']:
        is_reassignment = True
        previous_assignee = task.assigned_to
    
    # Handle status change
    if 'status' in update_data:
        if update_data['status'] == 'Close' and task.status != 'Close':
            # Use UTC time but convert to naive datetime for database compatibility
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        elif update_data['status'] != 'Close':
            task.completed_at = None
    
    # Update other fields
    for field, value in update_data.items():
        if hasattr(task, field):
            setattr(task, field, value)
    
    # Track reassignment in task metadata if this is a reassignment
    if is_reassignment:
        if not task.task_metadata:
            task.task_metadata = {}
        
        if 'assignee_changes' not in task.task_metadata:
            task.task_metadata['assignee_changes'] = []
        
        # Get current time for tracking
        current_time = datetime.now(timezone.utc).replace(tzinfo=None)
        
        # Add reassignment history
        task.task_metadata['assignee_changes'].append({
            'previous_assignee': str(previous_assignee) if previous_assignee else None,
            'new_assignee': str(update_data['assigned_to']),
            'changed_by': str(user.id),
            'changed_at': current_time.isoformat(),
            'action': 'reassigned'
        })
    
    # Use UTC time but convert to naive datetime for database compatibility
    task.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await audit_log_write(db, user.id, "task.updated", "task", task.id, channel_id=task.channel_id, thread_id=task.thread_id)
    await db.commit()
    
    # Process task reassignment notifications in background if reassigned
    if is_reassignment and task.assigned_to and task_channel_id and task_thread_id:
        # Get platform URL from environment variables for real-time notifications
        platform_url = os.environ.get("PLATFORM_URL") or settings.PLATFORM_URL

        # Construct redirect URL (shortened; store thread_id/channel_id for move-safe links)
        redirect_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{task_channel_id}/{task_thread_id}?openTask=true", db,
            thread_id=task_thread_id, channel_id=task_channel_id, entity_type="task",
        ) if platform_url else "#"
        # Construct notification settings URL (shortened; channel-level)
        notification_settings_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{task_channel_id}?openSettings=true&tab=notification", db,
            channel_id=task_channel_id, entity_type="channel",
        ) if platform_url else "#"

        background_tasks.add_task(
            process_task_reassignment_notifications,
            str(user.id),  # Reassigner ID
            str(task.assigned_to),  # Reassigned user ID
            str(task_channel_id),  # Channel ID
            redirect_url,  # Pre-constructed redirect URL
            notification_settings_url  # Pre-constructed notification settings URL
        )

    # Handle optional message content and attachments for task update
    if task_data.message_content or task_data.attachment_ids:
        from app.core.auth import generate_message_id
        from app.models.attachment import Attachment

        # Get the thread to create a message
        if task_thread_id:
            # Create a new message with the provided content
            new_message = Message(
                id=generate_message_id(),
                content=task_data.message_content or f"Task updated: {task.title}",
                message_type="user",
                thread_id=task_thread_id,
                channel_id=task_channel_id,
                workspace_id=task_workspace_id,
                user_id=user.id,
                sequence_number=1  # Will be updated by the message system
            )
            
            db.add(new_message)

            # Update channel metadata
            if task_channel_id:
                channel_stmt = select(Channel).where(Channel.id == task_channel_id)
                channel_result = await db.execute(channel_stmt)
                channel = channel_result.scalar_one_or_none()
                if channel:
                    channel.message_count += 1
                    channel.last_message_at = datetime.utcnow()

            await db.commit()
            await db.refresh(new_message)

            # Link attachments to the new message if provided
            if task_data.attachment_ids:
                for attachment_id in task_data.attachment_ids:
                    try:
                        attachment_uuid = uuid.UUID(attachment_id)
                        attachment_stmt = select(Attachment).where(
                            and_(
                                Attachment.id == attachment_uuid,
                                Attachment.channel_id == task_channel_id,
                                Attachment.user_id == user.id  # Ensure user owns the attachment
                            )
                        )
                        attachment_result = await db.execute(attachment_stmt)
                        attachment = attachment_result.scalar_one_or_none()

                        if attachment:
                            # Link attachment to the new message
                            attachment.message_id = new_message.id
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

                await db.commit()

    # Load checklists separately to avoid collection eager loading issues
    await db.refresh(task, attribute_names=['checklists'])

    # Load additional details manually
    details = await load_task_details(task, db)

    # Build response with details
    response = build_task_response(task, include_details=False)
    response.update(details)
    return response


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Delete a task"""
    user = await get_current_user_required(request, db)
    
    # Get task
    stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Check access through message -> channel membership
    if task.message_id:
        msg_stmt = select(Message).where(Message.id == task.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg and msg.channel_id:
            channel_member_stmt = select(ChannelMember).where(
                and_(
                    ChannelMember.channel_id == msg.channel_id,
                    ChannelMember.user_id == user.id,
                    ChannelMember.is_active == True
                )
            )
            channel_member_result = await db.execute(channel_member_stmt)
            channel_member = channel_member_result.scalar_one_or_none()
            if not channel_member and str(task.created_by) != str(user.id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to task"
                )

    # Delete task
    
    await audit_log_write(db, user.id, "task.deleted", "task", task.id, channel_id=task.channel_id, thread_id=task.thread_id)
    await db.delete(task)
    await db.commit()

    return {"message": "Task deleted successfully"}


@router.post("/{task_id}/assign", response_model=TaskResponse)
async def assign_task(
    task_id: str,
    assignment_data: TaskAssignmentRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Assign a task to a user"""
    user = await get_current_user_required(request, db)
    
    # Get task without eager loading to avoid collection issues
    stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Resolve channel_id from message for access checks
    assign_channel_id = None
    assign_thread_id = None
    if task.message_id:
        msg_stmt = select(Message).where(Message.id == task.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg:
            assign_channel_id = msg.channel_id
            assign_thread_id = msg.thread_id

    # Check access through channel membership
    if assign_channel_id:
        channel_member_stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id == assign_channel_id,
                ChannelMember.user_id == user.id,
                ChannelMember.is_active == True
            )
        )
        channel_member_result = await db.execute(channel_member_stmt)
        channel_member = channel_member_result.scalar_one_or_none()
        if not channel_member and str(task.created_by) != str(user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to task"
            )

    # Validate assigned user
    user_stmt = select(User).where(User.id == assignment_data.assigned_to)
    user_result = await db.execute(user_stmt)
    assigned_user = user_result.scalar_one_or_none()

    if not assigned_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assigned user not found"
        )

    # Check if assigned user is in the same company
    if assigned_user.company_id != user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot assign task to user from different company"
        )

    # Validate that assigned user is a member of the channel (resolved via message)
    if assign_channel_id:
        from app.models.channel_member import ChannelMember
        channel_member_stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id == assign_channel_id,
                ChannelMember.user_id == assignment_data.assigned_to,
                ChannelMember.is_active == True
            )
        )
        channel_member_result = await db.execute(channel_member_stmt)
        channel_member = channel_member_result.scalar_one_or_none()

        if not channel_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Assigned user must be a member of the channel to receive tasks"
            )

    # Check if this is a reassignment (different from current assignee)
    is_reassignment = task.assigned_to != assignment_data.assigned_to
    previous_assignee = task.assigned_to
    
    # Assign task
    task.assigned_to = assignment_data.assigned_to
    # Use UTC time but convert to naive datetime for database compatibility
    task.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    
    # Track reassignment in task metadata if this is a reassignment
    if is_reassignment:
        if not task.task_metadata:
            task.task_metadata = {}
        
        if 'assignee_changes' not in task.task_metadata:
            task.task_metadata['assignee_changes'] = []
        
        # Get current time for tracking
        current_time = datetime.now(timezone.utc).replace(tzinfo=None)
        
        # Add reassignment history
        task.task_metadata['assignee_changes'].append({
            'previous_assignee': str(previous_assignee) if previous_assignee else None,
            'new_assignee': str(assignment_data.assigned_to),
            'changed_by': str(user.id),
            'changed_at': current_time.isoformat(),
            'action': 'reassigned'
        })
    
    await audit_log_write(db, user.id, "task.assigned", "task", task.id, channel_id=task.channel_id, thread_id=task.thread_id, details={"assignee_id": str(assignment_data.assigned_to)})
    await db.commit()
    
    # Process task reassignment notifications in background if reassigned
    if is_reassignment and task.assigned_to and assign_channel_id and assign_thread_id:
        # Get platform URL from environment variables for real-time notifications
        platform_url = os.environ.get("PLATFORM_URL") or settings.PLATFORM_URL

        # Construct redirect URL (shortened; store thread_id/channel_id for move-safe links)
        redirect_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{assign_channel_id}/{assign_thread_id}?openTask=true", db,
            thread_id=assign_thread_id, channel_id=assign_channel_id, entity_type="task",
        ) if platform_url else "#"
        # Construct notification settings URL (shortened; channel-level)
        notification_settings_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{assign_channel_id}?openSettings=true&tab=notification", db,
            channel_id=assign_channel_id, entity_type="channel",
        ) if platform_url else "#"

        background_tasks.add_task(
            process_task_reassignment_notifications,
            str(user.id),  # Reassigner ID
            str(task.assigned_to),  # Reassigned user ID
            str(assign_channel_id),  # Channel ID
            redirect_url,  # Pre-constructed redirect URL
            notification_settings_url  # Pre-constructed notification settings URL
        )

    # Load checklists separately to avoid collection eager loading issues
    await db.refresh(task, attribute_names=['checklists'])

    # Load additional details manually
    details = await load_task_details(task, db)

    # Build response with details
    response = build_task_response(task, include_details=False)
    response.update(details)
    return response


@router.post("/{task_id}/status", response_model=TaskResponse)
async def update_task_status(
    task_id: str,
    status_data: TaskStatusUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Update task status"""
    user = await get_current_user_required(request, db)
    
    # Get task without eager loading to avoid collection issues
    stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Resolve channel/thread/workspace from message for access checks and message creation
    status_channel_id = None
    status_thread_id = None
    status_workspace_id = None
    if task.message_id:
        msg_stmt = select(Message).where(Message.id == task.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg:
            status_channel_id = msg.channel_id
            status_thread_id = msg.thread_id
            status_workspace_id = msg.workspace_id

    # Check access through channel membership
    if status_channel_id:
        channel_member_stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id == status_channel_id,
                ChannelMember.user_id == user.id,
                ChannelMember.is_active == True
            )
        )
        channel_member_result = await db.execute(channel_member_stmt)
        channel_member = channel_member_result.scalar_one_or_none()
        if not channel_member and str(task.created_by) != str(user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to task"
            )

    # Update status
    task.status = status_data.status
    
    # Handle completion
    if status_data.status == 'Close' and task.status != 'Close':
        # Use UTC time but convert to naive datetime for database compatibility
        task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    elif status_data.status != 'Close':
        task.completed_at = None
    
    # Update metadata with status change comment if provided
    if status_data.comments:
        if not task.task_metadata:
            task.task_metadata = {}
        
        if 'status_changes' not in task.task_metadata:
            task.task_metadata['status_changes'] = []
        
        # Use UTC time but convert to naive datetime for database compatibility
        current_time = datetime.now(timezone.utc).replace(tzinfo=None)
        
        task.task_metadata['status_changes'].append({
            'status': status_data.status,
            'changed_by': str(user.id),
            'changed_at': current_time.isoformat(),
            'comments': status_data.comments
        })
    
    # Use UTC time but convert to naive datetime for database compatibility
    task.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await audit_log_write(db, user.id, "task.status_updated", "task", task.id, channel_id=task.channel_id, thread_id=task.thread_id, details={"status": status_data.status})
    await db.commit()
    
    # Handle optional message content and attachments for status update
    if status_data.message_content or status_data.attachment_ids:
        from app.core.auth import generate_message_id
        from app.models.attachment import Attachment

        # Get the thread to create a message
        if status_thread_id:
            # Create a new message with the provided content
            new_message = Message(
                id=generate_message_id(),
                content=status_data.message_content or f"Task status updated to {status_data.status}",
                message_type="user",
                thread_id=status_thread_id,
                channel_id=status_channel_id,
                workspace_id=status_workspace_id,
                user_id=user.id,
                sequence_number=1  # Will be updated by the message system
            )

            db.add(new_message)

            # Update channel metadata
            if status_channel_id:
                channel_stmt = select(Channel).where(Channel.id == status_channel_id)
                channel_result = await db.execute(channel_stmt)
                channel = channel_result.scalar_one_or_none()
                if channel:
                    channel.message_count += 1
                    channel.last_message_at = datetime.utcnow()

            await db.commit()
            await db.refresh(new_message)

            # Link attachments to the new message if provided
            if status_data.attachment_ids:
                for attachment_id in status_data.attachment_ids:
                    try:
                        attachment_uuid = uuid.UUID(attachment_id)
                        attachment_stmt = select(Attachment).where(
                            and_(
                                Attachment.id == attachment_uuid,
                                Attachment.channel_id == status_channel_id,
                                Attachment.user_id == user.id  # Ensure user owns the attachment
                            )
                        )
                        attachment_result = await db.execute(attachment_stmt)
                        attachment = attachment_result.scalar_one_or_none()

                        if attachment:
                            # Link attachment to the new message
                            attachment.message_id = new_message.id
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

                await db.commit()

    # Refresh the task object to ensure all fields are properly loaded
    await db.refresh(task)

    # Build a simple response to avoid async issues
    response = {
        'id': str(task.id),
        'title': task.title,
        'description': task.description,
        'status': task.status,
        'source': task.source,
        'due_date': format_due_date_for_response(task.due_date),
        'priority': task.priority,
        'tags': task.tags,
        'task_metadata': task.task_metadata,
        'assigned_to': str(task.assigned_to) if task.assigned_to else None,
        'created_by': str(task.created_by) if task.created_by else None,
        'message_id': str(task.message_id) if task.message_id else None,
        'created_at': task.created_at,
        'updated_at': task.updated_at,
        'completed_at': task.completed_at.isoformat() if task.completed_at else None,
        'checklists': []
    }

    return response


@router.get("/stats/overview", response_model=TaskStats)
async def get_task_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    workspace_id: Optional[str] = Query(None, description="Filter by workspace"),
    channel_id: Optional[str] = Query(None, description="Filter by channel")
):
    """Get task statistics"""
    user = await get_current_user_required(request, db)
    
    # Build base query for accessible channels (via company workspaces)
    workspace_query = select(Workspace.id).where(Workspace.company_id == user.company_id)
    if workspace_id:
        workspace_query = workspace_query.where(Workspace.id == workspace_id)

    workspace_result = await db.execute(workspace_query)
    accessible_workspaces = [str(w) for w in workspace_result.scalars().all()]

    if not accessible_workspaces:
        return TaskStats(
            total_tasks=0,
            open_tasks=0,
            in_progress_tasks=0,
            on_hold_tasks=0,
            closed_tasks=0,
            urgent_tasks=0
        )

    # Find channels in those workspaces
    channels_query = select(Channel.id).where(Channel.workspace_id.in_(accessible_workspaces))
    if channel_id:
        channels_query = channels_query.where(Channel.id == channel_id)
    channels_result = await db.execute(channels_query)
    accessible_channel_ids = [row[0] for row in channels_result.all()]

    if not accessible_channel_ids:
        return TaskStats(
            total_tasks=0,
            open_tasks=0,
            in_progress_tasks=0,
            on_hold_tasks=0,
            closed_tasks=0,
            urgent_tasks=0
        )

    # Find message IDs in those channels
    msg_ids_query = select(Message.id).where(Message.channel_id.in_(accessible_channel_ids))
    msg_ids_result = await db.execute(msg_ids_query)
    accessible_message_ids = [row[0] for row in msg_ids_result.all()]

    if not accessible_message_ids:
        return TaskStats(
            total_tasks=0,
            open_tasks=0,
            in_progress_tasks=0,
            on_hold_tasks=0,
            closed_tasks=0,
            urgent_tasks=0
        )

    # Build task query
    task_query = select(Task).where(Task.message_id.in_(accessible_message_ids))
    
    # Get all tasks for stats
    result = await db.execute(task_query)
    tasks = result.scalars().all()
    
    # Calculate stats
    total_tasks = len(tasks)
    open_tasks = len([t for t in tasks if t.status == 'Open'])
    in_progress_tasks = len([t for t in tasks if t.status == 'In Progress'])
    on_hold_tasks = len([t for t in tasks if t.status == 'On Hold'])
    closed_tasks = len([t for t in tasks if t.status == 'Close'])
    overdue_tasks = len([t for t in tasks if t.is_overdue])
    urgent_tasks = len([t for t in tasks if t.is_urgent])
    
    return TaskStats(
        total_tasks=total_tasks,
        open_tasks=open_tasks,
        in_progress_tasks=in_progress_tasks,
        on_hold_tasks=on_hold_tasks,
        closed_tasks=closed_tasks,
        overdue_tasks=overdue_tasks,
        urgent_tasks=urgent_tasks
    )


@router.get("/thread/{thread_id}", response_model=TaskResponse)
async def get_thread_task(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get task associated with a specific thread"""
    user = await get_current_user_required(request, db)
    
    # Get thread
    thread_stmt = select(Thread).where(Thread.id == thread_id)
    thread_result = await db.execute(thread_stmt)
    thread = thread_result.scalar_one_or_none()
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )
    
    # Check access through channel
    channel_stmt = select(Channel).where(Channel.id == thread.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()
    
    if not channel or not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to thread"
        )
    
    # Get task for this thread: find tasks whose message_id belongs to a message in this thread
    thread_msg_ids_stmt = select(Message.id).where(Message.thread_id == thread_id)
    thread_msg_ids_result = await db.execute(thread_msg_ids_stmt)
    thread_msg_ids = [row[0] for row in thread_msg_ids_result.all()]

    task = None
    if thread_msg_ids:
        task_stmt = select(Task).where(Task.message_id.in_(thread_msg_ids)).order_by(desc(Task.created_at)).limit(1)
        task_result = await db.execute(task_stmt)
        task = task_result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No task found for this thread"
        )
    
    # Load checklists separately to avoid collection eager loading issues
    await db.refresh(task, attribute_names=['checklists'])
    
    # Load additional details manually
    details = await load_task_details(task, db)
    
    # Build response with details
    response = build_task_response(task, include_details=False)
    response.update(details)
    return response


@router.get("/thread/{thread_id}/status")
async def get_thread_task_status(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Check if a thread can accept new tasks (one active task per thread limit)"""
    user = await get_current_user_required(request, db)
    
    # Get thread
    thread_stmt = select(Thread).where(Thread.id == thread_id)
    thread_result = await db.execute(thread_stmt)
    thread = thread_result.scalar_one_or_none()
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )
    
    # Check access through channel
    channel_stmt = select(Channel).where(Channel.id == thread.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()
    
    if not channel or not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to thread"
        )
    
    # Check for existing active tasks (via message IDs in this thread)
    thread_msg_ids_stmt = select(Message.id).where(Message.thread_id == thread_id)
    thread_msg_ids_result = await db.execute(thread_msg_ids_stmt)
    thread_msg_ids = [row[0] for row in thread_msg_ids_result.all()]

    existing_task = None
    if thread_msg_ids:
        existing_task_stmt = select(Task).where(
            and_(
                Task.message_id.in_(thread_msg_ids),
                Task.status.in_(["Open", "In Progress", "On Hold"])
            )
        )
        existing_task_result = await db.execute(existing_task_stmt)
        existing_task = existing_task_result.scalar_one_or_none()

    if existing_task:
        return {
            "thread_id": thread_id,
            "can_create_task": False,
            "existing_task": {
                "id": str(existing_task.id),
                "title": existing_task.title,
                "status": existing_task.status,
                "assigned_to": str(existing_task.assigned_to) if existing_task.assigned_to else None,
                "created_at": existing_task.created_at,
                "due_date": format_due_date_for_response(existing_task.due_date)
            },
            "message": f"Thread already has an active task: {existing_task.title}"
        }
    else:
        return {
            "thread_id": thread_id,
            "can_create_task": True,
            "existing_task": None,
            "message": "Thread can accept new tasks"
        }


@router.post("/thread/{thread_id}/create", response_model=TaskResponse)
async def create_thread_task(
    thread_id: str,
    task_data: TaskCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Create a task for a specific thread (usually from first message)"""
    user = await get_current_user_required(request, db)
    
    # Get thread
    thread_stmt = select(Thread).where(Thread.id == thread_id)
    thread_result = await db.execute(thread_stmt)
    thread = thread_result.scalar_one_or_none()
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )
    
    # Check access through channel
    channel_stmt = select(Channel).where(Channel.id == thread.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()
    
    if not channel or not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to thread"
        )
    
    # Get first message in thread for context
    first_message_stmt = select(Message).where(
        Message.thread_id == thread_id
    ).order_by(Message.sequence_number).limit(1)
    first_message_result = await db.execute(first_message_stmt)
    first_message = first_message_result.scalar_one_or_none()

    # Check if there's already an active task in this thread (via message IDs)
    thread_msg_ids_stmt = select(Message.id).where(Message.thread_id == thread_id)
    thread_msg_ids_result = await db.execute(thread_msg_ids_stmt)
    thread_msg_ids = [row[0] for row in thread_msg_ids_result.all()]

    if thread_msg_ids:
        existing_task_stmt = select(Task).where(
            and_(
                Task.message_id.in_(thread_msg_ids),
                Task.status.in_(["Open", "In Progress", "On Hold"])  # Active statuses
            )
        )
        existing_task_result = await db.execute(existing_task_stmt)
        existing_task = existing_task_result.scalar_one_or_none()

        if existing_task:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot create task: Thread already has an active task '{existing_task.title}' (ID: {existing_task.id}) with status '{existing_task.status}'. Only one active task allowed per thread."
            )

    # Create task linked via message_id only (no workspace_id/channel_id/thread_id columns)
    task = Task(
        id=uuid.uuid4(),  # Pass UUID object directly, not string
        title=task_data.title or f"Task for Thread {thread.title or str(thread.id)[:8]}",
        description=task_data.description or (first_message.content[:200] + "..." if first_message and len(first_message.content) > 200 else first_message.content if first_message else None),
        assigned_to=task_data.assigned_to,
        created_by=user.id,
        status=task_data.status,
        source=task_data.source or "manual",
        due_date=task_data.due_date,
        message_id=first_message.id if first_message else None,
        priority=task_data.priority,
        tags=task_data.tags,
        task_metadata={
            **(task_data.task_metadata or {}),
            "thread_title": thread.title,
            "channel_name": channel.name,
            "created_from_message": str(first_message.id) if first_message else None
        }
    )
    
    db.add(task)
    await audit_log_write(db, user.id, "task.created", "task", task.id, channel_id=thread.channel_id, thread_id=thread.id)
    await db.commit()
    # Load checklists separately to avoid collection eager loading issues
    await db.refresh(task, attribute_names=['checklists'])
    
    # Load additional details manually
    details = await load_task_details(task, db)
    
    # Build response with details
    response = build_task_response(task, include_details=False)
    response.update(details)
    return response
