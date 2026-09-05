"""
Private helpers for login.py's login_user endpoint.

Split out of registration.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up) so
login.py itself stays under the 150-line limit.

`_verify_login_credentials` is the one piece here that tests patch directly
(`verify_password`) — see tests/test_user_auth_characterization.py, which
now targets `app.routes.user_auth._login_helpers.verify_password`.
"""

from fastapi import HTTPException, status

from app.core.auth import verify_password
from app.core.encryption_utils import decrypt


def _ensure_login_allowed(user) -> None:
    """Raise if the user account can't do a password login right now."""
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Account is inactive. Please contact support.",
                "error_code": "E005"
            }
        )

    if user.password_hash is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "E007",
                "message": (
                    f"This account was created using "
                    f"{(user.oauth_provider or 'sso').title()} sign-in. "
                    f"Please use 'Continue with {(user.oauth_provider or 'SSO').title()}' "
                    f"to log in, or click 'Set a password' to create one."
                ),
                "oauth_provider": user.oauth_provider,
                "action": "use_sso",
            }
        )


def _verify_login_credentials(login_data, user) -> None:
    """Decrypt (if needed) and verify the submitted password, raising on failure."""
    password_to_verify = login_data.password

    print(f"\U0001f50d Login Debug - Email: {login_data.email_id}")
    print(f"\U0001f50d Login Debug - Encrypted flag: {login_data.encrypted}")
    print(f"\U0001f50d Login Debug - Password length (bytes): {len(password_to_verify.encode('utf-8'))}")
    print(f"\U0001f50d Login Debug - Password length (chars): {len(password_to_verify)}")

    if login_data.encrypted:
        try:
            password_to_verify = decrypt(login_data.password)
            print(f"\U0001f50d Login Debug - After decryption length (bytes): {len(password_to_verify.encode('utf-8'))}")
        except Exception as e:
            print(f"❌ Login Debug - Decryption error: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid encrypted password format"
            )

    try:
        print(f"\U0001f50d Login Debug - Stored hash preview: {user.password_hash[:20]}...")
        print(f"\U0001f50d Login Debug - Stored hash length: {len(user.password_hash)}")
        password_valid = verify_password(password_to_verify, user.password_hash)
        print(f"\U0001f50d Login Debug - Password verification result: {password_valid}")
    except Exception as e:
        print(f"❌ Login Debug - Password verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Password verification failed: {str(e)}"
        )

    if not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password"
        )
