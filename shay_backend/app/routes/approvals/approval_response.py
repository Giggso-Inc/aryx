"""Shared ApprovalResponse serializer used by the create and reassign endpoints."""

from app.models.approval import Approval
from app.schemas.approval import ApprovalResponse


def to_approval_response(approval: Approval) -> ApprovalResponse:
    """Convert an Approval ORM row into the API response schema.

    Args:
        approval (Approval): The approval row to serialize.

    Returns:
        ApprovalResponse: UUID fields converted to strings for JSON output.
    """
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
