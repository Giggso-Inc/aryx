"""Helpers for loading and summarizing a single approval's user/detail info."""

from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.models.user import User


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
