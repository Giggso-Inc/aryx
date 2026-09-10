"""
Registration URL/param helpers built on top of app.core.encryption_utils.core.

Split out of app/core/encryption_utils.py — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.
"""

import urllib.parse

from app.core.encryption_utils.core import decrypt_multiple, encrypt_multiple


def create_encrypted_registration_param(email: str, invite_code: str, company_id: str, role: str) -> str:
    """
    Creates an encrypted URL parameter for registration
    Args:
        email: User's email
        invite_code: Invitation code
        company_id: Company ID
        role: User role
    Returns:
        Encrypted parameter string
    """
    return encrypt_multiple([email, invite_code, company_id, role])

def decrypt_registration_params(encrypted_param: str) -> dict:
    """
    Decrypts registration parameters from URL
    Args:
        encrypted_param: The encrypted parameter from URL
    Returns:
        Dictionary with email, invite_code, company_id, and role
    """
    [email, invite_code, company_id, role] = decrypt_multiple(encrypted_param)
    return {
        'email': email,
        'invite_code': invite_code,
        'company_id': company_id,
        'role': role
    }

def create_registration_url(base_url: str, email: str, invite_code: str, company_id: str, role: str) -> str:
    """
    Creates a registration URL with encrypted parameters
    Args:
        base_url: Base URL for registration
        email: User's email
        invite_code: Invitation code
        company_id: Company ID
        role: User role
    Returns:
        Complete registration URL with URL-encoded encrypted parameter
    """
    encrypted_param = create_encrypted_registration_param(email, invite_code, company_id, role)
    # URL encode the encrypted parameter (equivalent to encodeURIComponent in JavaScript)
    encoded_param = urllib.parse.quote(encrypted_param, safe='')
    return f"{base_url}/register?e={encoded_param}"
