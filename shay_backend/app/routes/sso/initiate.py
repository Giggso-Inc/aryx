"""
Initiate route: sso_initiate (GET /{provider}/initiate).

Split out of the original monolithic app/routes/sso.py (233 lines, over the
150-line hard limit) — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
wave B5 (final wave). One endpoint per file, aggregated back into a single
`router` by app/routes/sso/__init__.py in the original registration order.
"""

import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from app.schemas.sso import SSOInitiateResponse
from app.services.sso_service import (
    build_state,
    is_allowed_redirect_uri,
    get_google_authorization_url,
    get_microsoft_authorization_url,
)
from app.routes.sso._shared import ALLOWED_PROVIDERS

router = APIRouter(tags=["SSO"])


@router.get("/{provider}/initiate", response_model=SSOInitiateResponse)
async def sso_initiate(
    provider: str,
    redirect_uri: str = Query(...),
    invite_id: Optional[str] = Query(
        None,
        description="Invitation UUID for first-time sign-up; omit for returning SSO sign-in.",
    ),
) -> SSOInitiateResponse:
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
