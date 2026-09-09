"""
Authentication utilities and JWT token management.

Package split from the former single-file app/core/auth.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md:
- tokens.py    — JWT access/refresh token create/verify/decode,
                 get_current_user_payload, TokenData, create_token_data,
                 the shared HTTPBearer `security` instance
- passwords.py — bcrypt/passlib setup + hash_password/verify_password/
                 get_password_hash/validate_password_length
- ids.py       — UUID4 generators for every domain entity

HIGH CAUTION (per task): this is auth-critical JWT/token code. Every name
below is re-exported unchanged; grepped across 43 files that import from
`app.core.auth` (app/routes/*, app/middleware/auth_middleware.py) before
committing to this layout — nothing here changes signatures or behavior.
"""

from app.core.auth.ids import (
    generate_ai_response_id,
    generate_approval_id,
    generate_attachment_id,
    generate_channel_id,
    generate_company_id,
    generate_message_id,
    generate_user_id,
    generate_workspace_id,
)
from app.core.auth.passwords import (
    BCRYPT_AVAILABLE,
    get_password_hash,
    hash_password,
    pwd_context,
    validate_password_length,
    verify_password,
)
from app.core.auth.tokens import (
    TokenData,
    create_access_token,
    create_refresh_token,
    create_token_data,
    decode_access_token,
    get_current_user_payload,
    security,
    verify_token,
)

__all__ = [
    "create_access_token",
    "create_refresh_token",
    "verify_token",
    "decode_access_token",
    "get_current_user_payload",
    "TokenData",
    "create_token_data",
    "security",
    "hash_password",
    "verify_password",
    "get_password_hash",
    "validate_password_length",
    "pwd_context",
    "BCRYPT_AVAILABLE",
    "generate_user_id",
    "generate_company_id",
    "generate_workspace_id",
    "generate_message_id",
    "generate_approval_id",
    "generate_attachment_id",
    "generate_channel_id",
    "generate_ai_response_id",
]
