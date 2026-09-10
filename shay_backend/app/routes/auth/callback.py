"""
Callback route: oauth_callback (handle OAuth2 callback from Google).

Split out of the original monolithic app/routes/auth.py (312 lines, over the
150-line hard limit) — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5 (final wave). One endpoint per file, aggregated back into a single
`router` by app/routes/auth/__init__.py in the original registration order.

This is the single largest/most tightly-coupled endpoint in the original
file (token exchange -> userinfo fetch -> find-or-create user/company ->
JWT issuance, all inside one try/except and largely one atomic-ish flow) —
kept as one file rather than split further to avoid fragmenting a single
error-handling boundary across modules.
"""

import httpx
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.auth import create_access_token, create_refresh_token, create_token_data, generate_user_id, generate_company_id
from app.core.config import settings
from app.models.user import User
from app.models.company import Company
from app.schemas.auth import Token, OAuthCallback

router = APIRouter()


@router.post("/callback", response_model=Token)
async def oauth_callback(callback_data: OAuthCallback, db: AsyncSession = Depends(get_db)) -> Token:
    """Handle OAuth2 callback from Google"""
    try:
        # Exchange authorization code for tokens
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "code": callback_data.code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.GOOGLE_REDIRECT_URI
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=token_data)
            response.raise_for_status()
            token_info = response.json()

        # Get user information from Google
        user_info_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        headers = {"Authorization": f"Bearer {token_info['access_token']}"}

        async with httpx.AsyncClient() as client:
            response = await client.get(user_info_url, headers=headers)
            response.raise_for_status()
            user_info = response.json()

        # Check if user exists
        stmt = select(User).where(User.google_id == user_info["id"])
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            # Extract domain from email
            email_domain = user_info.get("email", "").split("@")[1] if "@" in user_info.get("email", "") else None

            # Check if company exists for this domain
            company = None
            if email_domain:
                company_stmt = select(Company).where(Company.domain == email_domain)
                company_result = await db.execute(company_stmt)
                company = company_result.scalar_one_or_none()

            # Create company if it doesn't exist
            if not company:
                company_id = generate_company_id()
                company = Company(
                    id=company_id,
                    name=f"{user_info.get('name', 'User')}'s Company",
                    domain=email_domain
                )
                db.add(company)
                await db.flush()  # Flush to get the company ID

            # Create user with appropriate role
            user_id = generate_user_id()

            # Determine user role: admin if first user in company, otherwise user
            user_count_stmt = select(func.count(User.id)).where(User.company_id == company.id)
            user_count_result = await db.execute(user_count_stmt)
            user_count = user_count_result.scalar()

            # First user in company gets admin role, others get user role
            user_role = "admin" if user_count == 0 else "user"

            user = User(
                id=user_id,
                email_id=user_info["email"],
                name=user_info.get("name"),
                avatar_url=user_info.get("picture"),
                google_id=user_info["id"],
                company_id=company.id,
                role=user_role,
                is_verified=True,
                last_login=datetime.utcnow()
            )
            db.add(user)

            await db.commit()
        else:
            # Update existing user
            user.last_login = datetime.utcnow()
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

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth callback failed: {str(e)}"
        )
