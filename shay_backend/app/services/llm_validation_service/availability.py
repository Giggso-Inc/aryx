"""Optional-dependency detection for the LLM validation providers.

Each provider SDK is optional at the process level (the app may run without
any of them installed); every symbol here is re-exported by the package
`__init__.py` so existing `from app.services.llm_validation_service import X`
call sites (including local imports inside route handlers) keep working.
"""

import logging

# Try to import OpenAI
try:
    from openai import OpenAI, AzureOpenAI
    from openai import RateLimitError
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    OpenAI = None
    AzureOpenAI = None
    RateLimitError = None

# Try to import Google Generative AI (Gemini)
try:
    import google.generativeai as genai
    from google.api_core.exceptions import (
        InvalidArgument,
        Forbidden,
        ServiceUnavailable,
        InternalServerError
    )
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    genai = None
    InvalidArgument = None
    Forbidden = None
    ServiceUnavailable = None
    InternalServerError = None

# Try to import LangChain callbacks for cost tracking
try:
    from langchain.callbacks import get_openai_callback
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    get_openai_callback = None

logger = logging.getLogger(__name__)
