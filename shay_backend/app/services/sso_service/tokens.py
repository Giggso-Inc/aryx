"""Issue platform access/refresh tokens for a resolved SSO user."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token, create_refresh_token, create_token_data
from app.core.config import settings
from app.models.company import Company
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.user import UserTokenResponse
from .errors import ProviderError


async def issue_tokens_for_user(db: AsyncSession, user: User) -> UserTokenResponse:
    company_result = await db.execute(
        select(Company).where(Company.id == user.company_id)
    )
    company = company_result.scalar_one_or_none()
    if not user.is_active:
        raise ProviderError("User account is inactive")
    if company and not company.is_active:
        raise ProviderError("Company account is inactive")
    workspace_result = await db.execute(
        select(Workspace).where(Workspace.company_id == user.company_id).limit(1)
    )
    workspace = workspace_result.scalar_one_or_none()
    token_data = create_token_data(
        str(user.id), user.email_id, user.role, str(user.company_id)
    )
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)
    user.last_login = datetime.utcnow()
    await db.commit()
    return UserTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_id=str(user.id),
        email_id=user.email_id,
        name=user.name,
        avatar_url=user.avatar_url,
        role=user.role,
        company_id=str(user.company_id),
        company_name=company.name if company else None,
        default_workspace_id=str(workspace.id) if workspace else None,
    )
