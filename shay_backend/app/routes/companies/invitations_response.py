"""
Response-assembly helper for list_invitations (invitations.py): fetches the
users who sent each invitation in one query, then builds the
invited_by-enriched response list. Split out purely to keep the endpoint
itself under the 150-line limit; no behavior change.
"""

from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invitation import Invitation
from app.models.user import User
from app.schemas.company import InvitedByUser, UserInvitationResponse


async def _build_invitation_responses(db: AsyncSession, invitations: List[Invitation]) -> List[UserInvitationResponse]:
    """Fetch the users who sent each invitation in one query, then build
    the invited_by-enriched response list."""
    invited_by_user_ids = list(set(invitation.invited_by for invitation in invitations))

    users_query = select(User).where(User.id.in_(invited_by_user_ids))
    users_result = await db.execute(users_query)
    users = users_result.scalars().all()

    users_map = {user.id: user for user in users}

    invitation_responses = []
    for invitation in invitations:
        invited_by_user = users_map.get(invitation.invited_by)

        if invited_by_user:
            invited_by_obj = InvitedByUser(
                userId=invited_by_user.id,
                userEmail=invited_by_user.email_id,
                username=invited_by_user.name,
                avatar_url=invited_by_user.avatar_url,
                role=invited_by_user.role
            )
        else:
            # Fallback if user not found (shouldn't happen, but handle gracefully)
            invited_by_obj = InvitedByUser(
                userId=invitation.invited_by,
                userEmail=None,
                username=None,
                avatar_url=None,
                role=None
            )

        invitation_responses.append(UserInvitationResponse(
            id=invitation.id,
            email=invitation.email,
            role=invitation.role,
            company_id=invitation.company_id,
            invited_by=invited_by_obj,
            status=invitation.status,
            message=invitation.message,
            created_at=invitation.created_at,
            expires_at=invitation.expires_at
        ))

    return invitation_responses
