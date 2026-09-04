"""Auto-login after signup: POST /autoLogin."""

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.auth import create_access_token, create_refresh_token, verify_password
from app.core.config import settings
from app.models.user import User
from app.schemas.user import UserTokenResponse

router = APIRouter()


@router.post("/autoLogin", response_model=UserTokenResponse)
async def auto_login_after_signup(
    email: str,
    password: str,
    db: AsyncSession = Depends(get_db)
) -> UserTokenResponse:
    """
    Auto-login after successful company creation.

    Called automatically after company creation to authenticate the new user.
    """
    try:
        # Find user by email
        result = await db.execute(
            select(User).where(User.email_id == email)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Verify password
        if not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )

        # Generate tokens
        access_token = create_access_token(
            data={"sub": str(user.id), "company_id": str(user.company_id), "role": user.role}
        )
        refresh_token = create_refresh_token(
            data={"sub": str(user.id), "company_id": str(user.company_id), "role": user.role}
        )

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
            company_id=str(user.company_id)
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}"
        )
