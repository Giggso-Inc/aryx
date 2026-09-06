"""
POST /{company_id}/invite — invite_user.

Split from app/routes/companies.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2; further
split in wave B4 out of invitations.py, one endpoint per file).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.models.invitation import Invitation
from app.models.user import User
from app.schemas.company import InvitedByUser, UserInvitation, UserInvitationResponse

router = APIRouter()


@router.post("/{company_id}/invite", response_model=UserInvitationResponse)
async def invite_user(
    company_id: str,
    invitation: UserInvitation,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> UserInvitationResponse:
    """Invite a user to the company"""
    user = await get_current_user_required(request)

    # Check if user can invite to this company
    if user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only invite users to your own company"
        )

    # Check if user is admin or has invite permissions
    if user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to invite users"
        )

    # Get company
    stmt = select(Company).where(Company.id == company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
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

    # Check if invitation already exists
    existing_invitation_stmt = select(Invitation).where(
        and_(
            Invitation.email == invitation.email,
            Invitation.company_id == company_id,
            Invitation.status == "pending"
        )
    )
    existing_invitation_result = await db.execute(existing_invitation_stmt)
    existing_invitation = existing_invitation_result.scalar_one_or_none()

    if existing_invitation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation already exists for this email"
        )

    # Create invitation
    new_invitation = Invitation.create_invitation(
        email=invitation.email,
        role=invitation.role,
        company_id=company_id,
        invited_by=user.id,
        message=invitation.message
    )

    db.add(new_invitation)
    await db.commit()
    await db.refresh(new_invitation)

    # Create InvitedByUser object from the current user (include avatar_url for UI)
    invited_by_obj = InvitedByUser(
        userId=user.id,
        userEmail=user.email_id,
        username=user.name,
        avatar_url=user.avatar_url,
        role=user.role
    )

    # Create UserInvitationResponse with invited_by object
    return UserInvitationResponse(
        id=new_invitation.id,
        email=new_invitation.email,
        role=new_invitation.role,
        company_id=new_invitation.company_id,
        invited_by=invited_by_obj,
        status=new_invitation.status,
        message=new_invitation.message,
        created_at=new_invitation.created_at,
        expires_at=new_invitation.expires_at
    )
