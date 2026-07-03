"""
Token details routes (non-public).

This module provides authenticated endpoints to update token details stored in the
external vault and referenced by the gg_vault table.
"""

from datetime import datetime  # For audit timestamps
import uuid  # For UUID parsing/validation
import base64  # For base64 encoding/decoding api_key in vault payload
import logging  # For logging

from fastapi import APIRouter, Depends, HTTPException, Request, status  # FastAPI primitives
from sqlalchemy import select  # SQLAlchemy query builder
from sqlalchemy.ext.asyncio import AsyncSession  # Async DB session

from app.core.database import get_db  # DB dependency
from app.middleware.auth_middleware import get_current_user_required  # Auth requirement
from app.models.giggso_vault import GiggsoVault  # gg_vault model
from app.schemas.common import (  # Standard API wrappers + payload schema
    DeleteTokenDetailsRequest,
    DeleteTokenDetailsResponse,
    FetchTokenDetailsRequest,
    FetchTokenDetailsResponse,
    SaveTokenDetailsRequest,
    SaveTokenDetailsResponse,
    SuccessResponse,
    LLMValidatorRequest,
)
from app.services.vault_service import vault_service  # External vault integration


router = APIRouter()


def _normalize_token_type_for_vault(token_type: str) -> str:
    """
    Normalize token_type for vault/ML: azureopenai -> azure; others (openai, chatgpt, gemini) unchanged.
    ML expects tokenType: azure | openai | chatgpt | gemini.
    """
    if not token_type:
        return token_type or ""
    t = (token_type or "").strip().lower()
    if t == "azureopenai":
        return "azure"
    return token_type.strip()


def _vault_dict_to_ml_shape(data: dict) -> dict:
    """
    Map vault keys to ML-expected keys. Handles both new (ML) and legacy vault shapes.
    ML expects: openaiToken, tokenType, model, apiVersion, endpoint, deploymentName, embeddingsDeploymentName.
    """
    if not isinstance(data, dict):
        return data
    out = dict(data)
    # tokenType: from token_type or tokenType, normalized (azureopenai -> azure)
    raw_token_type = out.get("token_type") or out.get("tokenType") or ""
    out["tokenType"] = _normalize_token_type_for_vault(raw_token_type)
    out.pop("token_type", None)
    # model: from gpt_model or model
    if "gpt_model" in out and "model" not in out:
        out["model"] = out.pop("gpt_model", "")
    # apiVersion: from deploymentVersion or apiVersion
    if "deploymentVersion" in out and "apiVersion" not in out:
        out["apiVersion"] = out.pop("deploymentVersion", "")
    # embeddingsDeploymentName: from embedding_model or embeddingsDeploymentName
    if "embedding_model" in out and "embeddingsDeploymentName" not in out:
        out["embeddingsDeploymentName"] = out.pop("embedding_model", "")
    # Remove legacy api_key if openaiToken is present (avoid duplicate)
    if "openaiToken" in out:
        out.pop("api_key", None)
    return out


def _vault_dict_to_response_shape(data: dict) -> dict:
    """
    Convert vault data (ML or legacy keys) to legacy fetch response shape for backward compatibility.
    Response uses: api_key, token_type, embedding_model, gpt_model, deploymentVersion, deploymentName,
    endpoint, companyId, tokenName (if present).
    """
    if not isinstance(data, dict):
        return data
    out = {}
    # api_key: decoded value from openaiToken or legacy api_key (caller already decoded openaiToken in place)
    out["api_key"] = data.get("openaiToken") or data.get("api_key") or ""
    # token_type: from tokenType or token_type; for response use "azureopenai" when vault has "azure"
    raw = (data.get("tokenType") or data.get("token_type") or "").strip().lower()
    out["token_type"] = "azureopenai" if raw == "azure" else (data.get("tokenType") or data.get("token_type") or "")
    # embedding_model: from embeddingsDeploymentName or embedding_model
    out["embedding_model"] = data.get("embeddingsDeploymentName") or data.get("embedding_model") or ""
    # gpt_model: from model or gpt_model
    out["gpt_model"] = data.get("model") or data.get("gpt_model") or ""
    # deploymentVersion: from apiVersion or deploymentVersion
    out["deploymentVersion"] = data.get("apiVersion") or data.get("deploymentVersion") or ""
    # Pass-through keys (unchanged)
    for key in ("companyId", "deploymentName", "endpoint", "tokenName"):
        if key in data and data[key] is not None:
            out[key] = data[key]
    return out


