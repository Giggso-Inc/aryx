import base64
import json
import secrets
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.sso import SSOInitiateResponse
from app.schemas.user import UserTokenResponse
from app.services.sso_service import (
    build_state,
    verify_state,
    is_allowed_redirect_uri,
    get_google_authorization_url,
    get_microsoft_authorization_url,
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

router = APIRouter(tags=["SSO"])

ALLOWED_PROVIDERS = ["google", "microsoft"]

# Maps callback failure slugs to stable API codes (JSON body, same style as initiate errors).
_SSO_CALLBACK_ERRORS: dict[str, tuple[str, str]] = {
    "access_denied": ("SSO_003", "User denied access at the identity provider"),
    "session_expired": (
        "SSO_004",
        "Missing sso_csrf cookie: call initiate again in this same browser, use the same API host as "
        "GOOGLE_REDIRECT_URI/MICROSOFT_REDIRECT_URI (do not mix localhost and 127.0.0.1), and for SPA use "
        "fetch(..., { credentials: 'include' }) so Set-Cookie is stored.",
    ),
    "invalid_state": ("SSO_009", "Invalid or tampered OAuth state"),
    "invalid_redirect": ("SSO_002", "redirect_uri in state is not allowed"),
    "provider_error": ("SSO_008", "Token exchange or identity provider error"),
    "unknown_provider": ("SSO_010", "Unknown provider in callback path"),
    "invitation_not_found": ("SSO_005", "Invitation not found"),
    "invitation_invalid": ("SSO_006", "Invitation expired or already used"),
    "email_mismatch": ("SSO_007", "SSO account email does not match the invitation"),
    "signup_requires_invite": (
        "SSO_012",
        "SSO sign-up requires invite_id; returning users should call initiate without invite_id",
    ),
}


def _json_sso_error(status_code: int, error_slug: str) -> JSONResponse:
    """Used for early errors only — before redirect_uri is available and trusted."""
    code, message = _SSO_CALLBACK_ERRORS.get(
        error_slug, ("SSO_011", error_slug.replace("_", " ").title())
    )
    response = JSONResponse(status_code=status_code, content={"error_code": code, "message": message})
    response.delete_cookie("sso_csrf")
    return response


def _fragment_error_redirect(redirect_uri: str, error_slug: str) -> RedirectResponse:
    """Redirect to the frontend /sso-callback with error info in the URL fragment.
    The FE's parseSsoCallbackErrorsFromLocation() reads error_code + message from the hash.
    """
    code, message = _SSO_CALLBACK_ERRORS.get(
        error_slug, ("SSO_011", error_slug.replace("_", " ").title())
    )
    fragment = urlencode({"error_code": code, "message": message})
    response = RedirectResponse(url=f"{redirect_uri}#{fragment}", status_code=302)
    response.delete_cookie("sso_csrf")
    return response


@router.get("/{provider}/initiate", response_model=SSOInitiateResponse)
async def sso_initiate(
    provider: str,
    redirect_uri: str = Query(...),
    invite_id: Optional[str] = Query(
        None,
        description="Invitation UUID for first-time sign-up; omit for returning SSO sign-in.",
    ),
):
    redirect_uri = redirect_uri.strip()  # normalize frontend redirect input before validation/signing.
    invite_for_state = (invite_id or "").strip()  # empty embeds in state when signing in without an invite.

    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(400, detail={
            "error_code": "SSO_001",
            "message": f"Unknown provider '{provider}'. Allowed: {ALLOWED_PROVIDERS}",
        })
    if not is_allowed_redirect_uri(redirect_uri):
        raise HTTPException(400, detail={
            "error_code": "SSO_002",
            "message": "redirect_uri is not in the list of allowed origins",
        })
    csrf_token = secrets.token_urlsafe(32)
    state = build_state(invite_for_state, redirect_uri, csrf_token)
    if provider == "google":
        auth_url = get_google_authorization_url(state)
    else:
        auth_url = get_microsoft_authorization_url(state)
    response = JSONResponse(
        content=SSOInitiateResponse(
            authorization_url=auth_url,
            state=state,
        ).dict()
    )
    response.set_cookie(
        key="sso_csrf",
        value=csrf_token,
        httponly=True,
        samesite="lax",
        max_age=600,
    )
    return response


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
):
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
    _TOKEN_FIELDS = {
        "access_token", "refresh_token", "token_type", "expires_in",
        "user_id", "email_id", "name", "full_name", "role", "company_id",
    }
    data = token_response.model_dump()
    payload = {k: v for k, v in data.items() if k in _TOKEN_FIELDS and v is not None}
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(',', ':')).encode()
    ).decode().rstrip('=')
    response = RedirectResponse(url=f"{redirect_uri}#sso_data={payload_b64}", status_code=302)
    response.delete_cookie("sso_csrf")
    return response