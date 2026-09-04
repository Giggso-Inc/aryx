"""
Invitation-acceptance endpoint: turns a pending invitation into a new user.

Split from app/routes/companies.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.user import User
from app.models.invitation import Invitation
from app.schemas.company import InvitationAccept

router = APIRouter()


@router.post("/invitations/{invitation_id}/accept", response_model=dict)
async def accept_invitation(
    invitation_id: str,
    accept_data: InvitationAccept,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Accept an invitation"""
    # Get invitation
    stmt = select(Invitation).where(Invitation.id == invitation_id)
    result = await db.execute(stmt)
    invitation = result.scalar_one_or_none()

    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found"
        )

    if not invitation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation is not valid or has expired"
        )

    # Check if user already exists
    existing_user_stmt = select(User).where(User.email_id == invitation.email)
    existing_user_result = await db.execute(existing_user_stmt)
    existing_user = existing_user_result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )

    # Create user
    from app.core.auth import generate_user_id

    user = User(
        id=generate_user_id(),
        name=accept_data.name,
        email_id=invitation.email_id,
        role=invitation.role,
        company_id=invitation.company_id
    )

    # Mark invitation as accepted
    invitation.accept()

    db.add(user)
    await db.commit()

    return {
        "message": "Invitation accepted successfully",
        "user_id": str(user.id),
        "company_id": str(user.company_id) if user.company_id else None
    }
