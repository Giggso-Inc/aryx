"""OpenAI (ChatGPT) token validation."""

from .availability import OPENAI_AVAILABLE, OpenAI


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
