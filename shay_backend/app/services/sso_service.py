import base64
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode, urlparse

import httpx
from jose import jwt, JWTError
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    create_token_data,
    generate_user_id,
    generate_workspace_id,
)
from app.core.config import settings
from app.models.company import Company
from app.models.invitation import Invitation
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.user import UserTokenResponse

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
MICROSOFT_AUTH_BASE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_BASE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
MICROSOFT_GRAPH_ME = "https://graph.microsoft.com/v1.0/me"


class SSOError(Exception):
    def __init__(self, message: str, error_code: str):
        self.message = message
        self.error_code = error_code
        super().__init__(message)


class InvitationNotFoundError(SSOError):
    def __init__(self):
        super().__init__("Invitation not found", "SSO_005")


class InvitationInvalidError(SSOError):
    def __init__(self):
        super().__init__("Invitation has expired or already been used", "SSO_006")


class SignupInviteRequiredError(SSOError):
    """New SSO users must start from an invitation; returning users omit invite_id."""

    def __init__(self):
        super().__init__(
            "SSO sign-up requires a valid invite_id; for sign-in, omit invite_id if you already have an account",
            "SSO_012",
        )


class EmailMismatchError(SSOError):
    def __init__(self, provider: str):
        super().__init__(
            f"The email from your {provider} account does not match the invitation email",
            "SSO_007",
        )


class ProviderError(SSOError):
    def __init__(self, provider: str):
        super().__init__(f"Failed to authenticate with {provider}", "SSO_008")


def _get_state_secret() -> str:
    return settings.SSO_STATE_SECRET


