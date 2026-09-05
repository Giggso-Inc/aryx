"""
Internal API-key verification for bulk_create_internal.py (POST /internal/bulk).
"""

from fastapi import HTTPException, Request, status

from app.core.config import settings


def verify_internal_api_key(request: Request) -> None:
    """Verify internal API key from request headers"""
    api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is required. Provide X-API-Key header or Bearer token."
        )

    expected_api_key = settings.ML_API_KEY
    if not expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key not configured. Set ML_API_KEY environment variable."
        )

    if api_key != expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
