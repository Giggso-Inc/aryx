"""Google OAuth: authorization URL + code-exchange/ID-token verification."""

from urllib.parse import urlencode

import httpx
from jose import jwt, JWTError

from app.core.config import settings
from .errors import ProviderError

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


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
