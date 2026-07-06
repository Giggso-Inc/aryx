"""
Authentication routes for OAuth2 login and JWT token management
"""

import httpx
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.auth import (
    create_access_token,
    create_refresh_token,
    create_token_data,
    generate_user_id,
    generate_company_id
)
from app.core.config import settings
from app.models.user import User
from app.models.company import Company
from app.schemas.auth import (
    Token,
    UserLogin,
    UserCreate,
    UserUpdate,
    OAuthLogin,
    OAuthCallback,
    RefreshToken,
    LogoutRequest
)
from app.schemas.user import UserResponse

router = APIRouter()


@router.post("/login", response_model=dict)
async def login(login_data: OAuthLogin):
    """Initiate OAuth2 login with Google"""
    # Generate OAuth2 authorization URL
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={settings.GOOGLE_CLIENT_ID}&"
        f"redirect_uri={settings.GOOGLE_REDIRECT_URI}&"
        f"response_type=code&"
        f"scope=openid email profile&"
        f"access_type=offline"
    )
    
    return {
        "auth_url": auth_url,
        "message": "Redirect to Google OAuth"
    }


@router.post("/callback", response_model=Token)
async def oauth_callback(callback_data: OAuthCallback, db: AsyncSession = Depends(get_db)):
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


@router.post("/refresh", response_model=Token)
async def refresh_token(refresh_data: RefreshToken):
    """Refresh JWT access token"""
    try:
        from app.core.auth import verify_token
        
        # Verify refresh token
        payload = verify_token(refresh_data.refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
        
        # Create new access token
        token_data = {
            "sub": payload["sub"],
            "email": payload["email"],
            "role": payload["role"],
            "company_id": payload.get("company_id"),
            "type": "access"
        }
        
        access_token = create_access_token(token_data)
        
        return Token(
            access_token=access_token,
            refresh_token=refresh_data.refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user_id=payload["sub"],
            email=payload["email"],
            role=payload["role"],
            company_id=payload.get("company_id")
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token refresh failed: {str(e)}"
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(request: Request, db: AsyncSession = Depends(get_db)):
    """Get current user information"""
    from app.middleware.auth_middleware import get_current_user_required
    
    user = await get_current_user_required(request)
    return UserResponse.from_orm(user)


@router.post("/logout")
async def logout(logout_data: LogoutRequest):
    """Logout user (invalidate refresh token)"""
    # In a real implementation, you might want to blacklist the refresh token
    # For now, we'll just return success
    return {"message": "Successfully logged out"}


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Update current user information"""
    from app.middleware.auth_middleware import get_current_user_required
    
    user = await get_current_user_required(request)
    
    # Update user fields
    update_data = user_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)
    
    await db.commit()
    await db.refresh(user)
    
    return UserResponse.from_orm(user)


@router.post("/dev-token", response_model=Token)
async def get_dev_token(db: AsyncSession = Depends(get_db)):
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