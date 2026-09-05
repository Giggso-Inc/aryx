"""
LLM Validation Service

This service provides utilities for validating API tokens for various LLM providers:
- Azure OpenAI
- OpenAI (ChatGPT)
- Gemini

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): this used to be a single
180-line app/services/llm_validation_service.py. It is now a package split
one provider per module, with every name any caller imported (including the
local `from app.services.llm_validation_service import (...)` inside
app/routes/token_details/validation.py) re-exported here so no call site
needs to change.

  availability.py - optional-dependency detection (OPENAI_AVAILABLE,
                    GEMINI_AVAILABLE, LANGCHAIN_AVAILABLE) + the SDK
                    symbols/exception classes each provider module imports
  azure.py        - updateAzureOpenAiChat
  openai_chat.py  - updateOpenAiChat
  gemini.py       - validate_gemini
"""

from .availability import (
    OPENAI_AVAILABLE,
    OpenAI,
    AzureOpenAI,
    RateLimitError,
    GEMINI_AVAILABLE,
    genai,
    InvalidArgument,
    Forbidden,
    ServiceUnavailable,
    InternalServerError,
    LANGCHAIN_AVAILABLE,
    get_openai_callback,
    logger,
)
from .azure import updateAzureOpenAiChat
from .openai_chat import updateOpenAiChat
from .gemini import validate_gemini

__all__ = [
    "OPENAI_AVAILABLE",
    "OpenAI",
    "AzureOpenAI",
    "RateLimitError",
    "GEMINI_AVAILABLE",
    "genai",
    "InvalidArgument",
    "Forbidden",
    "ServiceUnavailable",
    "InternalServerError",
    "LANGCHAIN_AVAILABLE",
    "get_openai_callback",
    "logger",
    "updateAzureOpenAiChat",
    "updateOpenAiChat",
    "validate_gemini",
]
