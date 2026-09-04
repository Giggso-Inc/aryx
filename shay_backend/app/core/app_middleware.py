"""
Middleware registration for the FastAPI application.

Extracted from main.py during Raven Phase 5a file-size compliance work.
main.py keeps its own `app = FastAPI(...)` construction and lifespan
wiring; this module is called once, right after that construction, via
`register_middleware(app)`.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import settings
from app.middleware.auth_middleware import AuthMiddleware


def _cors_origins_for_credentials() -> list:
    """
    Starlette + allow_credentials=True cannot use wildcard Allow-Origin; SSO initiate uses Set-Cookie cross-origin.
    Strip entries, drop '*', and fall back to local dev origins if the env list is only '*'/empty.
    """
    cleaned = [o.strip() for o in settings.ALLOWED_ORIGINS if o and str(o).strip()]
    explicit = [o for o in cleaned if o != "*"]
    if explicit:
        return explicit
    return [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ]


def register_middleware(app: FastAPI) -> None:
    """Attach CORS, trusted-host, and authentication middleware to `app`."""
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins_for_credentials(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add trusted host middleware
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.ALLOWED_HOSTS
    )

    # Add authentication middleware
    app.add_middleware(AuthMiddleware)
