"""
Shared response-shaping helper for the thread member endpoints.

Split from app/routes/threads/members.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

from app.models.member import GGMember
from app.schemas.member import MemberResponse


def member_to_response(m: GGMember) -> MemberResponse:
    return MemberResponse(
        id=str(m.id),
        user_id=str(m.user_id),
        level=m.level,
        workspace_id=str(m.workspace_id) if m.workspace_id else None,
        channel_id=str(m.channel_id) if m.channel_id else None,
        thread_id=str(m.thread_id) if m.thread_id else None,
        role=m.role,
        is_active=m.is_active,
        permissions=m.permissions,
        invited_by=str(m.invited_by) if m.invited_by else None,
        joined_at=m.joined_at,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )
