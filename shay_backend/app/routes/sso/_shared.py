"""
Shared constants and error-response helpers for the SSO route package.

Split out of the original monolithic app/routes/sso.py (233 lines, over the
150-line hard limit) — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5 (final wave). Used by both initiate.py and callback.py.
"""

from urllib.parse import urlencode

from fastapi.responses import JSONResponse, RedirectResponse

ALLOWED_PROVIDERS = ["google", "microsoft"]

# Fields from UserTokenResponse.model_dump() allowed into the callback's
# base64url fragment payload (#sso_data=...); anything else (and any None
# value) is dropped before encoding.
TOKEN_FIELDS = {
    "access_token", "refresh_token", "token_type", "expires_in",
    "user_id", "email_id", "name", "full_name", "role", "company_id",
}

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
