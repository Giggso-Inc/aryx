"""
Registration route: register_user.

Split out of registration.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up — the
original registration.py combined register_user and login_user in one
475-line file, over the 150-line hard limit). Sub-steps used only by this
endpoint live in `_register_helpers.py`; steps shared with login.py live in
`_auth_flow_helpers.py`.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.auth import create_access_token, create_refresh_token, get_password_hash
from app.core.encryption_utils import decrypt

from app.models.user import User

from app.schemas.user import UserRegisterEncryptedRequest, UserTokenResponse

from app.routes.user_auth._auth_flow_helpers import (
    _get_company_or_404, _get_or_create_default_workspace, _build_token_data,
)
from app.routes.user_auth._register_helpers import (
    _apply_invite_param_overrides, _resolve_registration_target,
    _derive_user_name, _upsert_registered_user,
)
from app.services.workspace_membership import ensure_workspace_membership

router = APIRouter()


@router.post("/register", response_model=UserTokenResponse)
async def register_user(
    register_data: UserRegisterEncryptedRequest,
    db: AsyncSession = Depends(get_db)
) -> UserTokenResponse:
    """Register new user with or without invitation, supporting encrypted passwords"""

    password_to_use = register_data.password
    if register_data.encrypted:
        try:
            password_to_use = decrypt(register_data.password)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid encrypted password format"
            )

    _apply_invite_param_overrides(register_data)

    stmt = select(User).where(User.email_id == register_data.email_id)
    result = await db.execute(stmt)
    existing_user = result.scalar_one_or_none()
    if existing_user and existing_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists"
        )
    if existing_user and not register_data.invite_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists"
        )

    company_id, role, _invitation = await _resolve_registration_target(db, register_data)

    password_hash = get_password_hash(password_to_use)
    user_name = _derive_user_name(register_data)
    user = _upsert_registered_user(
        db, register_data, company_id, role, password_hash, existing_user, user_name
    )

    await db.commit()
    await db.refresh(user)

    company = await _get_company_or_404(db, user.company_id)
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
        default_workspace_id=str(default_workspace.id) if default_workspace else None
    )