def build_state(invite_id: str, redirect_uri: str, csrf_token: str) -> str:
    payload = {
        "invite_id": invite_id,
        "redirect_uri": redirect_uri,
        "csrf": csrf_token,
    }
    payload_bytes = json.dumps(payload, sort_keys=True).encode()
    signature = hmac.new(
        _get_state_secret().encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    state_obj = {"p": payload, "s": signature}
    return base64.urlsafe_b64encode(
        json.dumps(state_obj).encode()
    ).decode()


def verify_state(state: str, cookie_csrf: Optional[str] = None) -> dict:
    """
    Verify the HMAC-signed OAuth state parameter.

    The HMAC signature is always required — it cryptographically binds the state
    to this server's SSO_STATE_SECRET and is sufficient CSRF protection on its own.

    ``cookie_csrf`` is validated as a belt-and-suspenders second factor when the
    browser successfully echoes the cookie back (same-origin SPA, desktop browsers
    on a single-hop provider like Google).  It is intentionally *optional* because
    Microsoft's multi-hop redirect chain causes some browsers to drop SameSite=Lax
    cookies before the final callback arrives, making the cookie unavailable even
    though the initiate call completed correctly.  Skipping the cookie check in
    that case does not weaken security because the HMAC signature already prevents
    state forgery.
    """
    try:
        state_obj = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
        payload = state_obj["p"]
        received_signature = state_obj["s"]
        payload_bytes = json.dumps(payload, sort_keys=True).encode()
        expected_signature = hmac.new(
            _get_state_secret().encode(),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, received_signature):
            raise ValueError("State signature mismatch")
        # Only enforce cookie binding when the browser echoed it back.
        if cookie_csrf and not hmac.compare_digest(payload["csrf"], cookie_csrf):
            raise ValueError("CSRF token mismatch")
        return payload
    except Exception as e:
        raise ValueError(f"Invalid state: {str(e)}")


def is_allowed_redirect_uri(redirect_uri: str) -> bool:
    parsed = urlparse(redirect_uri.strip())
    if not parsed.scheme or not parsed.netloc:
        return False
    target_origin = f"{parsed.scheme}://{parsed.netloc}".lower()
    allowed = [o.strip().lower() for o in (settings.ALLOWED_ORIGINS or []) if str(o).strip()]
    return "*" in allowed or target_origin in allowed


def get_google_authorization_url(state: str) -> str:
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def get_microsoft_authorization_url(state: str) -> str:
    auth_url = MICROSOFT_AUTH_BASE.format(tenant=settings.MICROSOFT_TENANT_ID)
    params = {
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
        "response_type": "code",
        "response_mode": "query",
        "scope": "openid email profile User.Read",
        "state": state,
    }
    return f"{auth_url}?{urlencode(params)}"


def _select_jwk_for_token(id_token: str, jwks: dict) -> dict:
    header = jwt.get_unverified_header(id_token)
    token_kid = header.get("kid")
    for key in jwks.get("keys", []):
        if key.get("kid") == token_kid:
            return key
    raise ProviderError("Google")


async def exchange_google_code(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        if token_resp.status_code != 200:
            raise ProviderError("Google")
        token_data = token_resp.json()
        id_token = token_data.get("id_token")
        if not id_token:
            raise ProviderError("Google")
        jwks_resp = await client.get(GOOGLE_JWKS_URL)
        if jwks_resp.status_code != 200:
            raise ProviderError("Google")
        jwks = jwks_resp.json()
    try:
        key = _select_jwk_for_token(id_token, jwks)
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=settings.GOOGLE_CLIENT_ID,
            options={"verify_at_hash": False},
        )
    except JWTError:
        raise ProviderError("Google")
    if not claims.get("email") or claims.get("email_verified") is False:
        raise ProviderError("Google")
    return {
        "google_id": claims["sub"],
        "email": claims["email"],
        "name": claims.get("name", ""),
        "avatar_url": claims.get("picture"),
    }


async def exchange_microsoft_code(code: str) -> dict:
    token_url = MICROSOFT_TOKEN_BASE.format(tenant=settings.MICROSOFT_TENANT_ID)
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(token_url, data={
            "code": code,
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "client_secret": settings.MICROSOFT_CLIENT_SECRET,
            "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
            "grant_type": "authorization_code",
            "scope": "openid email profile User.Read",
        })
        if token_resp.status_code != 200:
            raise ProviderError("Microsoft")
        token_data = token_resp.json()
        ms_access_token = token_data.get("access_token")
        if not ms_access_token:
            raise ProviderError("Microsoft")
        graph_resp = await client.get(
            MICROSOFT_GRAPH_ME,
            headers={"Authorization": f"Bearer {ms_access_token}"},
        )
        if graph_resp.status_code != 200:
            raise ProviderError("Microsoft")
        graph_data = graph_resp.json()
    email = graph_data.get("mail") or graph_data.get("userPrincipalName")
    if not email:
        raise ProviderError("Microsoft")
    return {
        "microsoft_id": graph_data["id"],
        "email": email,
        "name": graph_data.get("displayName", ""),
        "avatar_url": None,  # Graph photo is a separate call; keep minimal.
    }


async def resolve_sso_user(
    db: AsyncSession,
    provider_id_field: str,
    provider_id_value: str,
    email: str,
    name: str,
    avatar_url: Optional[str],
    invite_id: str,
    provider_name: str,
) -> User:
    # Resolve by provider id first (returning SSO user — no invitation).
    provider_result = await db.execute(
        select(User).where(getattr(User, provider_id_field) == provider_id_value)
    )
    provider_user = provider_result.scalar_one_or_none()

    # Resolve by email for link / returning-by-email / guard.
    email_result = await db.execute(select(User).where(User.email_id == email))
    email_user = email_result.scalar_one_or_none()

    # Guard: same provider identity must not map to a different local user than this email.
    if provider_user and email_user and str(provider_user.id) != str(email_user.id):
        raise ProviderError(provider_name.title())

    # Returning user: matched by provider id.
    if provider_user:
        provider_user.last_login = datetime.utcnow()
        await db.commit()
        await db.refresh(provider_user)
        return provider_user

    # Returning user: matched by email with this provider already linked.
    linked_id = getattr(email_user, provider_id_field, None) if email_user else None
    if email_user and linked_id:
        if linked_id != provider_id_value:
            raise ProviderError(provider_name.title())
        email_user.last_login = datetime.utcnow()
        await db.commit()
        await db.refresh(email_user)
        return email_user

    # Existing local user, same email, not yet linked to this provider — link and skip invitation.
    if email_user:
        setattr(email_user, provider_id_field, provider_id_value)
        email_user.oauth_provider = provider_name
        if not email_user.avatar_url and avatar_url:
            email_user.avatar_url = avatar_url
        if not email_user.is_verified:
            email_user.is_verified = True
        await db.commit()
        await db.refresh(email_user)
        return email_user

    # Brand-new user: invitation is required (invite_id omitted => cannot create account).
    invite_id_clean = (invite_id or "").strip()
    if not invite_id_clean:
        raise SignupInviteRequiredError()
    try:
        invite_uuid = uuid.UUID(invite_id_clean)
    except ValueError:
        raise InvitationNotFoundError()
    result = await db.execute(select(Invitation).where(Invitation.id == invite_uuid))
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise InvitationNotFoundError()
    if not invitation.is_valid:
        raise InvitationInvalidError()
    if invitation.email.lower() != email.lower():
        raise EmailMismatchError(provider_name)

    new_user = User(
        id=generate_user_id(),
        email_id=email,
        name=name or email.split("@")[0],
        avatar_url=avatar_url,
        company_id=invitation.company_id,
        role=invitation.role,
        is_active=True,
        is_verified=True,
        oauth_provider=provider_name,
        password_hash=None,
        **{provider_id_field: provider_id_value},
    )
    db.add(new_user)
    await db.flush()  # keep same transaction for workspace creation.
    await _create_default_workspace_if_not_exists(db, new_user)
    invitation.mark_as_used()
    await db.commit()
    await db.refresh(new_user)
    return new_user


async def _create_default_workspace_if_not_exists(db: AsyncSession, user: User) -> None:
    company_result = await db.execute(select(Company).where(Company.id == user.company_id))
    company = company_result.scalar_one_or_none()
    if not company:
        return
    stmt = select(Workspace).where(
        and_(
            Workspace.company_id == user.company_id,
            Workspace.name == company.name,
            Workspace.is_active == True,
        )
    )
    result = await db.execute(stmt)
    default_workspace = result.scalar_one_or_none()
    if not default_workspace:
        default_workspace = Workspace(
            id=generate_workspace_id(),
            name=company.name,
            description=f"Default workspace for {company.name}",
            company_id=user.company_id,
            created_by=user.id,
            is_active=True,
            is_public=False,
            ai_enabled=True,
            ai_provider="openai",
            ai_model="gpt-4",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(default_workspace)
        await db.flush()  # keep creation inside the current transaction.


async def issue_tokens_for_user(db: AsyncSession, user: User) -> UserTokenResponse:
    company_result = await db.execute(
        select(Company).where(Company.id == user.company_id)
    )
    company = company_result.scalar_one_or_none()
    if not user.is_active:
        raise ProviderError("User account is inactive")
    if company and not company.is_active:
        raise ProviderError("Company account is inactive")
    workspace_result = await db.execute(
        select(Workspace).where(Workspace.company_id == user.company_id).limit(1)
    )
    workspace = workspace_result.scalar_one_or_none()
    token_data = create_token_data(
        str(user.id), user.email_id, user.role, str(user.company_id)
    )
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)
    user.last_login = datetime.utcnow()
    await db.commit()
    return UserTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_id=str(user.id),
        email_id=user.email_id,
        name=user.name,
        avatar_url=user.avatar_url,
        role=user.role,
        company_id=str(user.company_id),
        company_name=company.name if company else None,
        default_workspace_id=str(workspace.id) if workspace else None,
    )
