"""
User authentication routes for registration, login, and invitations.

This package handles all user authentication operations including user registration,
login/logout, password management, and invitation workflows. It provides secure
JWT-based authentication and manages user sessions with proper security measures.

Split from a single 1,870-line module into this package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5) — one submodule per
sub-resource, combined here into a single `router` in the original endpoint
order so route precedence and external behavior (main.py's
`user_auth.router` usage, `app/routes/__init__.py`'s re-export) are unchanged.

Author: Karthick Chandrasekar
Date: 2025-08-14
Version: 1.0.0
"""

from fastapi import APIRouter

from app.routes.user_auth import invitations
from app.routes.user_auth import registration
from app.routes.user_auth import sso_password
from app.routes.user_auth import profile
from app.routes.user_auth import password_reset

router = APIRouter()

# Preserve original registration order:
# invite_user, decrypt_registration_invite, bulk_invite_users,
# register_user, login_user,
# request_set_password, confirm_set_password,
# get_current_user_profile_details, upload_profile_image, remove_profile_photo,
# update_current_user_personal_info,
# update_current_user_password, forgot_password, reset_password
router.include_router(invitations.router)
router.include_router(registration.router)
router.include_router(sso_password.router)
router.include_router(profile.router)
router.include_router(password_reset.router)
