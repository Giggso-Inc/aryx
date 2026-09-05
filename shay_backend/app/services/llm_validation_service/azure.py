"""Azure OpenAI token validation."""

from .availability import OPENAI_AVAILABLE, AzureOpenAI


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
