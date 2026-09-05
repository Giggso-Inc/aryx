"""
Python encryption utilities for URL parameters
Equivalent to the JavaScript version for backend compatibility.

Package split from the former single-file app/core/encryption_utils.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md:
- core.py           — SEPARATOR, _secret_key, encrypt/decrypt,
                       encrypt_multiple/decrypt_multiple, decrypt_urlsafe_token
- registration.py    — create_encrypted_registration_param,
                       decrypt_registration_params, create_registration_url
- password_reset.py  — create_password_reset_param,
                       decrypt_password_reset_params, create_password_reset_url
- devtest.py         — test_encryption() manual dev smoke test (not imported
                       by any app code; kept out of this __init__ so pytest
                       never has a reason to look at it)

Re-exports every name external code imported from
`app.core.encryption_utils` before the split (grepped across app/routes,
app/services, tests).
"""

from app.core.encryption_utils.core import (
    SEPARATOR,
    _secret_key,
    decrypt,
    decrypt_multiple,
    decrypt_urlsafe_token,
    encrypt,
    encrypt_multiple,
)
from app.core.encryption_utils.password_reset import (
    create_password_reset_param,
    create_password_reset_url,
    decrypt_password_reset_params,
)
from app.core.encryption_utils.registration import (
    create_encrypted_registration_param,
    create_registration_url,
    decrypt_registration_params,
)

__all__ = [
    "SEPARATOR",
    "_secret_key",
    "encrypt",
    "decrypt",
    "encrypt_multiple",
    "decrypt_multiple",
    "decrypt_urlsafe_token",
    "create_encrypted_registration_param",
    "decrypt_registration_params",
    "create_registration_url",
    "create_password_reset_param",
    "decrypt_password_reset_params",
    "create_password_reset_url",
]
