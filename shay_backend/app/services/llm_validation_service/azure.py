"""Azure OpenAI token validation."""

from .availability import OPENAI_AVAILABLE, AzureOpenAI


def update_azure_openai_chat(
    prompt: str,
    openai_token: str,
    deployment_name: str,
    endpoint: str,
    api_version: str
) -> str:
    """
    Validate Azure OpenAI API by making a test request

    Args:
        prompt: Test prompt to send
        openai_token: Azure OpenAI API key
        deployment_name: Azure deployment name
        endpoint: Azure endpoint URL
        api_version: API version

    Returns:
        Response text from the API

    Raises:
        Exception: If validation fails
    """
    if not OPENAI_AVAILABLE:
        raise ImportError("openai package is required. Install it with: pip install openai")

    # Initialize Azure OpenAI client
    client = AzureOpenAI(
        api_key=openai_token,
        api_version=api_version,
        azure_endpoint=endpoint
    )

    # Make a test request
    response = client.chat.completions.create(
        model=deployment_name,
        messages=[
            {"role": "user", "content": prompt}
        ],
        max_tokens=10  # Minimal tokens for validation
    )

    return response.choices[0].message.content
