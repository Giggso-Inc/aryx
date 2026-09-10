"""
Password-reset URL/param helpers built on top of app.core.encryption_utils.core.

Split out of app/core/encryption_utils.py — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.
"""

import urllib.parse

from app.core.encryption_utils.core import decrypt_multiple, encrypt_multiple


def create_password_reset_param(user_id: str, email: str, timestamp: str) -> str:
    """
    Creates an encrypted URL parameter for password reset
    Args:
        user_id: User's ID
        email: User's email
        timestamp: Timestamp when reset was requested
    Returns:
        Encrypted parameter string
    """
    return encrypt_multiple([user_id, email, timestamp])


def decrypt_password_reset_params(encrypted_param: str) -> dict:
    """
    Decrypts password reset parameters from URL
    Args:
        encrypted_param: The encrypted parameter from URL
    Returns:
        Dictionary with user_id, email, and timestamp
    """
    [user_id, email, timestamp] = decrypt_multiple(encrypted_param)
    return {
        'user_id': user_id,
        'email': email,
        'timestamp': timestamp
    }


def create_password_reset_url(base_url: str, user_id: str, email: str, timestamp: str) -> str:
    """
    Creates a password reset URL with encrypted parameters
    Args:
        base_url: Base URL for password reset
        user_id: User's ID
        email: User's email
        timestamp: Timestamp when reset was requested
    Returns:
        Complete password reset URL with URL-encoded encrypted parameter
    """
    encrypted_param = create_password_reset_param(user_id, email, timestamp)
    # URL encode the encrypted parameter
    encoded_param = urllib.parse.quote(encrypted_param, safe='')
    return f"{base_url}/reset-password?token={encoded_param}"
