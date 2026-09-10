"""
POST /fetchTokenDetails — fetch_token_details.

Split out of the original app/routes/token_details.py (767 lines) as part of
the Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
"""

from __future__ import annotations

import uuid
import base64

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.giggso_vault import GiggsoVault
from app.schemas.common import (
    FetchTokenDetailsRequest,
    FetchTokenDetailsResponse,
    SuccessResponse,
)
from app.services.vault_service import vault_service

from .helpers import _vault_dict_to_response_shape

router = APIRouter()


@router.post("/fetchTokenDetails", response_model=SuccessResponse[FetchTokenDetailsResponse])
async def fetch_token_details(
    request: Request,
    payload: FetchTokenDetailsRequest,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[FetchTokenDetailsResponse]:
    """
    Fetch token/API details for a company from vault (authenticated).

    Flow:
    - Require JWT (non-public).
    - Find gg_vault record by companyId and vault_type='gpt_token' to get vault_unique_id.
    - Retrieve stored details from vault and return them.
    """
    # Enforce authentication and get the current user (authorization decisions below use this)
    user = await get_current_user_required(request, db)

    try:
        # Parse companyId and prevent cross-company reads by non-admin users
        try:
            company_uuid = uuid.UUID(payload.companyId)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid companyId format (must be a valid UUID)",
            )

        # Basic authorization: only allow reads within the caller's company unless caller is admin
        if str(user.company_id) != str(company_uuid) and getattr(user, "role", "").lower() != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not allowed to fetch token details for another company.",
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

        # Retrieve the full payload from external vault
        token_details = await vault_service.retrieve_from_vault(vault_unique_id)
        if not token_details:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token details not found in vault for the stored vault_unique_id.",
            )

        # Decode api_key from base64 for response (fallback to original value if decode fails)
        if isinstance(token_details, dict) and "openaiToken" in token_details and token_details.get("openaiToken") is not None:
            try:
                token_details["openaiToken"] = base64.b64decode(str(token_details["openaiToken"])).decode("utf-8")
            except Exception:
                # Keep openaiToken as-is (supports legacy/plaintext or unexpected formats)
                pass
        # Backward compatibility: legacy vault entries may still store the token under "api_key"
        elif isinstance(token_details, dict) and "api_key" in token_details and token_details.get("api_key") is not None:
            legacy_val = token_details["api_key"]
            try:
                token_details["openaiToken"] = base64.b64decode(str(legacy_val)).decode("utf-8")
            except Exception:
                token_details["openaiToken"] = legacy_val

        # Return legacy response shape (api_key, token_type, embedding_model, gpt_model, deploymentVersion, etc.)
        token_details = _vault_dict_to_response_shape(token_details)

        return SuccessResponse(
            success=True,
            data=FetchTokenDetailsResponse(
                vault_unique_id=vault_unique_id,
                giggso_vault_id=str(vault_record.giggso_vault_id),
                token_details=token_details,
            ),
            message="Token details fetched successfully.",
            code=status.HTTP_200_OK,
        )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch token details: {str(e)}",
        )
