"""
POST /llmValidation/gpt-token-validation — llm_validation.

Split out of the original app/routes/token_details.py (767 lines) as part of
the Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2), then
further split in wave B (150-line hard rule): each provider branch
(azureopenai / chatgpt / gemini) is now its own module
(validation_azure.py / validation_chatgpt.py / validation_gemini.py),
called from this file's dispatcher. This is safe against the whitebox test
patches in tests/test_token_details_characterization.py because those
patches all target `app.services.llm_validation_service.*` (the functions
themselves), not any `app.routes.token_details.validation*` path — every
branch imports its provider functions locally from that service module at
call time, unchanged by which file the branch code lives in.
"""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.common import LLMValidatorRequest, SuccessResponse
from app.routes.token_details.validation_azure import _validate_azure_openai
from app.routes.token_details.validation_chatgpt import _validate_chatgpt
from app.routes.token_details.validation_gemini import _validate_gemini_token

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
        get_openai_callback,
        LANGCHAIN_AVAILABLE
    )

    cost = 0.0
    llm_type = request_data.llmType.lower()  # Normalize to lowercase

    try:
        # Decode base64 API key
        api_key = base64.b64decode(request_data.llmApiKey).decode('UTF-8').strip()
        deployment_name = request_data.llmModelName
        api_version = request_data.llmApiVersion
        endpoint = request_data.llmEndpoint
        model = request_data.llmModelName

        logger.info("## Request received in validator API...")
        logger.info(f"Token is received in payload Type: {llm_type}")

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
        if llm_type == "azureopenai":
            return _validate_azure_openai(
                logger, deployment_name, endpoint, api_version, api_key, cb, LANGCHAIN_AVAILABLE
            )

        elif llm_type == "chatgpt":
            return _validate_chatgpt(logger, api_key, model, cb, LANGCHAIN_AVAILABLE)

        elif llm_type == "gemini":
            return _validate_gemini_token(logger, api_key, model)

        # -------------------- Unsupported Provider --------------------
        else:
            logger.error(f"Unsupported llmType received: {llm_type}")
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
