"""
Shared password-strength validation for the password-reset routes.

Split out of the original password_reset.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up). Both
update_password.py and reset_password.py ran this exact same set of checks
inline/nested; consolidated here since it's genuinely reused by 2+ endpoints.
Not patched by any test.
"""

from fastapi import HTTPException, status


def _validate_password_strength(password: str) -> None:
    """Raise 400 Bad Request if the password doesn't meet strength requirements."""
    if len(password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters long")
    if not any(c.isupper() for c in password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one uppercase letter")
    if not any(c.islower() for c in password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one digit")
    if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one special character")
