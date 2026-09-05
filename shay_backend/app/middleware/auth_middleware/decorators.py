"""
require_auth / optional_auth decorators for plain function-style endpoints
that aren't using FastAPI's Depends() injection.

Split out of app/middleware/auth_middleware.py — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.
"""

from typing import Any, Callable

from fastapi import Request, HTTPException, status

from app.middleware.auth_middleware.current_user import get_current_user_optional, get_current_user_required


def require_auth(func) -> Callable:
    """Decorator to require authentication"""
    async def wrapper(*args, **kwargs) -> Any:
        request = kwargs.get("request")
        if not request:
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

        if not request:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Request object not found"
            )

        user = await get_current_user_required(request)
        kwargs["current_user"] = user
        return await func(*args, **kwargs)

    return wrapper


def optional_auth(func) -> Callable:
    """Decorator for optional authentication"""
    async def wrapper(*args, **kwargs) -> Any:
        request = kwargs.get("request")
        if not request:
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

        if request:
            user = await get_current_user_optional(request)
            kwargs["current_user"] = user

        return await func(*args, **kwargs)

    return wrapper
