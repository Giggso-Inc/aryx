"""
OpenAI / ChatGPT branch of POST /llmValidation/gpt-token-validation.

Extracted out of validation.py (Raven style-compliance pass, wave B, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). `_validate_chatgpt` is
called only from `llm_validation`'s dispatcher in validation.py; it is not
an independent endpoint.
"""

from __future__ import annotations

import logging

from fastapi import status

from app.schemas.common import SuccessResponse


def _validate_chatgpt(
    logger: logging.Logger,
    api_key: str,
    model: str | None,
    cb,
    langchain_available: bool,
) -> SuccessResponse[dict]:
    """Validate an OpenAI (ChatGPT) API token; mirrors the original inline branch."""
    from app.services.llm_validation_service import (
        update_openai_chat,
        RateLimitError,
        get_openai_callback,
    )

    cost = 0.0

    try:
        logger.info(f"## Request received for OpenAI Model: {model}")

        user_prompt = "This is a test"
        response = update_openai_chat(user_prompt, api_key, model)

        # Get cost from callback if available
        if langchain_available and get_openai_callback and hasattr(cb, 'total_cost'):
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
