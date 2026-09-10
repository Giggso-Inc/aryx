"""
GET /{app_account_id} and DELETE /{app_account_id} — get_app_account,
delete_app_account.

Split out of the original app/routes/app_accounts.py (755 lines) as part of
the Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2). Grouped
together because both are simple single-resource operations keyed only by
app_account_id, with no request body or vault logic (unlike mutate.py's
update_app_account). Registration order between GET and DELETE on the same
dynamic path is irrelevant to FastAPI (it matches per method+path), so
combining them does not change effective routing versus the original file's
get-then-update-then-delete declaration order.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.app_account import AppAccount
from app.models.channel import Channel
from app.models.user import User
from app.schemas.app_account import AppAccountResponse

from .helpers import build_app_account_response

router = APIRouter()


@router.get("/{app_account_id}", response_model=AppAccountResponse)
async def get_app_account(
    app_account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> AppAccountResponse:
    """Get a specific app account by ID"""
    user = await get_current_user_required(request, db)

    # Get app account with channel company_id to avoid lazy loading
    app_account_stmt = select(AppAccount, Channel.company_id).join(Channel).where(AppAccount.id == app_account_id)
    app_account_result = await db.execute(app_account_stmt)
    app_account_row = app_account_result.first()

    if not app_account_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App account not found"
        )

    app_account, channel_company_id = app_account_row

    # Check if user has access to this connection
    if channel_company_id != user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this app account"
        )

    # Load connected user for user_metadata
    connected_user_stmt = select(User).where(User.id == app_account.connected_by)
    connected_user_result = await db.execute(connected_user_stmt)
    connected_user = connected_user_result.scalar_one_or_none()

    return build_app_account_response(app_account, connected_user)


@router.delete("/{app_account_id}")
async def delete_app_account(
    app_account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete an app account"""
    user = await get_current_user_required(request, db)

    # Get app account with channel company_id to avoid lazy loading
    app_account_stmt = select(AppAccount, Channel.company_id).join(Channel).where(AppAccount.id == app_account_id)
    app_account_result = await db.execute(app_account_stmt)
    app_account_row = app_account_result.first()

    if not app_account_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App account not found"
        )

    app_account, channel_company_id = app_account_row

    # Check if user has access to this connection
    if channel_company_id != user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this app account"
        )

    # Delete app account
    await db.delete(app_account)
    await db.commit()

    return {"message": "App account deleted successfully"}
