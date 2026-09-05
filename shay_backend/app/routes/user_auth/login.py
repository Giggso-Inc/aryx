"""
Login route: login_user.

Split out of registration.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up — the
original registration.py combined register_user and login_user in one
475-line file, over the 150-line hard limit). Precondition checks and
password verification live in `_login_helpers.py`; steps shared with
register.py live in `_auth_flow_helpers.py`.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.auth import create_access_token, create_refresh_token

from app.models.user import User

from app.schemas.user import UserLoginEncryptedRequest, UserTokenResponse

from app.routes.user_auth._auth_flow_helpers import (
    _get_company_or_404, _get_or_create_default_workspace, _build_token_data,
)
from app.routes.user_auth._login_helpers import (
    _ensure_login_allowed, _verify_login_credentials,
)
from app.services.workspace_membership import ensure_workspace_membership

router = APIRouter()


@router.post("/login", response_model=UserTokenResponse)
async def login_user(
    login_data: UserLoginEncryptedRequest,
    db: AsyncSession = Depends(get_db)
) -> UserTokenResponse:
    """
    Authenticate user with email and password, returning JWT tokens.

    This endpoint handles user login by validating credentials and updating
    the user's last_login timestamp. It supports both encrypted and non-encrypted
    passwords based on the 'encrypted' flag in the request.

    Args:
        login_data: UserLoginEncryptedRequest containing email, password, and encrypted flag
        db: Database session dependency

    Returns:
        UserTokenResponse: JWT access and refresh tokens with user info

    Raises:
        HTTPException: 404 with error_code E004 when email not in DB,
                       401 with "Invalid password" for wrong password, 404 for company not found
    """
    stmt = select(User).where(User.email_id == login_data.email_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "Account not found",
                "error_code": "E004"
            }
        )

    _ensure_login_allowed(user)
    _verify_login_credentials(login_data, user)

    user.last_login = datetime.utcnow()
    await db.commit()

    company = await _get_company_or_404(db, user.company_id)

    if not company.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Company account is inactive. Please contact support.",
                "error_code": "E006"
            }
        )

    default_workspace = await _get_or_create_default_workspace(db, company, user)

    await ensure_workspace_membership(
        db,
        workspace=default_workspace,
        user=user,
        role="admin" if user.role == "admin" else "member",
    )
    await db.commit()

    token_data = _build_token_data(user)
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return UserTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=1800,  # 30 minutes
        user_id=str(user.id),
        email_id=user.email_id,
        name=user.name,
        avatar_url=user.avatar_url,
        role=user.role,
        company_id=str(user.company_id),
        company_name=company.name,
        default_workspace_id=str(default_workspace.id) if default_workspace else None
    )
