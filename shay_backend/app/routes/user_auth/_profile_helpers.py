"""
Shared helper for the profile routes.

Split out of the original monolithic profile.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up).
`get_current_user_profile_details` and `update_current_user_personal_info`
both build the exact same user-profile response dict; consolidated here
since it's reused by 2+ endpoints.
"""

from app.models.user import User


def _build_user_profile_dict(user: User) -> dict:
    """Build the standard user-profile response dict shared by profile endpoints."""
    return {
        "id": str(user.id),
        "name": user.name,
        "email_id": user.email_id,
        "avatar_url": user.avatar_url,
        "role": user.role,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "oauth_provider": user.oauth_provider,
        "preferences": user.preferences,
        "last_login": user.last_login,
        "created_datetime": user.created_datetime,
        "updated_datetime": user.updated_datetime,
    }
