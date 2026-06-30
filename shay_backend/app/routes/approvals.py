"""
Approval Routes for Thread-Level Message Approvals

This module provides FastAPI routes for managing thread-level message approval
workflows. It handles approval creation, status updates, reassignments, and
various approval-related operations.

Features:
- Create approval requests for thread messages
- List and filter approvals with pagination
- Take approval actions (approve/reject)
- Reassign approvals to different users
- Update approval details
- Get approval statistics
- Soft delete approvals

Author: Karthick Chandrasekar
Date: 19-08-2025
Version: 1.0.0

API Base Path: /api/v1/approvals
"""

# Type hints for function parameters and return values
import os
from typing import List, Optional, Dict, Any
# FastAPI framework components for routing and HTTP handling
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query, BackgroundTasks
# SQLAlchemy async session management
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
# SQLAlchemy query building and database operations
from sqlalchemy import select, func, and_, or_
# Date and time handling with timezone support
from datetime import datetime, timezone, timedelta
# UUID handling for database identifiers
from uuid import UUID

# Database session management
from app.core.database import get_db
from app.core.config import settings
# Utility functions for ID generation
from app.core.auth import generate_approval_id
# Authentication middleware for user validation
from app.middleware.auth_middleware import get_current_user_required
from app.utils.channel_access import check_channel_access_by_thread
from app.services.audit_service import log as audit_log_write
from app.services.email_service import email_service
from app.services.link_shortener_service import link_shortener_service
from app.models.realtime_notification import RealtimeNotification
# Database models for approval system
from app.models.approval import Approval
from app.models.message import Thread, Message
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.user import User
from app.models.workspace import Workspace
# Pydantic schemas for request/response validation
from app.schemas.approval import (
    ApprovalCreate,
    ApprovalUpdate,
    ApprovalAction,
    ApprovalReassign,
    ApprovalResponse,
    ApprovalWithDetailsResponse,
    ApprovalList,
    ApprovalStats,
    ApprovalHistoryItem,
    ApprovalDetails,
    EnhancedApprovalResponse,
    ApprovalListResponse,
    ApprovalCountResponse,
)

router = APIRouter()


