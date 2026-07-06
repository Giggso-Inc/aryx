"""
LLM Validation Service

This service provides utilities for validating API tokens for various LLM providers:
- Azure OpenAI
- OpenAI (ChatGPT)
- Gemini
"""

import logging
from typing import Optional

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


def updateAzureOpenAiChat(
    prompt: str,
    openaiToken: str,
    deploymentName: str,
    endpoint: str,
    apiVersion: str
) -> str:
    """
    Validate Azure OpenAI API by making a test request
    
    Args:
        prompt: Test prompt to send
        openaiToken: Azure OpenAI API key
        deploymentName: Azure deployment name
        endpoint: Azure endpoint URL
        apiVersion: API version
        
    Returns:
        Response text from the API
        
    Raises:
        Exception: If validation fails
    """
    if not OPENAI_AVAILABLE:
        raise ImportError("openai package is required. Install it with: pip install openai")
    
    # Initialize Azure OpenAI client
    client = AzureOpenAI(
        api_key=openaiToken,
        api_version=apiVersion,
        azure_endpoint=endpoint
    )
    
    # Make a test request
    response = client.chat.completions.create(
        model=deploymentName,
        messages=[
            {"role": "user", "content": prompt}
        ],
        max_tokens=10  # Minimal tokens for validation
    )
    
    return response.choices[0].message.content


def updateOpenAiChat(
    prompt: str,
    apiKey: str,
    model: str
) -> str:
    """
    Validate OpenAI API by making a test request
    
    Args:
        prompt: Test prompt to send
        apiKey: OpenAI API key
        model: Model name (e.g., "gpt-3.5-turbo", "gpt-4")
        
    Returns:
        Response text from the API
        
    Raises:
        RateLimitError: If quota is exceeded
        Exception: If validation fails
    """
    if not OPENAI_AVAILABLE:
        raise ImportError("openai package is required. Install it with: pip install openai")
    
    # Initialize OpenAI client
    client = OpenAI(api_key=apiKey)
    
    # Make a test request
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": prompt}
        ],
        max_tokens=10  # Minimal tokens for validation
    )
    
    return response.choices[0].message.content


def validate_gemini(
    apiKey: str,
    model: str,
    prompt: str = "This is a test prompt."
) -> str:
    """
    Validate Gemini API by making a test request
    
    Args:
        apiKey: Gemini API key
        model: Model name (e.g., "gemini-pro", "gemini-1.5-pro")
        prompt: Test prompt to send
        
    Returns:
        Response text from the API
        
    Raises:
        InvalidArgument: If API key or model is invalid
        Forbidden: If API key doesn't have access
        ServiceUnavailable: If service is temporarily unavailable
        InternalServerError: If internal error occurred
        Exception: If validation fails
    """
    if not GEMINI_AVAILABLE:
        raise ImportError("google-generativeai package is required. Install it with: pip install google-generativeai")
    
    # Configure Gemini API
    genai.configure(api_key=apiKey)
    
    # Get model instance
    model_instance = genai.GenerativeModel(model)
    
    # Make a test request
    response = model_instance.generate_content(prompt)
    
    # Handle response - check if text exists
    if hasattr(response, 'text') and response.text:
        return response.text
    elif hasattr(response, 'candidates') and response.candidates:
        # Try to get text from candidates
        if response.candidates[0].content and response.candidates[0].content.parts:
            return response.candidates[0].content.parts[0].text
    else:
        # Return a success indicator even if no text
        return "Validation successful"
