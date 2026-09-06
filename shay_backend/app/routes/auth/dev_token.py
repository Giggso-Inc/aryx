"""
Dev-token route: get_dev_token (DEV ONLY test token issuance).

Split out of the original monolithic app/routes/auth.py (312 lines, over the
150-line hard limit) — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5 (final wave). One endpoint per file, aggregated back into a single
`router` by app/routes/auth/__init__.py in the original registration order.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.auth import create_access_token, create_refresh_token, create_token_data, generate_user_id, generate_company_id
from app.core.config import settings
from app.models.user import User
from app.models.company import Company
from app.schemas.auth import Token

router = APIRouter()


@router.post("/dev-token", response_model=Token)
async def get_dev_token(db: AsyncSession = Depends(get_db)) -> Token:
    """Get a development token for testing (DEV ONLY)"""
    # Create a test user if it doesn't exist
    stmt = select(User).where(User.email_id == "dev@test.com")
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        # Get or create test company
        company_stmt = select(Company).where(Company.domain == "dev.test")
        company_result = await db.execute(company_stmt)
        company = company_result.scalar_one_or_none()

        if not company:
            company_id = generate_company_id()
            company = Company(
                id=company_id,
                name="Development Company",
                domain="dev.test",
                subscription_plan="free",
                max_users="10",
                max_workspaces="5",
                max_storage_gb="1",
                ai_enabled=True,
                ai_provider="openai"
            )
            db.add(company)

        # Create test user
        user_id = generate_user_id()
        user = User(
            id=user_id,
            name="Development User",
            email_id="dev@test.com",
            role="admin",
            company_id=company.id,
            is_active=True
        )
        db.add(user)
        await db.commit()

    # Create JWT tokens
    token_data = create_token_data(
        user_id=str(user.id),
        email=user.email_id,
        role=user.role,
        company_id=str(user.company_id) if user.company_id else None
    )

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_id=str(user.id),
        email=user.email_id,
        role=user.role,
        company_id=str(user.company_id) if user.company_id else None
    )
