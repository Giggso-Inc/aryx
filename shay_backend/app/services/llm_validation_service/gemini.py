"""Gemini token validation."""

from .availability import GEMINI_AVAILABLE, genai


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
