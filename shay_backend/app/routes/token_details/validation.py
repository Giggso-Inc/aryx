"""
POST /llmValidation/gpt-token-validation — llm_validation.

Split out of the original app/routes/token_details.py (767 lines) as part of
the Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).

Stated exception: this file is ~355 lines, above the ~150-line target. The
single endpoint is one cohesive request flow — decode the token, then branch
on llmType (azureopenai / chatgpt / gemini / unsupported) with each branch's
own try/except mapping provider-specific exceptions to a response shape.
Splitting the branches into separate files would fragment a single
endpoint's error-handling contract across modules and force each branch
module to duplicate the shared `cost`/`cb_context`/logger setup, without
making any branch independently reusable or testable — none of the
per-provider blocks are called from anywhere else. Kept as one file.
"""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.common import LLMValidatorRequest, SuccessResponse

router = APIRouter()


@router.post("/llmValidation/gpt-token-validation", response_model=SuccessResponse[dict], tags=["LLM Validator"])
async def llm_validation(
    request: Request,
    request_data: LLMValidatorRequest,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[dict]:
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
