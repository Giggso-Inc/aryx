"""
Invitation route: decrypt_registration_invite.

Split out of the original monolithic invitations.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up).
"""

from fastapi import APIRouter, HTTPException, status

from app.core.encryption_utils import decrypt_registration_params

from app.schemas.user import RegistrationInviteResponse

router = APIRouter()


@router.get("/decrypt-registration", response_model=RegistrationInviteResponse)
async def decrypt_registration_invite(
    e: str
) -> RegistrationInviteResponse:
    """Decrypt an encrypted invitation payload for the registration page."""
    try:
        encrypted_invite_data = decrypt_registration_params(e)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid encrypted invitation format"
        )

    email_id = (encrypted_invite_data.get("email") or "").strip()
    invite_id = (encrypted_invite_data.get("invite_code") or "").strip()
    company_id = (encrypted_invite_data.get("company_id") or "").strip()
    role = (encrypted_invite_data.get("role") or "user").strip() or "user"

    if not email_id or not invite_id or not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid encrypted invitation format"
        )

    return RegistrationInviteResponse(
        email_id=email_id,
        invite_id=invite_id,
        company_id=company_id,
        role=role,
    )
