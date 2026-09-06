"""
Logout route: logout (invalidate refresh token).

Split out of the original monolithic app/routes/auth.py (312 lines, over the
150-line hard limit) — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5 (final wave). One endpoint per file, aggregated back into a single
`router` by app/routes/auth/__init__.py in the original registration order.
"""

from fastapi import APIRouter

from app.schemas.auth import LogoutRequest

router = APIRouter()


@router.post("/logout")
async def logout(logout_data: LogoutRequest) -> dict:
    """Logout user (invalidate refresh token)"""
    # In a real implementation, you might want to blacklist the refresh token
    # For now, we'll just return success
    return {"message": "Successfully logged out"}
