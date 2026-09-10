"""
Login route: login (initiate OAuth2 login with Google).

Split out of the original monolithic app/routes/auth.py (312 lines, over the
150-line hard limit) — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5 (final wave). One endpoint per file, aggregated back into a single
`router` by app/routes/auth/__init__.py in the original registration order.
"""

from fastapi import APIRouter

from app.core.config import settings
from app.schemas.auth import OAuthLogin

router = APIRouter()


@router.post("/login", response_model=dict)
async def login(login_data: OAuthLogin) -> dict:
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
