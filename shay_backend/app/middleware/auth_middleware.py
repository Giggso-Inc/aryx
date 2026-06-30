"""
Authentication middleware for JWT token validation
"""

import time
from typing import Optional
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.core.auth import verify_token
from app.core.database import get_db
from app.models.user import User
from app.models.invitation import Invitation


class AuthMiddleware:
    """Authentication middleware for JWT token validation"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        request = Request(scope, receive)
        
        # Skip authentication for certain endpoints
        if self._should_skip_auth(request.url.path):
            await self.app(scope, receive, send)
            return
        
        # Check for authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            await self.app(scope, receive, send)
            return
        
        # Extract and verify token
        token = auth_header.split(" ")[1]
        payload = verify_token(token)
        
        if not payload:
            await self.app(scope, receive, send)
            return
        
        # Add user information to request state
        request.state.user_id = payload.get("sub")
        request.state.user_email = payload.get("email")
        request.state.user_role = payload.get("role")
        request.state.user_company_id = payload.get("company_id")
        
        await self.app(scope, receive, send)
    
    def _should_skip_auth(self, path: str) -> bool:
        """Check if authentication should be skipped for this path"""
        skip_paths = [
            "/health",
            "/docs",
            "/api/docs",  # FastAPI docs_url is /api/docs in main.py
            "/redoc",
            "/openapi.json",
            "/api/openapi.json",  # OpenAPI JSON path used by Swagger UI.
            "/api/v1/auth/login",
            "/api/v1/auth/callback",
            "/api/v1/auth/refresh",
            "/api/v1/user-auth/login",  # Add user-auth login endpoint
            "/api/v1/user-auth/register",  # Add user-auth register endpoint
            "/api/v1/user-auth/forgot-password",  # Add forgot password endpoint
            "/api/v1/user-auth/reset-password",  # Add reset password endpoint
            "/api/v1/user-auth/set-password/request",  # Allow SSO users to request password setup.
            "/api/v1/user-auth/set-password/confirm",  # Allow password setup token confirmation.
            "/api/v1/sso/",  # Prefix skip covers both providers and callback/initiate paths.
            "/api/v1/agent/callback",
            "/api/v1/agent/status"
        ]
        
        return any(path.startswith(skip_path) for skip_path in skip_paths)


async def get_current_user(request: Request, db: Optional[AsyncSession] = None) -> Optional[User]:
    """Get current user from request state"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return None
    
    # If database session is provided, use it
    if db:
        # Query user from database
        from sqlalchemy import select
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            return None
        
        return user
    
    # Fallback: Get database session (this should be avoided in most cases)
    async for db_session in get_db():
        # Query user from database
        from sqlalchemy import select
        stmt = select(User).where(User.id == user_id)
        result = await db_session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            return None
        
        return user


async def _user_has_used_invitation(user: User, db: AsyncSession) -> bool:
    """True if this user was created via a used invitation (email + company_id match)."""
    if not user.email_id or not user.company_id:
        return False
    stmt = select(Invitation).where(
        Invitation.email == user.email_id,
        Invitation.company_id == user.company_id,
        Invitation.status == "used",
    ).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def get_current_user_required(request: Request, db: Optional[AsyncSession] = None) -> User:
    """Get current user, raise exception if not authenticated or not verified"""
    user = await get_current_user(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Block app access until email is verified, unless user was invited (has used invitation)
    if not getattr(user, "is_verified", True):
        if db is not None:
            has_used_invitation = await _user_has_used_invitation(user, db)
        else:
            async for session in get_db():
                has_used_invitation = await _user_has_used_invitation(user, session)
                break
            else:
                has_used_invitation = False
        if has_used_invitation:
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email to continue.",
        )
    return user



async def get_current_user_optional(request: Request, db: Optional[AsyncSession] = None) -> Optional[User]:
    """Get current user, return None if not authenticated"""
    return await get_current_user(request, db)


def require_auth(func):
    """Decorator to require authentication"""
    async def wrapper(*args, **kwargs):
        request = kwargs.get("request")
        if not request:
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
        
        if not request:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Request object not found"
            )
        
        user = await get_current_user_required(request)
        kwargs["current_user"] = user
        return await func(*args, **kwargs)
    
    return wrapper


def optional_auth(func):
    """Decorator for optional authentication"""
    async def wrapper(*args, **kwargs):
        request = kwargs.get("request")
        if not request:
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
        
        if request:
            user = await get_current_user_optional(request)
            kwargs["current_user"] = user
        
        return await func(*args, **kwargs)
    
    return wrapper 