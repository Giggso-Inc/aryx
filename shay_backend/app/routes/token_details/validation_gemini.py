"""
Gemini branch of POST /llmValidation/gpt-token-validation.

Extracted out of validation.py (Raven style-compliance pass, wave B, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). `_validate_gemini_token` is
called only from `llm_validation`'s dispatcher in validation.py; it is not
an independent endpoint.
"""

from __future__ import annotations

import logging

from fastapi import status

from app.schemas.common import SuccessResponse


def _validate_gemini_token(
    logger: logging.Logger,
    apiKey: str,
    model: str | None,
) -> SuccessResponse[dict]:
    """Validate a Gemini API token; mirrors the original inline branch."""
    from app.services.llm_validation_service import (
        validate_gemini,
        InvalidArgument,
        Forbidden,
        ServiceUnavailable,
        InternalServerError,
    )

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
