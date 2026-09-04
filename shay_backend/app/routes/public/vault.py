"""Public vault token storage: POST /saveTokenDetails."""

import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.giggso_vault import GiggsoVault
from app.schemas.common import SuccessResponse, SaveTokenDetailsRequest, SaveTokenDetailsResponse
from app.services.vault_service import vault_service
from app.routes.token_details import _normalize_token_type_for_vault  # ML vault shape normalization

router = APIRouter()


@router.post("/saveTokenDetails", response_model=SuccessResponse[SaveTokenDetailsResponse])
async def save_token_details(
    payload: SaveTokenDetailsRequest,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[SaveTokenDetailsResponse]:
    """
    Public endpoint to save token/API details to vault and gg_vault (no JWT required).
    Accepts token_type, api_key, embedding_model, gpt_model, companyId. When token_type
    is azure, deploymentName, deploymentVersion and endpoint are required and stored in
    vault. Creates gg_vault with company_id, vault_type='gpt_token', user_id=null.
    """
    try:
        # Parse company_id as UUID for gg_vault and vault key generation
        try:
            company_uuid = uuid.UUID(payload.companyId)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid companyId format (must be a valid UUID)"
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
                    detail=f"When token_type is azure, the following are required: {', '.join(missing)}"
                )
        # Build vault payload in ML shape: tokenType, model, apiVersion, embeddingsDeploymentName, openaiToken
        vault_data = {
            "tokenType": _normalize_token_type_for_vault(payload.token_type or ""),
            "tokenName": payload.tokenName,
            "openaiToken": payload.api_key,
            "embeddingsDeploymentName": payload.embedding_model or "",
            "model": payload.gpt_model or "",
            "apiVersion": payload.deploymentVersion if payload.deploymentVersion is not None else "",
            "companyId": payload.companyId,
        }
        if payload.deploymentName is not None:
            vault_data["deploymentName"] = payload.deploymentName
        if payload.endpoint is not None:
            vault_data["endpoint"] = payload.endpoint
        # Generate vault unique ID using company_id as prefix (no user_id in public flow)
        vault_unique_id = vault_service.generate_vault_unique_id(
            str(company_uuid), app_key=payload.token_type or "token"
        )
        # Save to external vault
        saved_vault_id = await vault_service.save_to_vault(vault_data, vault_unique_id)
        if not saved_vault_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save token details to vault."
            )
        # Create gg_vault record: company_id, vault_unique_id, vault_type='gpt_token', user_id=null
        base_label = f"tk_{vault_unique_id.replace('/', '_')[:20]}"
        vault_label = (base_label + "_ok")[:50]
        vault_record = GiggsoVault(
            vault_unique_id=vault_unique_id,
            user_id=None,
            vault_label=vault_label,
            vault_type="gpt_token",
            company_id=company_uuid,
            created_datetime=datetime.utcnow(),
        )
        db.add(vault_record)
        await db.flush()
        await db.commit()
        await db.refresh(vault_record)
        # Return vault identifiers in standard success wrapper
        return SuccessResponse(
            success=True,
            data=SaveTokenDetailsResponse(
                vault_unique_id=vault_unique_id,
                giggso_vault_id=str(vault_record.giggso_vault_id),
            ),
            message="Token details saved to vault successfully.",
            code=status.HTTP_200_OK,
        )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save token details: {str(e)}"
        )
