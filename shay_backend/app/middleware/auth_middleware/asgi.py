"""
Raw ASGI middleware that verifies the Bearer JWT (if present) and stamps
request.state with the decoded user fields — never blocks a request itself
(that's left to the get_current_user_required dependency downstream).

Split out of app/middleware/auth_middleware.py — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.
"""

from fastapi import Request

from app.core.auth import verify_token


class AuthMiddleware:
    """Authentication middleware for JWT token validation"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        # Skip authentication for certain endpoints
        if self._should_skip_auth(request.url.path):
            await self.app(scope, receive, send)
            return

        # Check for authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            await self.app(scope, receive, send)
            return

        # Extract and verify token
        token = auth_header.split(" ")[1]
        payload = verify_token(token)

        if not payload:
            await self.app(scope, receive, send)
            return

        # Add user information to request state
        request.state.user_id = payload.get("sub")
        request.state.user_email = payload.get("email")
        request.state.user_role = payload.get("role")
        request.state.user_company_id = payload.get("company_id")

        await self.app(scope, receive, send)

    def _should_skip_auth(self, path: str) -> bool:
        """Check if authentication should be skipped for this path"""
        skip_paths = [
            "/health",
            "/docs",
            "/api/docs",  # FastAPI docs_url is /api/docs in main.py
            "/redoc",
            "/openapi.json",
            "/api/openapi.json",  # OpenAPI JSON path used by Swagger UI.
            "/api/v1/auth/login",
            "/api/v1/auth/callback",
            "/api/v1/auth/refresh",
            "/api/v1/user-auth/login",  # Add user-auth login endpoint
            "/api/v1/user-auth/register",  # Add user-auth register endpoint
            "/api/v1/user-auth/decrypt-registration",  # Allow invited users to prefill registration form
            "/api/v1/user-auth/forgot-password",  # Add forgot password endpoint
            "/api/v1/user-auth/reset-password",  # Add reset password endpoint
            "/api/v1/user-auth/set-password/request",  # Allow SSO users to request password setup.
            "/api/v1/user-auth/set-password/confirm",  # Allow password setup token confirmation.
            "/api/v1/sso/",  # Prefix skip covers both providers and callback/initiate paths.
            "/api/v1/agent/callback",
            "/api/v1/agent/status"
        ]

        return any(path.startswith(skip_path) for skip_path in skip_paths)
