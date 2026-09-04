"""
Approval history/context builders used by the list and detail endpoints.

Stated exception to the 150-line target: build_approval_history alone is a
single ~200-line function that reconstructs a chronological timeline from
three independent metadata shapes (initial_assignment, reassignments,
status_changes) plus a legacy fallback branch for approvals created before
initial_assignment tracking existed. It was golden-mastered as one unit in
tests/test_approvals_characterization.py; splitting its per-metadata-shape
blocks into separate helpers risks silently changing timestamp fallback or
sort-order behavior. Kept together per the Raven Style Compliance Plan's
"too tightly coupled to split further safely" carve-out (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.models.channel import Channel
from app.models.message import Message, Thread
from app.models.user import User
from app.models.workspace import Workspace

from .details import load_approval_details


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