@router.post("/updateTokenDetails", response_model=SuccessResponse[SaveTokenDetailsResponse])
async def update_token_details(
    request: Request,
    payload: SaveTokenDetailsRequest,
    db: AsyncSession = Depends(get_db),
):
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


@router.post("/fetchTokenDetails", response_model=SuccessResponse[FetchTokenDetailsResponse])
async def fetch_token_details(
    request: Request,
    payload: FetchTokenDetailsRequest,
    db: AsyncSession = Depends(get_db),
):
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


@router.delete("/deleteTokenDetails", response_model=SuccessResponse[DeleteTokenDetailsResponse])
async def delete_token_details(
    request: Request,
    payload: DeleteTokenDetailsRequest,
    db: AsyncSession = Depends(get_db),
):
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


@router.post("/llmValidation/gpt-token-validation", response_model=SuccessResponse[dict], tags=["LLM Validator"])
async def llm_validation(
    request: Request,
    request_data: LLMValidatorRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Validate LLM API tokens (OpenAI, Azure OpenAI, Gemini)
    
    This API validates the provided API token by making a test request to the LLM service.
    Supports validation for:
    - Azure OpenAI
    - OpenAI (ChatGPT)
    - Gemini
    """
    logger = logging.getLogger(__name__)
    
    # Import validation functions and exceptions
    from app.services.llm_validation_service import (
        updateAzureOpenAiChat,
        updateOpenAiChat,
        validate_gemini,
        RateLimitError,
        InvalidArgument,
        Forbidden,
        ServiceUnavailable,
        InternalServerError,
        get_openai_callback,
        LANGCHAIN_AVAILABLE
    )
    
    cost = 0.0
    llmType = request_data.llmType.lower()  # Normalize to lowercase
    
    try:
        # Decode base64 API key
        apiKey = base64.b64decode(request_data.llmApiKey).decode('UTF-8').strip()
        deploymentName = request_data.llmModelName
        apiVersion = request_data.llmApiVersion
        endpoint = request_data.llmEndpoint
        model = request_data.llmModelName
        
        logger.info("## Request received in validator API...")
        logger.info(f"Token is received in payload Type: {llmType}")
        
    except Exception as exp:
        logger.exception(
            f"The request contains one or more invalid parameters. Issue: {exp}"
        )
        return SuccessResponse(
            success=False,
            data={
                "status": "failed",
                "type": "payload_issue",
                "cost": cost,
                "message": "The request contains one or more invalid parameters. Please review your request and ensure all parameters are correctly formatted and valid."
            },
            message="Validation failed due to invalid parameters",
            code=status.HTTP_400_BAD_REQUEST
        )
    
    # Use LangChain callback for cost tracking if available
    # Note: get_openai_callback() is a context manager, so we need to handle it properly
    if LANGCHAIN_AVAILABLE and get_openai_callback:
        # Use the callback context manager
        cb_context = get_openai_callback()
    else:
        # Create a dummy context manager if LangChain is not available
        from contextlib import nullcontext
        cb_context = nullcontext()
    
    with cb_context as cb:
        # -------------------- Azure OpenAI --------------------
        if llmType == "azureopenai":
            try:
                logger.info("## Request received for the AzureOpenAI API...")
                logger.info(
                    f"Deployment Name: {deploymentName}\nEndpoint: {endpoint}\nAPI Version: {apiVersion}"
                )
                
                # Validate required fields for Azure
                if not apiVersion or not endpoint:
                    return SuccessResponse(
                        success=False,
                        data={
                            "status": "failed",
                            "type": "payload_issue",
                            "cost": cost,
                            "message": "API version and endpoint are required for Azure OpenAI"
                        },
                        message="Validation failed",
                        code=status.HTTP_400_BAD_REQUEST
                    )
                
                response = updateAzureOpenAiChat(
                    prompt="This is a test",
                    openaiToken=apiKey,
                    deploymentName=deploymentName,
                    endpoint=endpoint,
                    apiVersion=apiVersion
                )
                
                logger.info(f"Response: {response}")
                
                # Get cost from callback if available
                if LANGCHAIN_AVAILABLE and get_openai_callback and hasattr(cb, 'total_cost'):
                    cost = cb.total_cost
                
                return SuccessResponse(
                    success=True,
                    data={
                        "status": "success",
                        "type": "text",
                        "cost": cost,
                        "message": "Great news! Your API token for Azure OpenAI is valid and ready to power your Model."
                    },
                    message="Validation successful",
                    code=status.HTTP_200_OK
                )
                
            except Exception as exp:
                error_msg = str(exp)
                
                if "Resource not found" in error_msg:
                    return SuccessResponse(
                        success=False,
                        data={
                            "status": "failed",
                            "type": "resource_issue",
                            "cost": cost,
                            "message": "The provided API version or endpoint appears to be invalid."
                        },
                        message="Validation failed",
                        code=status.HTTP_400_BAD_REQUEST
                    )
                
                elif "invalid subscription key" in error_msg.lower():
                    return SuccessResponse(
                        success=False,
                        data={
                            "status": "failed",
                            "type": "invalid_key",
                            "cost": cost,
                            "message": "The provided Token (API Key) appears to be invalid."
                        },
                        message="Validation failed",
                        code=status.HTTP_401_UNAUTHORIZED
                    )
                
                elif "The API deployment for this resource does not exist." in error_msg:
                    return SuccessResponse(
                        success=False,
                        data={
                            "status": "failed",
                            "type": "deployment_issue",
                            "cost": cost,
                            "message": "The API deployment for this resource does not exist."
                        },
                        message="Validation failed",
                        code=status.HTTP_404_NOT_FOUND
                    )
                
                else:
                    logger.exception("Azure OpenAI validation failed.")
                    return SuccessResponse(
                        success=False,
                        data={
                            "status": "failed",
                            "type": "text",
                            "cost": cost,
                            "message": "Uh-oh! There is an issue validating your Azure OpenAI API token."
                        },
                        message="Validation failed",
                        code=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
        
        # -------------------- OpenAI / ChatGPT --------------------
        elif llmType == "chatgpt":
            try:
                logger.info(f"## Request received for OpenAI Model: {model}")
                
                userPrompt = "This is a test"
                response = updateOpenAiChat(userPrompt, apiKey, model)
                
                # Get cost from callback if available
                if LANGCHAIN_AVAILABLE and get_openai_callback and hasattr(cb, 'total_cost'):
                    cost = cb.total_cost
                
                return SuccessResponse(
                    success=True,
                    data={
                        "status": "success",
                        "type": "text",
                        "cost": cost,
                        "message": "Great news! Your API token for OpenAI is valid and ready to power your Model."
                    },
                    message="Validation successful",
                    code=status.HTTP_200_OK
                )
                
            except RateLimitError as exp:
                logger.exception(f"Quota exceeded. Issue: {exp}")
                return SuccessResponse(
                    success=False,
                    data={
                        "status": "failed",
                        "type": "quota_issue",
                        "cost": cost,
                        "message": "Insufficient quota for the provided token. Please upgrade your plan."
                    },
                    message="Validation failed",
                    code=status.HTTP_429_TOO_MANY_REQUESTS
                )
                
            except Exception as exp:
                logger.exception(f"OpenAI validation failed. Issue: {exp}")
                return SuccessResponse(
                    success=False,
                    data={
                        "status": "failed",
                        "type": "text",
                        "cost": cost,
                        "message": "Uh-oh! There is an issue validating your OpenAI API token."
                    },
                    message="Validation failed",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        
        # -------------------- Gemini --------------------
        elif llmType == "gemini":
            try:
                logger.info("## Request received for the Gemini API...")
                
                response = validate_gemini(apiKey, model, "This is a test prompt.")
                logger.info(f"Response: {response}")
                
                return SuccessResponse(
                    success=True,
                    data={
                        "status": "success",
                        "type": "text",
                        "cost": 0.0,
                        "message": "Great news! Your API token for Gemini is valid and ready to power your Model."
                    },
                    message="Validation successful",
                    code=status.HTTP_200_OK
                )
                
            except InvalidArgument as exp:
                return SuccessResponse(
                    success=False,
                    data={
                        "status": "failed",
                        "type": "invalid_key",
                        "cost": 0.0,
                        "message": "The provided API key or model name is invalid."
                    },
                    message="Validation failed",
                    code=status.HTTP_400_BAD_REQUEST
                )
                
            except Forbidden:
                return SuccessResponse(
                    success=False,
                    data={
                        "status": "failed",
                        "type": "permission_denied",
                        "cost": 0.0,
                        "message": "The API key does not have access to the requested model."
                    },
                    message="Validation failed",
                    code=status.HTTP_403_FORBIDDEN
                )
                
            except ServiceUnavailable:
                return SuccessResponse(
                    success=False,
                    data={
                        "status": "failed",
                        "type": "service_unavailable",
                        "cost": 0.0,
                        "message": "The Gemini service is temporarily unavailable. Please try again later."
                    },
                    message="Validation failed",
                    code=status.HTTP_503_SERVICE_UNAVAILABLE
                )
                
            except InternalServerError:
                return SuccessResponse(
                    success=False,
                    data={
                        "status": "failed",
                        "type": "internal_error",
                        "cost": 0.0,
                        "message": "An internal error occurred on the Gemini service."
                    },
                    message="Validation failed",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
            except Exception as exp:
                error_msg = str(exp)
                logger.exception(f"Gemini validation failed. Issue: {exp}")
                
                # Check for common error patterns
                if "API key" in error_msg or "invalid" in error_msg.lower():
                    return SuccessResponse(
                        success=False,
                        data={
                            "status": "failed",
                            "type": "invalid_key",
                            "cost": 0.0,
                            "message": f"The provided API key or model name is invalid. Error: {error_msg}"
                        },
                        message="Validation failed",
                        code=status.HTTP_400_BAD_REQUEST
                    )
                elif "model" in error_msg.lower() or "not found" in error_msg.lower():
                    return SuccessResponse(
                        success=False,
                        data={
                            "status": "failed",
                            "type": "invalid_key",
                            "cost": 0.0,
                            "message": f"Model '{model}' not found or invalid. Please check the model name. Error: {error_msg}"
                        },
                        message="Validation failed",
                        code=status.HTTP_400_BAD_REQUEST
                    )
                else:
                    return SuccessResponse(
                        success=False,
                        data={
                            "status": "failed",
                            "type": "text",
                            "cost": 0.0,
                            "message": f"Uh-oh! There is an issue validating your Gemini API token. Error: {error_msg}"
                        },
                        message="Validation failed",
                        code=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
        
        # -------------------- Unsupported Provider --------------------
        else:
            logger.error(f"Unsupported llmType received: {llmType}")
            return SuccessResponse(
                success=False,
                data={
                    "status": "failed",
                    "type": "unsupported_provider",
                    "cost": cost,
                    "message": "No support available for the provided API token. Supported types: chatgpt, azureopenai, gemini."
                },
                message="Validation failed",
                code=status.HTTP_400_BAD_REQUEST
            )
