"""
Profile route: get_current_user_profile_details.

Split out of the original monolithic profile.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up).
"""

from fastapi import APIRouter, Request

from app.middleware.auth_middleware import get_current_user_required

from app.routes.user_auth._profile_helpers import _build_user_profile_dict

router = APIRouter()


@router.get("/profile", response_model=dict)
async def get_current_user_profile_details(
    request: Request,
) -> dict:
    """
    Get current user's detailed profile information.

    This endpoint retrieves the authenticated user's profile details with
    personal information, role, and preferences.

    Args:
        request: FastAPI request object for authentication

    Returns:
        dict: Current user's detailed profile information

    Raises:
        HTTPException: 401 if not authenticated

    Sample Response Schema:
    {
        "id": "uuid-string",
        "name": "John Doe",
        "email_id": "john.doe@example.com",
        "avatar_url": "https://example.com/avatar.jpg",
        "role": "senior_developer",
        "is_active": true,
        "is_verified": true,
        "oauth_provider": "local",
        "preferences": {
            "theme": "dark",
            "language": "en",
            "notifications": true
        },
        "last_login": "2025-01-20T10:30:00Z",
        "created_datetime": "2025-01-15T09:00:00Z",
        "updated_datetime": "2025-01-20T10:30:00Z"
    }

    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 20/01/2025
    """
    user = await get_current_user_required(request)
    return _build_user_profile_dict(user)
