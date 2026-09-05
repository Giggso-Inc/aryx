"""
POST /updateTokenDetails — update_token_details.

Split out of the original app/routes/token_details.py (767 lines) as part of
the Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).

Stated exception (wave B, 150-line hard rule): this file is 151 lines, 1
over. The single endpoint is one linear, cohesive transaction (parse
companyId -> authorize -> validate Azure-specific fields -> fetch the
existing gg_vault record -> build the vault payload -> save -> touch audit
fields -> return), threading `company_uuid`/`user`/`vault_record` through
every step. There is no seam that isn't purely cosmetic; fragmenting a
single-transaction endpoint into two files to shave one line would add an
import/call indirection with no independent reuse or testability gain.
Kept as one file, matching this plan's established near-miss precedent
(e.g. `data_table_product.py` at 151 lines).
"""

from __future__ import annotations

import uuid
import base64
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.giggso_vault import GiggsoVault
from app.schemas.common import (
    SaveTokenDetailsRequest,
    SaveTokenDetailsResponse,
    SuccessResponse,
)
from app.services.vault_service import vault_service

from .helpers import _normalize_token_type_for_vault

router = APIRouter()


@router.post("/updateTokenDetails", response_model=SuccessResponse[SaveTokenDetailsResponse])
async def update_token_details(
    request: Request,
    payload: SaveTokenDetailsRequest,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[SaveTokenDetailsResponse]:
    """
    Update token/API details for a company (authenticated).

    Flow:
    - Require JWT (non-public).
    - Find the existing gg_vault record by companyId and vault_type='gpt_token'.
    - Reuse its vault_unique_id and overwrite the vault payload with the new one.
    """
    # Enforce authentication and get the current user (authorization decisions below use this)
    user = await get_current_user_required(request, db)

    try:
        # Parse companyId and prevent cross-company updates by non-admin users
        try:
            company_uuid = uuid.UUID(payload.companyId)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid companyId format (must be a valid UUID)",
            )

        # Basic authorization: only allow updates within the caller's company unless caller is admin
        if str(user.company_id) != str(company_uuid) and getattr(user, "role", "").lower() != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not allowed to update token details for another company.",
            )

        # Azure: when token_type is azure or azureopenai, require deploymentName, deploymentVersion, endpoint
        _normalized = _normalize_token_type_for_vault(payload.token_type or "")
        if _normalized and _normalized.lower() == "azure":
            missing = []
            if not (payload.deploymentName or "").strip():
                missing.append("deploymentName")
            if not (payload.deploymentVersion or "").strip():
                missing.append("deploymentVersion")
            if not (payload.endpoint or "").strip():
                missing.append("endpoint")
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"When token_type is azure, the following are required: {', '.join(missing)}",
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
                detail="No existing token details found for this company (vault_type='gpt_token').",
            )

        vault_unique_id = vault_record.vault_unique_id

        # Build vault payload in ML shape: tokenType, model, apiVersion, embeddingsDeploymentName, openaiToken, etc.
        vault_data = {
            "tokenType": _normalize_token_type_for_vault(payload.token_type or ""),
            "tokenName": payload.tokenName,
            "openaiToken": base64.b64encode(payload.api_key.encode("utf-8")).decode("utf-8"),
            "embeddingsDeploymentName": payload.embedding_model,
            "model": payload.gpt_model or "",
            "apiVersion": payload.deploymentVersion if payload.deploymentVersion is not None else "",
            "companyId": payload.companyId,
        }
        if payload.deploymentName is not None:
            vault_data["deploymentName"] = payload.deploymentName
        if payload.endpoint is not None:
            vault_data["endpoint"] = payload.endpoint

        # Overwrite the existing vault entry using the same vault_unique_id
        saved_vault_id = await vault_service.save_to_vault(vault_data, vault_unique_id)
        if not saved_vault_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update token details in vault.",
            )

        # Touch gg_vault record for audit (do not change vault_type; keep user_id as-is)
        vault_record.updated_datetime = datetime.utcnow()
        vault_record.updated_by = user.id

        await db.commit()
        await db.refresh(vault_record)

        return SuccessResponse(
            success=True,
            data=SaveTokenDetailsResponse(
                vault_unique_id=vault_unique_id,
                giggso_vault_id=str(vault_record.giggso_vault_id),
            ),
            message="Token details updated successfully.",
            code=status.HTTP_200_OK,
        )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update token details: {str(e)}",
        )
