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

from app.routes.user_auth import invite
from app.routes.user_auth import decrypt_registration
from app.routes.user_auth import bulk_invite
from app.routes.user_auth import register
from app.routes.user_auth import login
from app.routes.user_auth import request_set_password
from app.routes.user_auth import confirm_set_password
from app.routes.user_auth import get_profile
from app.routes.user_auth import upload_photo
from app.routes.user_auth import remove_photo
from app.routes.user_auth import update_profile
from app.routes.user_auth import update_password
from app.routes.user_auth import forgot_password
from app.routes.user_auth import reset_password

router = APIRouter()

# Preserve original registration order:
# invite_user, decrypt_registration_invite, bulk_invite_users,
# register_user, login_user,
# request_set_password, confirm_set_password,
# get_current_user_profile_details, upload_profile_image, remove_profile_photo,
# update_current_user_personal_info,
# update_current_user_password, forgot_password, reset_password
#
# registration.py, password_reset.py, invitations.py, profile.py, and
# sso_password.py were each further split (see
# docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up) into
# one file per endpoint; router inclusion order below is unchanged from the
# original registration order.
router.include_router(invite.router)
router.include_router(decrypt_registration.router)
router.include_router(bulk_invite.router)
router.include_router(register.router)
router.include_router(login.router)
router.include_router(request_set_password.router)
router.include_router(confirm_set_password.router)
router.include_router(get_profile.router)
router.include_router(upload_photo.router)
router.include_router(remove_photo.router)
router.include_router(update_profile.router)
router.include_router(update_password.router)
router.include_router(forgot_password.router)
router.include_router(reset_password.router)
