"""
Authentication/authorization for fetch_company_subscription_details.

Extracted from subscription_details.py: resolves the current user and
enforces that they belong to the requested company and hold the admin role.
"""
from typing import Any

from fastapi import HTTPException, Request, status

from app.middleware.auth_middleware import get_current_user_required


async def _authenticate_and_authorize(request: Request, company_id: Any) -> Any:
    """Return the authenticated admin user for `company_id`, or raise HTTPException."""
    user = await get_current_user_required(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    if str(user.company_id) != str(company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not belong to the requested company"
        )

    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only company admins can access subscription details"
        )

    return user
