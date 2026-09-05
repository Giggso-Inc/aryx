"""Microsoft (Entra ID) OAuth: authorization URL + code-exchange/Graph lookup."""

from urllib.parse import urlencode

import httpx

from app.core.config import settings
from .errors import ProviderError

MICROSOFT_AUTH_BASE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_BASE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
MICROSOFT_GRAPH_ME = "https://graph.microsoft.com/v1.0/me"


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
