"""
Refresh route: refresh_token (refresh JWT access token).

Split out of the original monolithic app/routes/auth.py (312 lines, over the
150-line hard limit) — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5 (final wave). One endpoint per file, aggregated back into a single
`router` by app/routes/auth/__init__.py in the original registration order.
"""

from fastapi import APIRouter, HTTPException, status

from app.core.auth import create_access_token
from app.core.config import settings
from app.schemas.auth import Token, RefreshToken

router = APIRouter()


@router.post("/refresh", response_model=Token)
async def refresh_token(refresh_data: RefreshToken) -> Token:
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