async def get_channel_members_with_approval_notifications_enabled(
    channel_id: UUID,
    approval_creator_id: UUID,
    db: AsyncSession
) -> List[User]:
    """
    Get all channel members who have approval notifications enabled.
    Excludes the approval creator.
    
    Logic:
    - Get all active channel members
    - For each member, check gg_realtime_notification table
    - Only include if:
      1. Data exists in table
      2. is_notifications_enabled = true
      3. is_approval_enabled = true
    - Exclude approval creator
    
    Args:
        channel_id: Channel ID
        approval_creator_id: User ID who created the approval (will be excluded)
        db: Database session
        
    Returns:
        List of User objects who have approval notifications enabled
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
        # Skip approval creator
        if member.user_id == approval_creator_id:
            continue
        
        # Check if notification preference exists
        notification_pref = notification_map.get(member.user_id)
        
        # Only send if data exists AND both flags are enabled
        if notification_pref:
            if notification_pref.is_notifications_enabled and notification_pref.is_approval_enabled:
                enabled_user_ids.append(member.user_id)
    
    if not enabled_user_ids:
        return []
    
    # Get user details for enabled members
    users_stmt = select(User).where(User.id.in_(enabled_user_ids))
    users_result = await db.execute(users_stmt)
    users = users_result.scalars().all()
    
    return list(users)


async def send_approval_notification_email(
    recipient_user: User,
    approval_creator: User,
    approver_user: User,
    channel: Channel,
    redirect_url: str,
    notification_settings_url: str,
    db: AsyncSession
) -> bool:
    """
    Send approval notification email to a channel member.
    
    Args:
        recipient_user: User who will receive the notification
        approval_creator: User who created/requested the approval
        approver_user: User who needs to approve
        channel: Channel where the approval was created
        redirect_url: URL to redirect to view the approval
        notification_settings_url: URL to notification settings page
        db: Database session
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Load the approval notification template
        template = email_service._load_template('approval_notification.html')
        
        # Get platform name from config
        platform_name = settings.PLATFORM_NAME
        
        # Prepare template variables
        template_variables = {
            'user': approval_creator.name or approval_creator.email_id or 'Someone',
            'approval_user': approver_user.name or approver_user.email_id or 'User',
            'approval_user_email': approver_user.email_id or '',
            'approval_user_role': approver_user.role or 'user',
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
        msg['Subject'] = f"Approval requested in {channel.name or 'a channel'}"
        
        # Attach HTML version only (no plain text)
        msg.attach(MIMEText(processed_html, 'html'))
        
        # Send email
        result = email_service._send_email(msg)
        
        if result:
            print(f"✅ Approval notification email sent successfully to {recipient_user.email_id}")
        else:
            print(f"❌ Failed to send approval notification email to {recipient_user.email_id}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error sending approval notification email to {recipient_user.email_id}: {e}")
        import traceback
        print(f"📋 Error traceback: {traceback.format_exc()}")
        return False


async def send_approval_reassignment_notification_email(
    recipient_user: User,
    reassigner: User,
    reassigned_approver: User,
    channel: Channel,
    redirect_url: str,
    notification_settings_url: str,
    db: AsyncSession
) -> bool:
    """
    Send approval reassignment notification email to a channel member.
    
    Args:
        recipient_user: User who will receive the notification
        reassigner: User who reassigned the approval
        reassigned_approver: User who was reassigned to approve
        channel: Channel where the approval was reassigned
        redirect_url: URL to redirect to view the approval
        notification_settings_url: URL to notification settings page
        db: Database session
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Load the approval reassign notification template
        template = email_service._load_template('approval_reassign_notification.html')
        
        # Get platform name from config
        platform_name = settings.PLATFORM_NAME
        
        # Prepare template variables
        template_variables = {
            'user': reassigner.name or reassigner.email_id or 'Someone',
            'reassigned_approval_user': reassigned_approver.name or reassigned_approver.email_id or 'User',
            'reassigned_approval_user_email': reassigned_approver.email_id or '',
            'reassigned_approval_user_role': reassigned_approver.role or 'user',
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
        msg['Subject'] = f"Approval reassigned in {channel.name or 'a channel'}"
        
        # Attach HTML version only (no plain text)
        msg.attach(MIMEText(processed_html, 'html'))
        
        # Send email
        result = email_service._send_email(msg)
        
        if result:
            print(f"✅ Approval reassignment notification email sent successfully to {recipient_user.email_id}")
        else:
            print(f"❌ Failed to send approval reassignment notification email to {recipient_user.email_id}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error sending approval reassignment notification email to {recipient_user.email_id}: {e}")
        import traceback
        print(f"📋 Error traceback: {traceback.format_exc()}")
        return False


async def process_approval_reassignment_notifications(
    reassigner_id: str,
    reassigned_approver_id: str,
    channel_id: str,
    redirect_url: str,
    notification_settings_url: str
) -> None:
    """
    Process approval reassignment notifications for channel members.
    This function creates its own database session for background processing.
    
    Args:
        reassigner_id: UUID string of the user who reassigned the approval
        reassigned_approver_id: UUID string of the user reassigned to approve
        channel_id: UUID string of the channel where approval was reassigned
        redirect_url: Pre-constructed URL to redirect to view the approval
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
            
            # Get reassigned approver
            approver_stmt = select(User).where(User.id == UUID(reassigned_approver_id))
            approver_result = await db.execute(approver_stmt)
            reassigned_approver = approver_result.scalar_one_or_none()
            
            if not reassigned_approver:
                print(f"⚠️ Reassigned approver not found: {reassigned_approver_id}")
                return
            
            # Get channel
            channel_stmt = select(Channel).where(Channel.id == UUID(channel_id))
            channel_result = await db.execute(channel_stmt)
            channel = channel_result.scalar_one_or_none()
            
            if not channel:
                print(f"⚠️ Channel not found: {channel_id}")
                return
            
            # Get channel members with approval notifications enabled
            enabled_members = await get_channel_members_with_approval_notifications_enabled(
                channel.id,
                reassigner.id,
                db
            )
            
            if not enabled_members:
                print(f"ℹ️ No channel members with approval notifications enabled for channel {channel_id}")
                return
            
            # Send notification to each enabled member with pre-constructed URLs
            for member in enabled_members:
                await send_approval_reassignment_notification_email(
                    member,
                    reassigner,
                    reassigned_approver,
                    channel,
                    redirect_url,
                    notification_settings_url,
                    db
                )
        
        except Exception as e:
            print(f"❌ Error processing approval reassignment notifications: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")


async def process_approval_notifications(
    approval_creator_id: str,
    approver_user_id: str,
    channel_id: str,
    redirect_url: str,
    notification_settings_url: str
) -> None:
    """
    Process approval notifications for channel members.
    This function creates its own database session for background processing.
    
    Args:
        approval_creator_id: UUID string of the user who created the approval
        approver_user_id: UUID string of the user who needs to approve
        channel_id: UUID string of the channel where approval was created
        redirect_url: Pre-constructed URL to redirect to view the approval
        notification_settings_url: Pre-constructed URL to notification settings page
    """
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get approval creator
            creator_stmt = select(User).where(User.id == UUID(approval_creator_id))
            creator_result = await db.execute(creator_stmt)
            approval_creator = creator_result.scalar_one_or_none()
            
            if not approval_creator:
                print(f"⚠️ Approval creator not found: {approval_creator_id}")
                return
            
            # Get approver user
            approver_stmt = select(User).where(User.id == UUID(approver_user_id))
            approver_result = await db.execute(approver_stmt)
            approver_user = approver_result.scalar_one_or_none()
            
            if not approver_user:
                print(f"⚠️ Approver user not found: {approver_user_id}")
                return
            
            # Get channel
            channel_stmt = select(Channel).where(Channel.id == UUID(channel_id))
            channel_result = await db.execute(channel_stmt)
            channel = channel_result.scalar_one_or_none()
            
            if not channel:
                print(f"⚠️ Channel not found: {channel_id}")
                return
            
            # Get channel members with approval notifications enabled
            enabled_members = await get_channel_members_with_approval_notifications_enabled(
                channel.id,
                approval_creator.id,
                db
            )
            
            if not enabled_members:
                print(f"ℹ️ No channel members with approval notifications enabled for channel {channel_id}")
                return
            
            # Send notification to each enabled member with pre-constructed URLs
            for member in enabled_members:
                await send_approval_notification_email(
                    member,
                    approval_creator,
                    approver_user,
                    channel,
                    redirect_url,
                    notification_settings_url,
                    db
                )
        
        except Exception as e:
            print(f"❌ Error processing approval notifications: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")


# Helper functions for approval history and details
async def load_approval_details(approval: Approval, db: AsyncSession) -> Dict[str, Any]:
    """
    Load detailed user information for an approval.
    
    Args:
        approval (Approval): The approval object
        db (AsyncSession): Database session
        
    Returns:
        Dict[str, Any]: Dictionary containing user details
    """
    details = {}
    
    # Load approver user details
    if approval.approver_user_id:
        approver_stmt = select(User).where(User.id == approval.approver_user_id)
        approver_result = await db.execute(approver_stmt)
        approver_user = approver_result.scalar_one_or_none()
        
        if approver_user:
            details['approver_user'] = {
                'id': str(approver_user.id),
                'name': approver_user.name,
                'email_id': approver_user.email_id,
                'avatar_url': approver_user.avatar_url,
                'username': approver_user.name or 'unknown'  # Use name as username fallback
            }
    
    # Load requested by user details
    if approval.requested_by_user_id:
        requester_stmt = select(User).where(User.id == approval.requested_by_user_id)
        requester_result = await db.execute(requester_stmt)
        requester_user = requester_result.scalar_one_or_none()
        
        if requester_user:
            details['requested_by_user'] = {
                'id': str(requester_user.id),
                'name': requester_user.name,
                'email_id': requester_user.email_id,
                'avatar_url': requester_user.avatar_url,
                'username': requester_user.name or 'unknown'  # Use name as username fallback
            }
    
    return details


async def get_last_requester_from_reassignments(approval: Approval, db: AsyncSession) -> Optional[Dict[str, Any]]:
    """
    Get the last person who requested approval to somebody from reassignments.
    
    Args:
        approval (Approval): The approval object
        db (AsyncSession): Database session
        
    Returns:
        Optional[Dict[str, Any]]: User details of the last requester, or None if no reassignments
    """
    metadata = approval.approval_metadata or {}
    reassignments = metadata.get('reassignments', [])
    
    if not reassignments:
        return None
    
    # Get the last reassignment (most recent)
    last_reassignment = reassignments[-1]
    last_requester_id = last_reassignment.get('reassigned_by')
    
    if not last_requester_id:
        return None
    
    # Get user details for the last requester
    user_stmt = select(User).where(User.id == last_requester_id)
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one_or_none()
    
    if user:
        return {
            'id': str(user.id),
            'name': user.name,
            'email_id': user.email_id,
            'avatar_url': user.avatar_url,
            'username': user.name or 'unknown'
        }
    
    return None


async def build_approval_details(approval: Approval, db: AsyncSession) -> Dict[str, Any]:
    """
    Build detailed approval information.
    
    Args:
        approval (Approval): The approval object
        db (AsyncSession): Database session
        
    Returns:
        Dict[str, Any]: Detailed approval information
    """
    # Load user details
    user_details = await load_approval_details(approval, db)
    
    # Get the original creator (currently shown as requested_by)
    created_by = user_details.get('requested_by_user')
    
    # Get the last person who requested approval to somebody (from reassignments)
    requested_by = await get_last_requester_from_reassignments(approval, db)
    
    # If no reassignments, the original creator is also the last requester
    if not requested_by:
        requested_by = created_by
    
    return {
        'approval_name': approval.title,
        'status': approval.status,
        'approver': user_details.get('approver_user'),
        'created_by': created_by,
        'requested_by': requested_by,
        'title': approval.title,
        'description': approval.description,
        'approval_notes': approval.approval_notes,
        'rejection_reason': approval.rejection_reason,
        'comment': approval.comment,
        'created_at': approval.created_at,
        'updated_at': approval.updated_at,
        'approved_at': approval.approved_at,
        'rejected_at': approval.rejected_at,
        'approval_metadata': approval.approval_metadata or {}
    }


async def build_approval_history(approval: Approval, db: AsyncSession) -> List[Dict[str, Any]]:
    """
    Build approval history from metadata and approval data.
    This function now uses the same logic as the new history endpoint.
    
    Args:
        approval (Approval): The approval object
        db (AsyncSession): Database session
        
    Returns:
        List[Dict[str, Any]]: List of approval history items
    """
    history = []
    
    # Get metadata or initialize empty dict
    metadata = approval.approval_metadata or {}
    
    # Add initial creation and assignment
    initial_assignment = None
    if metadata and 'initial_assignment' in metadata:
        initial_assignment = metadata['initial_assignment']
    
    if initial_assignment:
        # Get user details for the initial assignment
        assigned_by_user = None
        if initial_assignment.get('assigned_by'):
            user_stmt = select(User).where(User.id == initial_assignment['assigned_by'])
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()
            if user:
                assigned_by_user = {
                    'id': str(user.id),
                    'name': user.name,
                    'email_id': user.email_id,
                    'avatar_url': user.avatar_url,
                    'username': user.name or 'unknown'
                }
        
        if assigned_by_user:
            from datetime import datetime
            # Parse timestamp
            assigned_at = None
            if initial_assignment.get('assigned_at'):
                try:
                    assigned_at = datetime.fromisoformat(initial_assignment['assigned_at'].replace('Z', '+00:00'))
                    if assigned_at.tzinfo:
                        assigned_at = assigned_at.replace(tzinfo=None)
                except:
                    assigned_at = approval.created_at
            else:
                assigned_at = approval.created_at
            
            history.append({
                'action': 'Assigned to',
                'details': f'Assigned the approval to {initial_assignment.get("assigned_to_name", "Unknown User")}@{initial_assignment.get("assigned_to_name", "unknown")} and set the status to Pending Approval',
                'timestamp': assigned_at,
                'user': assigned_by_user,
                'metadata': {
                    'assigned_to': initial_assignment.get('assigned_to_name'),
                    'title': approval.title,
                    'description': approval.description
                }
            })
    else:
        # Fallback for older approvals without initial assignment tracking
        # Load user details
        user_details = await load_approval_details(approval, db)
        requester_user = user_details.get('requested_by_user')
        approver_user = user_details.get('approver_user')
        
        # Add approval creation history
        if requester_user:
            history.append({
                'action': 'Approval Created',
                'details': f'Approval "{approval.title}" created by {requester_user["name"]}',
                'timestamp': approval.created_at - timedelta(seconds=1),  # Ensure it appears first
                'user': requester_user,
                'metadata': {
                    'title': approval.title,
                    'description': approval.description
                }
            })
        
        # Add initial assignment history
        if approver_user:
            history.append({
                'action': 'Assigned to',
                'details': f'Assigned the approval to {approver_user["name"]}@{approver_user.get("username", "unknown")} and set the status to Pending Approval',
                'timestamp': approval.created_at + timedelta(seconds=1),  # Ensure it appears after creation
                'user': approver_user,
                'metadata': {
                    'status': approval.status
                }
            })
    
    # Add reassignments
    if metadata and 'reassignments' in metadata:
        for reassignment in metadata['reassignments']:
            # Get user details for the reassignment
            reassigned_by_user = None
            if reassignment.get('reassigned_by'):
                user_stmt = select(User).where(User.id == reassignment['reassigned_by'])
                user_result = await db.execute(user_stmt)
                user = user_result.scalar_one_or_none()
                if user:
                    reassigned_by_user = {
                        'id': str(user.id),
                        'name': user.name,
                        'email_id': user.email_id,
                        'avatar_url': user.avatar_url,
                        'username': user.name or 'unknown'
                    }
            
            if reassigned_by_user:
                from datetime import datetime
                # Parse timestamp
                if isinstance(reassignment.get('reassigned_at'), str):
                    try:
                        reassigned_at = datetime.fromisoformat(reassignment['reassigned_at'].replace('Z', '+00:00'))
                        if reassigned_at.tzinfo:
                            reassigned_at = reassigned_at.replace(tzinfo=None)
                    except:
                        reassigned_at = approval.updated_at
                else:
                    reassigned_at = approval.updated_at
                
                history.append({
                    'action': 'Reassigned',
                    'details': f'Assigned the approval to {reassignment.get("new_approver_name", "Unknown User")}@{reassignment.get("new_approver_name", "unknown")} and set the status to Pending Approval',
                    'timestamp': reassigned_at,
                    'user': reassigned_by_user,
                    'metadata': {
                        'previous_approver': reassignment.get('previous_approver_name'),
                        'new_approver': reassignment.get('new_approver_name'),
                        'notes': reassignment.get('notes'),
                        'status_reset': reassignment.get('status_reset', False)
                    }
                })
    
    # Add status changes
    if metadata and 'status_changes' in metadata:
        for status_change in metadata['status_changes']:
            if status_change.get('action_type') == 'reassignment_reset':
                continue  # Skip reassignment resets as they're covered in reassignments
            
            # Get user details for the change
            changed_by_user = None
            if status_change.get('changed_by'):
                user_stmt = select(User).where(User.id == status_change['changed_by'])
                user_result = await db.execute(user_stmt)
                user = user_result.scalar_one_or_none()
                if user:
                    changed_by_user = {
                        'id': str(user.id),
                        'name': user.name,
                        'email_id': user.email_id,
                        'avatar_url': user.avatar_url,
                        'username': user.name or 'unknown'
                    }
            
            if changed_by_user:
                from datetime import datetime
                # Parse timestamp
                if isinstance(status_change.get('changed_at'), str):
                    try:
                        changed_at = datetime.fromisoformat(status_change['changed_at'].replace('Z', '+00:00'))
                        if changed_at.tzinfo:
                            changed_at = changed_at.replace(tzinfo=None)
                    except:
                        changed_at = approval.updated_at
                else:
                    changed_at = approval.updated_at
                
                action_description = ""
                if status_change['new_status'] == 'approved':
                    action_description = "Changed the approval status to Approved"
                elif status_change['new_status'] == 'rejected':
                    action_description = "Changed the approval status to Rejected"
                elif status_change['new_status'] == 'pending':
                    action_description = "Changed the approval status to Pending Approval"
                
                history.append({
                    'action': 'Status Changed',
                    'details': action_description,
                    'timestamp': changed_at,
                    'user': changed_by_user,
                    'metadata': {
                        'old_status': status_change.get('old_status'),
                        'new_status': status_change['new_status'],
                        'comment': status_change.get('comment'),
                        'rejection_reason': status_change.get('rejection_reason')
                    }
                })
    
    # Sort history by timestamp (newest first)
    # Handle None timestamps by using a default datetime
    from datetime import datetime
    default_timestamp = datetime(1970, 1, 1)  # Unix epoch
    history.sort(key=lambda x: x['timestamp'] if x['timestamp'] is not None else default_timestamp, reverse=True)
    
    return history


async def build_approval_context(approval: Approval, db: AsyncSession) -> Dict[str, Any]:
    """
    Build context information for an approval by resolving through message_id.

    Args:
        approval (Approval): The approval object
        db (AsyncSession): Database session

    Returns:
        Dict[str, Any]: Context information
    """
    context = {}

    if not (hasattr(approval, 'message_id') and approval.message_id):
        return context

    try:
        msg_stmt = select(Message).where(Message.id == approval.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()

        if not msg:
            return context

        # Channel context
        if msg.channel_id:
            channel_stmt = select(Channel).where(Channel.id == msg.channel_id)
            channel_result = await db.execute(channel_stmt)
            channel = channel_result.scalar_one_or_none()

            if channel:
                # Load workspace
                if channel.workspace_id:
                    workspace_stmt = select(Workspace).where(Workspace.id == channel.workspace_id)
                    workspace_result = await db.execute(workspace_stmt)
                    workspace = workspace_result.scalar_one_or_none()

                    if workspace:
                        context['workspace'] = {
                            'id': str(workspace.id),
                            'name': workspace.name,
                            'description': workspace.description
                        }

                context['channel'] = {
                    'id': str(channel.id),
                    'name': channel.name,
                    'description': channel.description,
                    'type': 'public' if channel.is_public else 'private',
                    'is_private': not channel.is_public
                }

        # Thread context
        if msg.thread_id:
            thread_stmt = select(Thread).where(Thread.id == msg.thread_id)
            thread_result = await db.execute(thread_stmt)
            thread = thread_result.scalar_one_or_none()

            if thread:
                context['thread'] = {
                    'id': str(thread.id),
                    'title': thread.title,
                    'description': thread.description
                }

    except Exception as e:
        print(f"Error building approval context from message: {e}")

    return context


@router.post("/", response_model=ApprovalResponse)
async def create_approval(
    approval_data: ApprovalCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
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
        # Get platform URL from environment variables for real-time notifications
        platform_url = os.environ.get("PLATFORM_URL") or settings.PLATFORM_URL

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


@router.get("/", response_model=ApprovalListResponse)
async def list_approvals(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    status_filter: Optional[str] = Query(None, description="Filter by status(es): pending, approved, rejected (comma-separated for multiple)"),
    channel_id: Optional[str] = Query(None, description="Filter by channel ID"),
    thread_id: Optional[str] = Query(None, description="Filter by thread ID"),
    created_by: Optional[str] = Query(None, description="Filter by user ID who created the approval"),
    assigned_to: Optional[str] = Query(None, description="Filter by user ID who is assigned to approve"),
    requested_by: Optional[str] = Query(None, description="Filter by user ID who last requested approval to somebody"),
    my_approvals: bool = Query(False, description="Show only approvals assigned to current user"),
    my_requests: bool = Query(False, description="Show only approvals requested by current user")
):
    """
    List approvals with filtering and pagination.
    
    This endpoint retrieves a paginated list of approvals with optional filtering.
    It supports filtering by status, channel, thread, creator, assignee, requester, and user-specific views.

    Args:
        request (Request): FastAPI request object for authentication
        db (AsyncSession): Database session for data operations
        page (int): Page number (1-based)
        size (int): Number of items per page (1-100)
        status_filter (Optional[str]): Filter by approval status(es) - comma-separated for multiple
        channel_id (Optional[str]): Filter by specific channel ID
        thread_id (Optional[str]): Filter by specific thread ID
        created_by (Optional[str]): Filter by user ID who created the approval
        assigned_to (Optional[str]): Filter by user ID who is assigned to approve
        requested_by (Optional[str]): Filter by user ID who last requested approval to somebody
        my_approvals (bool): Show only approvals assigned to current user
        my_requests (bool): Show only approvals requested by current user
        
    Returns:
        ApprovalListResponse: Paginated list of approvals with enhanced details, history, and context
        
    Raises:
        HTTPException: 401 if user not authenticated
    """
    user = await get_current_user_required(request, db)
    
    # Build base query with joins for user details
    # channel_id/thread_id are no longer on Approval; resolved via message_id
    from sqlalchemy.orm import aliased

    # Create aliases for the two user joins
    RequestedByUser = aliased(User)
    ApproverUser = aliased(User)

    base_query = select(
        Approval,
        RequestedByUser.name.label('requested_by_user_name'),
        RequestedByUser.email_id.label('requested_by_user_email'),
        ApproverUser.name.label('approver_user_name'),
        ApproverUser.email_id.label('approver_user_email')
    ).join(
        RequestedByUser, Approval.requested_by_user_id == RequestedByUser.id, isouter=True
    ).join(
        ApproverUser, Approval.approver_user_id == ApproverUser.id, isouter=True
    )

    # Apply filters
    filters = [Approval.is_active == "Y"]
    # Exclude orphan approvals (no message_id)
    filters.append(Approval.message_id.isnot(None))

    # Default filtering: Only show approvals whose message belongs to channels where user is a member
    # Get user's channel memberships
    user_channels_stmt = select(ChannelMember.channel_id).where(
        and_(
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True
        )
    )
    user_channels_result = await db.execute(user_channels_stmt)
    user_channel_ids = [str(c) for c in user_channels_result.scalars().all()]

    if user_channel_ids:
        # Find message IDs in user's channels
        visible_msg_ids_stmt = select(Message.id).where(
            Message.channel_id.in_(user_channel_ids)
        )
        if channel_id:
            visible_msg_ids_stmt = visible_msg_ids_stmt.where(Message.channel_id == channel_id)
        if thread_id:
            await check_channel_access_by_thread(db, user, thread_id)
            visible_msg_ids_stmt = visible_msg_ids_stmt.where(Message.thread_id == thread_id)
        visible_msg_ids_result = await db.execute(visible_msg_ids_stmt)
        visible_message_ids = [row[0] for row in visible_msg_ids_result.all()]
        if visible_message_ids:
            filters.append(Approval.message_id.in_(visible_message_ids))
        else:
            filters.append(Approval.id == None)  # No results
    else:
        # If user is not a member of any channels, return empty result
        filters.append(Approval.id == None)  # This will return no results

    # Multi-status filtering
    if status_filter:
        status_list = [s.strip() for s in status_filter.split(',') if s.strip()]
        if status_list:
            filters.append(Approval.status.in_(status_list))

    # Note: channel_id/thread_id filters already applied above via message resolution

    if created_by:
        filters.append(Approval.requested_by_user_id == created_by)

    if assigned_to:
        filters.append(Approval.approver_user_id == assigned_to)

    # Note: requested_by filter will be applied after building approval details
    # because it requires checking reassignments metadata

    if my_approvals:
        filters.append(Approval.approver_user_id == user.id)

    if my_requests:
        filters.append(Approval.requested_by_user_id == user.id)
    
    # Apply filters to base query
    base_query = base_query.where(*filters)
    
    # Add sorting (newest first)
    base_query = base_query.order_by(Approval.created_at.desc())
    
    # Handle requested_by filter differently due to pagination requirements
    if requested_by:
        # For requested_by filter, we need to get all matching records first,
        # then apply pagination to avoid missing results across pages
        
        # Get all approvals without pagination
        all_items_query = base_query
        all_items_result = await db.execute(all_items_query)
        all_rows = all_items_result.all()

        # Build enhanced response with history and context for all records
        all_approvals = []
        for approval, requested_by_name, requested_by_email, approver_name, approver_email in all_rows:
            try:
                # Refresh approval to get latest data
                await db.refresh(approval)
                
                # Build approval details
                approval_details = await build_approval_details(approval, db)
                
                # Check if this approval matches the requested_by filter
                requested_by_user = approval_details.get('requested_by')
                if requested_by_user and requested_by_user.get('id') == requested_by:
                    # Build approval history
                    approval_history = await build_approval_history(approval, db)
                    
                    # Build context
                    context = await build_approval_context(approval, db)
                    
                    # Create enhanced approval response
                    enhanced_approval = EnhancedApprovalResponse(
                        id=str(approval.id),
                        approval_details=ApprovalDetails(**approval_details),
                        approval_history=[ApprovalHistoryItem(**item) for item in approval_history],
                        context=context
                    )
                    all_approvals.append(enhanced_approval)
                    
            except Exception as e:
                print(f"Error building approval details for {approval.id}: {e}")
                print(f"Approval status: {approval.status}")
                print(f"Approval metadata: {approval.approval_metadata}")
                import traceback
                traceback.print_exc()
                
                # Fallback to basic response
                approval_details = {
                    'approval_name': approval.title,
                    'status': approval.status,
                    'approver': None,
                    'created_by': None,
                    'requested_by': None,
                    'title': approval.title,
                    'description': approval.description,
                    'approval_notes': approval.approval_notes,
                    'rejection_reason': approval.rejection_reason,
                    'comment': approval.comment,
                    'created_at': approval.created_at,
                    'updated_at': approval.updated_at,
                    'approved_at': approval.approved_at,
                    'rejected_at': approval.rejected_at,
                    'approval_metadata': approval.approval_metadata or {}
                }
                
                # Check if this approval matches the requested_by filter
                requested_by_user = approval_details.get('requested_by')
                if requested_by_user and requested_by_user.get('id') == requested_by:
                    enhanced_approval = EnhancedApprovalResponse(
                        id=str(approval.id),
                        approval_details=ApprovalDetails(**approval_details),
                        approval_history=[],
                        context={}
                    )
                    all_approvals.append(enhanced_approval)
        
        # Apply pagination to the filtered results
        total = len(all_approvals)
        offset = (page - 1) * size
        approvals = all_approvals[offset:offset + size]
        
    else:
        # Normal flow for other filters
        # Apply pagination
        offset = (page - 1) * size
        items_query = base_query.offset(offset).limit(size)
        items_result = await db.execute(items_query)
        rows = items_result.all()

        # Get total count
        count_query = select(func.count(Approval.id)).where(*filters)
        count_result = await db.execute(count_query)
        total = count_result.scalar()

        # Build enhanced response with history and context
        approvals = []
        for approval, requested_by_name, requested_by_email, approver_name, approver_email in rows:
            try:
                # Refresh approval to get latest data
                await db.refresh(approval)
                
                # Build approval details
                approval_details = await build_approval_details(approval, db)
                
                # Build approval history
                approval_history = await build_approval_history(approval, db)
                
                # Build context
                context = await build_approval_context(approval, db)
                
                # Create enhanced approval response
                enhanced_approval = EnhancedApprovalResponse(
                    id=str(approval.id),
                    approval_details=ApprovalDetails(**approval_details),
                    approval_history=[ApprovalHistoryItem(**item) for item in approval_history],
                    context=context
                )
                approvals.append(enhanced_approval)
                
            except Exception as e:
                print(f"Error building approval details for {approval.id}: {e}")
                print(f"Approval status: {approval.status}")
                print(f"Approval metadata: {approval.approval_metadata}")
                import traceback
                traceback.print_exc()
                
                # Fallback to basic response
                approval_details = {
                    'approval_name': approval.title,
                    'status': approval.status,
                    'approver': None,
                    'created_by': None,
                    'requested_by': None,
                    'title': approval.title,
                    'description': approval.description,
                    'approval_notes': approval.approval_notes,
                    'rejection_reason': approval.rejection_reason,
                    'comment': approval.comment,
                    'created_at': approval.created_at,
                    'updated_at': approval.updated_at,
                    'approved_at': approval.approved_at,
                    'rejected_at': approval.rejected_at,
                    'approval_metadata': approval.approval_metadata or {}
                }
            
                enhanced_approval = EnhancedApprovalResponse(
                    id=str(approval.id),
                    approval_details=ApprovalDetails(**approval_details),
                    approval_history=[],
                    context={}
                )
                approvals.append(enhanced_approval)
    
    has_more = (page * size) < total
    
    return ApprovalListResponse(
        approvals=approvals,
        total=total,
        page=page,
        size=size,
        has_more=has_more
    )


@router.get("/count", response_model=ApprovalCountResponse)
async def get_approval_count(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get total count of approvals for the current user - uses same logic as list endpoint"""
    user = await get_current_user_required(request, db)
    
    # Get user's channel memberships (same logic as list_approvals endpoint)
    user_channels_stmt = select(ChannelMember.channel_id).where(
        and_(
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True
        )
    )
    user_channels_result = await db.execute(user_channels_stmt)
    user_channel_ids = [str(c) for c in user_channels_result.scalars().all()]
    
    # Build filters (same logic as list_approvals endpoint)
    filters = [Approval.is_active == "Y"]
    filters.append(Approval.message_id.isnot(None))  # Exclude orphan approvals
    # Default filtering: Only show approvals whose message is in user's channels
    if user_channel_ids:
        visible_msg_ids_stmt = select(Message.id).where(
            Message.channel_id.in_(user_channel_ids)
        )
        visible_msg_ids_result = await db.execute(visible_msg_ids_stmt)
        visible_message_ids = [row[0] for row in visible_msg_ids_result.all()]
        if visible_message_ids:
            filters.append(Approval.message_id.in_(visible_message_ids))
        else:
            return ApprovalCountResponse(approval_count=0)
    else:
        # If user is not a member of any channels, return 0 (same as list endpoint)
        return ApprovalCountResponse(approval_count=0)
    
    # Get total count using the same method as list endpoint
    count_query = select(func.count(Approval.id)).where(*filters)
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0
    
    return ApprovalCountResponse(approval_count=total_count)


@router.get("/stats", response_model=ApprovalStats)
async def get_approval_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    channel_id: Optional[str] = Query(None, description="Filter by channel ID")
):
    """Get approval statistics."""
    user = await get_current_user_required(request, db)
    
    # Build base filters; exclude orphan approvals (no message_id)
    filters = [Approval.is_active == "Y", Approval.message_id.isnot(None)]

    if channel_id:
        # Resolve channel_id filter via message
        channel_msg_ids_stmt = select(Message.id).where(Message.channel_id == channel_id)
        channel_msg_ids_result = await db.execute(channel_msg_ids_stmt)
        channel_msg_ids = [row[0] for row in channel_msg_ids_result.all()]
        if channel_msg_ids:
            filters.append(Approval.message_id.in_(channel_msg_ids))
        else:
            filters.append(Approval.id == None)  # No results
    
    # Get counts for each status
    pending_query = select(func.count(Approval.id)).where(
        and_(*filters, Approval.status == "pending")
    )
    pending_result = await db.execute(pending_query)
    total_pending = pending_result.scalar() or 0
    
    approved_query = select(func.count(Approval.id)).where(
        and_(*filters, Approval.status == "approved")
    )
    approved_result = await db.execute(approved_query)
    total_approved = approved_result.scalar() or 0
    
    rejected_query = select(func.count(Approval.id)).where(
        and_(*filters, Approval.status == "rejected")
    )
    rejected_result = await db.execute(rejected_query)
    total_rejected = rejected_result.scalar() or 0
    
    total_query = select(func.count(Approval.id)).where(*filters)
    total_result = await db.execute(total_query)
    total_approvals = total_result.scalar() or 0
    
    return ApprovalStats(
        total_pending=total_pending,
        total_approved=total_approved,
        total_rejected=total_rejected,
        total_approvals=total_approvals
    )


@router.get("/{approval_id}", response_model=ApprovalWithDetailsResponse)
async def get_approval(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific approval by ID."""
    user = await get_current_user_required(request, db)
    
    # Get approval with user details (channel_id/thread_id resolved via message_id)
    from sqlalchemy.orm import aliased

    # Create aliases for the two user joins
    RequestedByUser = aliased(User)
    ApproverUser = aliased(User)

    approval_stmt = select(
        Approval,
        RequestedByUser.name.label('requested_by_user_name'),
        RequestedByUser.email_id.label('requested_by_user_email'),
        ApproverUser.name.label('approver_user_name'),
        ApproverUser.email_id.label('approver_user_email')
    ).join(
        RequestedByUser, Approval.requested_by_user_id == RequestedByUser.id, isouter=True
    ).join(
        ApproverUser, Approval.approver_user_id == ApproverUser.id, isouter=True
    ).where(Approval.id == approval_id)

    approval_result = await db.execute(approval_stmt)
    approval_data = approval_result.first()

    if not approval_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found"
        )

    approval, requested_by_name, requested_by_email, approver_name, approver_email = approval_data

    # Check if user has access to this approval (requester, approver, or channel member)
    is_requester = approval.requested_by_user_id and str(approval.requested_by_user_id) == str(user.id)
    is_approver = approval.approver_user_id and str(approval.approver_user_id) == str(user.id)
    if not (is_requester or is_approver):
        # Also allow channel members
        channel_member_access = False
        if approval.message_id:
            msg_stmt = select(Message).where(Message.id == approval.message_id)
            msg_result = await db.execute(msg_stmt)
            msg = msg_result.scalar_one_or_none()
            if msg and msg.channel_id:
                cm_stmt = select(ChannelMember).where(
                    and_(
                        ChannelMember.channel_id == msg.channel_id,
                        ChannelMember.user_id == user.id,
                        ChannelMember.is_active == True
                    )
                )
                cm_result = await db.execute(cm_stmt)
                channel_member_access = cm_result.scalar_one_or_none() is not None
        if not channel_member_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this approval"
            )

    # Resolve channel_name for response via message
    channel_name = None
    if approval.message_id:
        msg_stmt = select(Message).where(Message.id == approval.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg and msg.channel_id:
            ch_stmt = select(Channel).where(Channel.id == msg.channel_id)
            ch_result = await db.execute(ch_stmt)
            ch = ch_result.scalar_one_or_none()
            if ch:
                channel_name = ch.name

    return ApprovalWithDetailsResponse(
        id=str(approval.id),
        message_id=str(approval.message_id) if approval.message_id else None,
        channel_name=channel_name,
        requested_by_user_id=str(approval.requested_by_user_id) if approval.requested_by_user_id else None,
        requested_by_user_name=requested_by_name,
        requested_by_user_email=requested_by_email,
        approver_user_id=str(approval.approver_user_id) if approval.approver_user_id else None,
        approver_user_name=approver_name,
        approver_user_email=approver_email,
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


@router.put("/{approval_id}", response_model=ApprovalResponse)
async def update_approval(
    approval_id: str,
    approval_data: ApprovalUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Update an approval request (only pending approvals can be updated)."""
    user = await get_current_user_required(request, db)
    
    # Get approval
    approval_stmt = select(Approval).where(Approval.id == approval_id)
    approval_result = await db.execute(approval_stmt)
    approval = approval_result.scalar_one_or_none()
    
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found"
        )
    
    # Check if user can update this approval
    if not (str(approval.requested_by_user_id) == str(user.id) or 
            str(approval.approver_user_id) == str(user.id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to update this approval"
        )
    
    # Only pending approvals can be updated
    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending approvals can be updated"
        )
    
    # Update fields
    if approval_data.title is not None:
        approval.title = approval_data.title
    
    if approval_data.description is not None:
        approval.description = approval_data.description
    
    # If changing approver, validate the new approver is a channel member (resolved via message)
    if approval_data.approver_user_id is not None:
        update_channel_id = None
        if approval.message_id:
            msg_stmt = select(Message).where(Message.id == approval.message_id)
            msg_result = await db.execute(msg_stmt)
            msg = msg_result.scalar_one_or_none()
            if msg:
                update_channel_id = msg.channel_id

        if update_channel_id:
            new_approver_member_stmt = select(ChannelMember).where(
                and_(
                    ChannelMember.channel_id == update_channel_id,
                    ChannelMember.user_id == approval_data.approver_user_id,
                    ChannelMember.is_active == True
                )
            )
            new_approver_member_result = await db.execute(new_approver_member_stmt)
            new_approver_member = new_approver_member_result.scalar_one_or_none()

            if not new_approver_member:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="New approver must be an active member of the channel"
                )

        approval.approver_user_id = approval_data.approver_user_id

    approval.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await audit_log_write(db, user.id, "approval.updated", "approval", approval.id, channel_id=approval.channel_id, thread_id=approval.thread_id)
    await db.commit()
    await db.refresh(approval)

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


@router.post("/{approval_id}/action", response_model=ApprovalResponse)
async def take_approval_action(
    approval_id: str,
    action_data: ApprovalAction,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Take action on an approval (approve/reject)."""
    user = await get_current_user_required(request, db)
    
    # Get approval
    approval_stmt = select(Approval).where(Approval.id == approval_id)
    approval_result = await db.execute(approval_stmt)
    approval = approval_result.scalar_one_or_none()
    
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found"
        )
    
    # Check if user can take action on this approval
    if str(approval.approver_user_id) != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assigned approver can take action on this approval"
        )
    
    # Only pending approvals can have actions taken
    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending approvals can have actions taken"
        )
    
    # Validate action
    if action_data.action not in ["approve", "reject"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be either 'approve' or 'reject'"
        )
    
    # Store old status for history tracking
    old_status = approval.status
    current_time = datetime.now(timezone.utc).replace(tzinfo=None)
    
    # Update approval based on action
    if action_data.action == "approve":
        approval.status = "approved"
        approval.comment = action_data.comment
        approval.approved_at = current_time
    else:  # reject
        approval.status = "rejected"
        approval.comment = action_data.comment
        approval.rejection_reason = action_data.rejection_reason
        approval.rejected_at = current_time
    
    approval.updated_at = current_time
    
    # Track status change in metadata
    if not approval.approval_metadata:
        approval.approval_metadata = {}
    
    if 'status_changes' not in approval.approval_metadata:
        approval.approval_metadata['status_changes'] = []
    
    approval.approval_metadata['status_changes'].append({
        'old_status': old_status,
        'new_status': approval.status,
        'changed_by': str(user.id),
        'changed_by_name': user.name if hasattr(user, 'name') else None,
        'changed_at': current_time.isoformat(),
        'comment': action_data.comment,
        'rejection_reason': action_data.rejection_reason if action_data.action == "reject" else None,
        'action_type': 'status_change'
    })
    
    # Mark the JSONB field as modified so SQLAlchemy detects the change
    from sqlalchemy.orm import attributes
    attributes.flag_modified(approval, 'approval_metadata')
    
    await db.commit()
    await db.refresh(approval)
    
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


@router.get("/{approval_id}/debug", response_model=Dict[str, Any])
async def debug_approval_metadata(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Debug endpoint to check raw approval metadata."""
    user = await get_current_user_required(request, db)
    
    # Get approval
    approval_stmt = select(Approval).where(Approval.id == approval_id)
    approval_result = await db.execute(approval_stmt)
    approval = approval_result.scalar_one_or_none()
    
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found"
        )
    
    return {
        "approval_id": str(approval.id),
        "status": approval.status,
        "approver_user_id": str(approval.approver_user_id),
        "raw_metadata": approval.approval_metadata,
        "metadata_type": type(approval.approval_metadata).__name__,
        "metadata_keys": list(approval.approval_metadata.keys()) if approval.approval_metadata else [],
        "reassignments_count": len(approval.approval_metadata.get('reassignments', [])) if approval.approval_metadata else 0,
        "status_changes_count": len(approval.approval_metadata.get('status_changes', [])) if approval.approval_metadata else 0
    }


@router.get("/{approval_id}/history", response_model=List[Dict[str, Any]])
async def get_approval_history(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get comprehensive approval history including all actions and reassignments."""
    user = await get_current_user_required(request, db)
    
    # Get approval
    approval_stmt = select(Approval).where(Approval.id == approval_id)
    approval_result = await db.execute(approval_stmt)
    approval = approval_result.scalar_one_or_none()
    
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found"
        )
    
    # Check if user has access to this approval (must be requester, approver, or channel member)
    is_requester_hist = approval.requested_by_user_id and str(approval.requested_by_user_id) == str(user.id)
    is_approver_hist = approval.approver_user_id and str(approval.approver_user_id) == str(user.id)
    if not (is_requester_hist or is_approver_hist):
        channel_member = None
        if approval.message_id:
            msg_stmt = select(Message).where(Message.id == approval.message_id)
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
        if not channel_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this approval"
            )
    
    # Build comprehensive history
    history = []
    
    # Add initial creation and assignment
    initial_assignment = None
    if approval.approval_metadata and 'initial_assignment' in approval.approval_metadata:
        initial_assignment = approval.approval_metadata['initial_assignment']
    
    if initial_assignment:
        history.append({
            "action": "assigned",
            "description": f"Assigned the approval to {initial_assignment.get('assigned_to_name', 'Unknown User')} and set the status to Pending Approval",
            "timestamp": initial_assignment.get('assigned_at', approval.created_at.isoformat() if approval.created_at else None),
            "user_id": initial_assignment.get('assigned_by'),
            "user_name": initial_assignment.get('assigned_by_name'),
            "status": "pending",
            "details": {
                "assigned_to": initial_assignment.get('assigned_to_name'),
                "title": approval.title,
                "description": approval.description
            }
        })
    else:
        # Fallback for older approvals without initial assignment tracking
        history.append({
            "action": "created",
            "description": f"Approval created and assigned to {approval.approver_user_id}",
            "timestamp": approval.created_at.isoformat() if approval.created_at else None,
            "user_id": str(approval.requested_by_user_id),
            "user_name": None,
            "status": "pending",
            "details": {
                "title": approval.title,
                "description": approval.description
            }
        })
    
    # Add reassignments
    if approval.approval_metadata and 'reassignments' in approval.approval_metadata:
        for reassignment in approval.approval_metadata['reassignments']:
            history.append({
                "action": "reassigned",
                "description": f"Assigned the approval to {reassignment.get('new_approver_name', 'Unknown User')} and set the status to Pending Approval",
                "timestamp": reassignment['reassigned_at'],
                "user_id": reassignment['reassigned_by'],
                "user_name": reassignment.get('reassigned_by_name'),
                "status": "pending",
                "details": {
                    "previous_approver": reassignment.get('previous_approver_name'),
                    "new_approver": reassignment.get('new_approver_name'),
                    "notes": reassignment.get('notes'),
                    "status_reset": reassignment.get('status_reset', False)
                }
            })
    
    # Add status changes
    if approval.approval_metadata and 'status_changes' in approval.approval_metadata:
        for status_change in approval.approval_metadata['status_changes']:
            if status_change.get('action_type') == 'reassignment_reset':
                continue  # Skip reassignment resets as they're covered in reassignments
            
            action_description = ""
            if status_change['new_status'] == 'approved':
                action_description = "Changed the approval status to Approved"
            elif status_change['new_status'] == 'rejected':
                action_description = "Changed the approval status to Rejected"
            elif status_change['new_status'] == 'pending':
                action_description = "Changed the approval status to Pending Approval"
            
            history.append({
                "action": "status_changed",
                "description": action_description,
                "timestamp": status_change['changed_at'],
                "user_id": status_change['changed_by'],
                "user_name": status_change.get('changed_by_name'),
                "status": status_change['new_status'],
                "details": {
                    "old_status": status_change['old_status'],
                    "new_status": status_change['new_status'],
                    "comment": status_change.get('comment'),
                    "rejection_reason": status_change.get('rejection_reason')
                }
            })
    
    # Sort history by timestamp
    history.sort(key=lambda x: x['timestamp'] or '')
    
    return history


@router.post("/{approval_id}/reassign", response_model=ApprovalResponse)
async def reassign_approval(
    approval_id: str,
    reassign_data: ApprovalReassign,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Reassign an approval to another user.
    
    This endpoint allows reassignment of approvals in any status:
    - Pending approvals: Simple reassignment to new approver
    - Completed approvals (approved/rejected): Reassignment with status reset to pending
    """
    user = await get_current_user_required(request, db)
    
    # Get approval
    approval_stmt = select(Approval).where(Approval.id == approval_id)
    approval_result = await db.execute(approval_stmt)
    approval = approval_result.scalar_one_or_none()
    
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found"
        )
    
    # Check if user can reassign this approval
    if str(approval.approver_user_id) != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assigned approver can reassign this approval"
        )
    
    # Allow reassignment of any approval status
    # If approval is completed (approved/rejected), reset status to pending
    was_completed = approval.status in ["approved", "rejected"]
    if was_completed:
        approval.status = "pending"
        # Clear completion timestamps when resetting to pending
        approval.approved_at = None
        approval.rejected_at = None
        approval.comment = None
        approval.rejection_reason = None
    
    # Resolve channel_id from message for channel membership checks
    reassign_channel_id = None
    reassign_thread_id = None
    if approval.message_id:
        msg_stmt = select(Message).where(Message.id == approval.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()
        if msg:
            reassign_channel_id = msg.channel_id
            reassign_thread_id = msg.thread_id

    # Validate new approver is a channel member (resolved via message)
    new_approver_member = None
    if reassign_channel_id:
        new_approver_member_stmt = select(ChannelMember).where(
            and_(
                ChannelMember.channel_id == reassign_channel_id,
                ChannelMember.user_id == reassign_data.new_approver_user_id,
                ChannelMember.is_active == True
            )
        )
        new_approver_member_result = await db.execute(new_approver_member_stmt)
        new_approver_member = new_approver_member_result.scalar_one_or_none()
    
    if reassign_channel_id and not new_approver_member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New approver must be an active member of the channel"
        )

    # Store previous approver for history tracking
    previous_approver_id = approval.approver_user_id
    current_time = datetime.now(timezone.utc).replace(tzinfo=None)
    
    # Update approver
    approval.approver_user_id = reassign_data.new_approver_user_id
    approval.approval_notes = reassign_data.notes
    approval.updated_at = current_time
    
    # Get user information for tracking
    previous_approver_stmt = select(User).where(User.id == previous_approver_id)
    previous_approver_result = await db.execute(previous_approver_stmt)
    previous_approver = previous_approver_result.scalar_one_or_none()
    
    new_approver_stmt = select(User).where(User.id == reassign_data.new_approver_user_id)
    new_approver_result = await db.execute(new_approver_stmt)
    new_approver = new_approver_result.scalar_one_or_none()
    
    # Track reassignment in metadata
    if not approval.approval_metadata:
        approval.approval_metadata = {}
    
    if 'reassignments' not in approval.approval_metadata:
        approval.approval_metadata['reassignments'] = []
    
    # Track reassignment
    reassignment_entry = {
        'previous_approver_id': str(previous_approver_id),
        'new_approver_id': str(reassign_data.new_approver_user_id),
        'reassigned_by': str(user.id),
        'reassigned_at': current_time.isoformat(),
        'notes': reassign_data.notes,
        'previous_status': approval.status if not was_completed else 'pending',
        'status_reset': was_completed,
        'reset_reason': 'reassigned_completed_approval' if was_completed else None,
        'previous_approver_name': previous_approver.name if previous_approver else None,
        'new_approver_name': new_approver.name if new_approver else None,
        'reassigned_by_name': user.name if hasattr(user, 'name') else None
    }
    
    approval.approval_metadata['reassignments'].append(reassignment_entry)
    
    # Also track as a status change if status was reset
    if was_completed:
        if 'status_changes' not in approval.approval_metadata:
            approval.approval_metadata['status_changes'] = []
        
        approval.approval_metadata['status_changes'].append({
            'old_status': 'approved' if approval.status == 'pending' else 'rejected',
            'new_status': 'pending',
            'changed_by': str(user.id),
            'changed_at': current_time.isoformat(),
            'comment': f"Status reset to pending due to reassignment to {new_approver.name if new_approver else 'new approver'}",
            'rejection_reason': None,
            'action_type': 'reassignment_reset'
        })
    
    # Mark the JSONB field as modified so SQLAlchemy detects the change
    from sqlalchemy.orm import attributes
    attributes.flag_modified(approval, 'approval_metadata')
    await audit_log_write(db, user.id, "approval.reassigned", "approval", approval.id, channel_id=approval.channel_id, thread_id=approval.thread_id, details={"new_approver_id": str(reassign_data.new_approver_user_id)})
    await db.commit()
    await db.refresh(approval)
    
    # Process approval reassignment notifications in background
    if reassign_channel_id and approval.approver_user_id and reassign_thread_id:
        # Get platform URL from environment variables for real-time notifications
        platform_url = os.environ.get("PLATFORM_URL") or settings.PLATFORM_URL

        # Construct redirect URL (shortened; store thread_id/channel_id for move-safe links)
        redirect_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{reassign_channel_id}/{reassign_thread_id}?openApproval=true", db,
            thread_id=reassign_thread_id, channel_id=reassign_channel_id, entity_type="approval",
        ) if platform_url else "#"
        # Construct notification settings URL (shortened; channel-level)
        notification_settings_url = await link_shortener_service.shorten(
            f"{platform_url}/threads/{reassign_channel_id}?openSettings=true&tab=notification", db,
            channel_id=reassign_channel_id, entity_type="channel",
        ) if platform_url else "#"

        background_tasks.add_task(
            process_approval_reassignment_notifications,
            str(user.id),  # Reassigner ID
            str(approval.approver_user_id),  # Reassigned approver ID
            str(reassign_channel_id),  # Channel ID
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


@router.delete("/{approval_id}")
async def delete_approval(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Delete an approval (soft delete by setting is_active to 'N')."""
    user = await get_current_user_required(request, db)
    
    # Get approval
    approval_stmt = select(Approval).where(Approval.id == approval_id)
    approval_result = await db.execute(approval_stmt)
    approval = approval_result.scalar_one_or_none()
    
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found"
        )
    
    # Check if user can delete this approval
    if str(approval.requested_by_user_id) != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the requester can delete this approval"
        )
    
    # Only pending approvals can be deleted
    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending approvals can be deleted"
        )
    
    await audit_log_write(db, user.id, "approval.deleted", "approval", approval.id, channel_id=approval.channel_id, thread_id=approval.thread_id)
    # Soft delete
    approval.is_active = "N"
    approval.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    
    await db.commit()
    
    return {"message": "Approval deleted successfully"}
