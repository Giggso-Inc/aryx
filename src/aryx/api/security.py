"""API-key middleware for the Aryx REST surface (G4)."""
from __future__ import annotations

import logging
import os

from fastapi import Header, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

_EXEMPT_EXACT = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})
_EXEMPT_PREFIXES = ("/mcp",)

# CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T11: all three .env.example*
# files ship ARYX_INTERNAL_API_KEY set to this exact placeholder. A real
# deployment that copies an example file and never rotates it would have
# _verify_key() accept this publicly-known string as a valid shared
# secret. Rejected outright below rather than trusted like any other
# configured value -- a deployment still on the placeholder is treated
# the same as one with no internal key configured at all (falls through
# to McpTokenStore, which has its own real per-token verification).
_PLACEHOLDER_INTERNAL_KEYS = frozenset({"change_me_internal_aryx_token"})
_MIN_INTERNAL_KEY_LENGTH = 16


def _has_authenticated_header(request: Request) -> bool:
    """Allow only verified Aryx API keys or verified bearer tokens."""
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return _verify_key(token) if token else False
    key = request.headers.get("x-aryx-api-key", "").strip()
    return _verify_key(key) if key else False


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Verify X-Aryx-Api-Key against McpTokenStore for non-exempt REST routes.

    Mode is controlled by ARYX_API_AUTH env var:
      off      — middleware is a no-op (useful for local dev)
      optional — missing/invalid key passes but sets X-Aryx-Auth-Warning header
      required — missing/invalid key returns 401 (production setting)
    Default: required. Deployments that do not set ARYX_API_AUTH will enforce
    authentication. Set ARYX_API_AUTH=off to disable in local dev environments.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path in _EXEMPT_EXACT or any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        mode = os.environ.get("ARYX_API_AUTH", "required").lower()
        if mode == "off":
            return await call_next(request)

        valid = _has_authenticated_header(request)

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


def require_api_key(
    request: Request,
    x_aryx_api_key: str = Header(default=""),
) -> str:
    """Hard route-level guard — fails closed regardless of ARYX_API_AUTH mode.

    Use as a FastAPI dependency on admin endpoints that must always require a
    valid key, even when the global middleware is in 'optional' or 'off' mode.
    """
    if _has_authenticated_header(request):
        return x_aryx_api_key or request.headers.get("authorization", "")
    if not x_aryx_api_key or not _verify_key(x_aryx_api_key):
        raise HTTPException(
            status_code=401,
            detail="missing or invalid api key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return x_aryx_api_key


def write_api_key(x_aryx_api_key: str = Header(default="")) -> str | None:
    """Mode-aware auth guard for write operations.

    Respects ARYX_API_AUTH env var so dev workflows are not blocked:
      off      → passes through (no key required)
      optional → passes with a response warning header if key absent/invalid
      required → hard 401 if key absent/invalid (production setting)
    Default: required.
    """
    mode = os.environ.get("ARYX_API_AUTH", "required").lower()
    if mode == "off":
        return None
    key = x_aryx_api_key.strip()
    valid = _verify_key(key) if key else False
    if mode == "required" and not valid:
        raise HTTPException(
            status_code=401,
            detail="missing or invalid api key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return key if valid else None


def _verify_key(key: str) -> bool:
    """Verify an API key against the shared internal key or McpTokenStore."""
    configured_internal_key = os.environ.get("ARYX_INTERNAL_API_KEY", "").strip()
    if (
        configured_internal_key
        and configured_internal_key not in _PLACEHOLDER_INTERNAL_KEYS
        and len(configured_internal_key) >= _MIN_INTERNAL_KEY_LENGTH
        and key == configured_internal_key
    ):
        return True

    try:
        from aryx.config import get_settings
        from aryx.store.mcp_token_store import McpTokenStore
        store = McpTokenStore(get_settings().effective_dsn())
        try:
            return store.verify(key)
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001
        logger.error("api key check failed — failing closed: %s", exc)
        return False
