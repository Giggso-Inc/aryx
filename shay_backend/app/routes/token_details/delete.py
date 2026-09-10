"""
DELETE /deleteTokenDetails — delete_token_details.

Split out of the original app/routes/token_details.py (767 lines) as part of
the Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.giggso_vault import GiggsoVault
from app.schemas.common import (
    DeleteTokenDetailsRequest,
    DeleteTokenDetailsResponse,
    SuccessResponse,
)
from app.services.vault_service import vault_service

router = APIRouter()


@router.delete("/deleteTokenDetails", response_model=SuccessResponse[DeleteTokenDetailsResponse])
async def delete_token_details(
    request: Request,
    payload: DeleteTokenDetailsRequest,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[DeleteTokenDetailsResponse]:
    """
    Delete token/API details for a company from vault and remove gg_vault entry (authenticated).

    Flow:
    - Require JWT (non-public).
    - Find gg_vault record by companyId and vault_type='gpt_token' to get vault_unique_id.
    - Delete stored details from vault.
    - Delete gg_vault row.
    """
    # Enforce authentication and get the current user (authorization decisions below use this)
    user = await get_current_user_required(request, db)

    try:
        # Parse companyId and prevent cross-company deletes by non-admin users
        try:
            company_uuid = uuid.UUID(payload.companyId)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid companyId format (must be a valid UUID)",
            )

        # Basic authorization: only allow deletes within the caller's company unless caller is admin
        if str(user.company_id) != str(company_uuid) and getattr(user, "role", "").lower() != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not allowed to delete token details for another company.",
            )

        # Fetch existing gg_vault record for this company and vault type
        stmt = (
            select(GiggsoVault)
            .where(
                GiggsoVault.company_id == company_uuid,
                GiggsoVault.vault_type == "gpt_token",
            )
            .order_by(GiggsoVault.created_datetime.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        vault_record = result.scalar_one_or_none()

        if not vault_record or not vault_record.vault_unique_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No token details found for this company (vault_type='gpt_token').",
            )

        vault_unique_id = vault_record.vault_unique_id

        # Delete from external vault first
        deleted_in_vault = await vault_service.delete_from_vault(vault_unique_id)
        if not deleted_in_vault:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete token details from vault.",
            )

        # Delete gg_vault row
        await db.delete(vault_record)
        await db.commit()

        return SuccessResponse(
            success=True,
            data=DeleteTokenDetailsResponse(
                deleted=True,
                vault_unique_id=vault_unique_id,
                giggso_vault_id=str(vault_record.giggso_vault_id),
            ),
            message="Token details deleted successfully.",
            code=status.HTTP_200_OK,
        )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete token details: {str(e)}",
        )
