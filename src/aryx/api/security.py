"""API-key middleware for the Aryx REST surface (G4)."""
from __future__ import annotations

import logging
import os
from hmac import compare_digest

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_EXEMPT_EXACT = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})
_EXEMPT_PREFIXES = ("/mcp",)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Verify X-Aryx-Api-Key against McpTokenStore for non-exempt REST routes.

    Mode is controlled by ARYX_API_AUTH env var:
      off      — middleware is a no-op (useful for local dev)
      optional — missing/invalid key passes but sets X-Aryx-Auth-Warning header
      required — missing/invalid key returns 401 (production setting)
    Default: optional.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in _EXEMPT_EXACT or any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        mode = os.environ.get("ARYX_API_AUTH", "optional").lower()
        if mode == "off":
            return await call_next(request)

        key = request.headers.get("x-aryx-api-key", "").strip()
        valid = _verify_key(key) if key else False

        if mode == "required" and not valid:
            return JSONResponse(
                {"detail": "missing or invalid api key"},
                status_code=401,
                headers={"WWW-Authenticate": "ApiKey"},
            )

        response = await call_next(request)
        if mode == "optional" and not valid:
            response.headers["X-Aryx-Auth-Warning"] = "api-key-not-verified"
        return response


def _verify_key(key: str) -> bool:
    """Verify a configured service key or active managed token.

    The optional static key supports service-to-service integrations while the
    database-backed token store continues to support issue, revoke, and usage
    tracking for managed credentials.
    """
    try:
        from aryx.config import get_settings
        from aryx.store.mcp_token_store import McpTokenStore
        settings = get_settings()
        service_key = getattr(settings, "service_api_key", "")
        if isinstance(service_key, str) and service_key and compare_digest(key, service_key):
            return True
        store = McpTokenStore(settings.rdb_dsn)
        try:
            return store.verify(key)
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001
        logger.error("api key check failed — failing closed: %s", exc)
        return False


def require_api_key(request: Request) -> str:
    """Require a valid API key or bearer token for a sensitive operation."""
    authorization = request.headers.get("authorization", "").strip()
    key = (
        authorization[7:].strip()
        if authorization.lower().startswith("bearer ")
        else request.headers.get("x-aryx-api-key", "").strip()
    )
    if not key or not _verify_key(key):
        raise HTTPException(
            status_code=401,
            detail="missing or invalid api key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return key
