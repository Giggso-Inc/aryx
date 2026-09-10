"""
Callback route: sso_callback (GET /{provider}/callback).

Split out of the original monolithic app/routes/sso.py (233 lines, over the
150-line hard limit) — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5 (final wave). One endpoint per file, aggregated back into a single
`router` by app/routes/sso/__init__.py in the original registration order.

Kept as one file (146 lines, under the 150-line limit — no exception
needed): state verification, IdP token exchange, user resolution, and
token issuance form one continuous exception-to-fragment-redirect chain
that resists being cut without duplicating the redirect-error plumbing
across modules.
"""

import base64
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.user import UserTokenResponse
from app.services.sso_service import (
    verify_state,
    is_allowed_redirect_uri,
    exchange_google_code,
    exchange_microsoft_code,
    resolve_sso_user,
    issue_tokens_for_user,
    InvitationNotFoundError,
    InvitationInvalidError,
    SignupInviteRequiredError,
    EmailMismatchError,
    ProviderError,
)
from app.routes.sso._shared import _json_sso_error, _fragment_error_redirect, TOKEN_FIELDS

router = APIRouter(tags=["SSO"])


@router.get(
    "/{provider}/callback",
    response_model=UserTokenResponse,
    responses={
        400: {"description": "Invalid state, invitation, or provider error"},
        401: {"description": "Missing or expired SSO session (CSRF cookie)"},
        403: {"description": "User denied consent at provider"},
        404: {"description": "Invitation not found"},
        502: {"description": "Token exchange or upstream provider failure"},
    },
)
async def sso_callback(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    code: str = Query(default=None),
    state: str = Query(default=None),
    error: str = Query(default=None),
) -> UserTokenResponse:
    # OAuth providers append code/state/error as query params on this backend URL.
    code = request.query_params.get("code") or code
    state = request.query_params.get("state") or state
    error = request.query_params.get("error") or error

    if error:
        return _json_sso_error(403, "access_denied")

    # Read cookie — present for single-hop providers (Google) and same-origin SPAs;
    # may be absent for Microsoft due to its multi-hop redirect chain dropping
    # SameSite=Lax cookies in modern browsers.  verify_state() treats it as
    # optional: the HMAC signature on the state is sufficient CSRF protection.
    cookie_csrf = request.cookies.get("sso_csrf")

    if not state:
        return _json_sso_error(400, "invalid_state")

    # Malformed callbacks can swallow provider params into state and leave code unset.
    if "&code=" in state or "&iss=" in state or "%26code%3D" in state or "%26iss%3D" in state:
        return _json_sso_error(400, "invalid_state")

    try:
        state_data = verify_state(state, cookie_csrf)
    except ValueError:
        return _json_sso_error(400, "invalid_state")

    invite_id = state_data.get("invite_id") or ""
    redirect_uri = state_data["redirect_uri"].strip()

    if not is_allowed_redirect_uri(redirect_uri):
        return _json_sso_error(400, "invalid_redirect")
    if not code:
        return _fragment_error_redirect(redirect_uri, "provider_error")
    try:
        if provider == "google":
            provider_data = await exchange_google_code(code)
            provider_id_field = "google_id"
            provider_id_value = provider_data["google_id"]
        elif provider == "microsoft":
            provider_data = await exchange_microsoft_code(code)
            provider_id_field = "microsoft_id"
            provider_id_value = provider_data["microsoft_id"]
        else:
            return _fragment_error_redirect(redirect_uri, "unknown_provider")
    except ProviderError:
        return _fragment_error_redirect(redirect_uri, "provider_error")
    except Exception:
        return _fragment_error_redirect(redirect_uri, "provider_error")
    try:
        user = await resolve_sso_user(
            db=db,
            provider_id_field=provider_id_field,
            provider_id_value=provider_id_value,
            email=provider_data["email"],
            name=provider_data["name"],
            avatar_url=provider_data.get("avatar_url"),
            invite_id=invite_id,
            provider_name=provider,
        )
    except InvitationNotFoundError:
        return _fragment_error_redirect(redirect_uri, "invitation_not_found")
    except SignupInviteRequiredError:
        return _fragment_error_redirect(redirect_uri, "signup_requires_invite")
    except InvitationInvalidError:
        return _fragment_error_redirect(redirect_uri, "invitation_invalid")
    except EmailMismatchError:
        return _fragment_error_redirect(redirect_uri, "email_mismatch")
    except Exception:
        return _fragment_error_redirect(redirect_uri, "provider_error")

    try:
        token_response = await issue_tokens_for_user(db, user)
    except Exception:
        return _fragment_error_redirect(redirect_uri, "provider_error")

    # Redirect to the frontend /sso-callback with tokens encoded as a single
    # base64url JSON fragment param (#sso_data=...).  A flat urlencode of
    # multiple JWT-sized values can exceed browser/server URI length limits,
    # so the entire payload is packed into one compact parameter instead.
    data = token_response.model_dump()
    payload = {k: v for k, v in data.items() if k in TOKEN_FIELDS and v is not None}
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(',', ':')).encode()
    ).decode().rstrip('=')
    response = RedirectResponse(url=f"{redirect_uri}#sso_data={payload_b64}", status_code=302)
    response.delete_cookie("sso_csrf")
    return response
