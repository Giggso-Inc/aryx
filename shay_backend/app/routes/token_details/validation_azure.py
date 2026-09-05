"""
Azure OpenAI branch of POST /llmValidation/gpt-token-validation.

Extracted out of validation.py (Raven style-compliance pass, wave B, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). `_validate_azure_openai` is
called only from `llm_validation`'s dispatcher in validation.py; it is not
an independent endpoint.
"""

from __future__ import annotations

import logging

from fastapi import status

from app.schemas.common import SuccessResponse


def _validate_azure_openai(
    logger: logging.Logger,
    deploymentName: str | None,
    endpoint: str | None,
    apiVersion: str | None,
    apiKey: str,
    cb,
    langchain_available: bool,
) -> SuccessResponse[dict]:
    """Validate an Azure OpenAI API token; mirrors the original inline branch."""
    from app.services.llm_validation_service import updateAzureOpenAiChat, get_openai_callback

    cost = 0.0

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
        if langchain_available and get_openai_callback and hasattr(cb, 'total_cost'):
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
