"""
Registration and login routes: register_user, login_user.

Split out of the original monolithic app/routes/user_auth.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.core.auth import create_access_token, create_refresh_token, get_password_hash, verify_password
from app.core.encryption_utils import decrypt, decrypt_registration_params
from app.services.workspace_membership import ensure_workspace_membership

from app.models.user import User
from app.models.company import Company
from app.models.invitation import Invitation
from app.models.workspace import Workspace

from app.schemas.user import (
    UserRegisterEncryptedRequest, UserLoginEncryptedRequest, UserTokenResponse,
)

router = APIRouter()


@router.post("/register", response_model=UserTokenResponse)
async def register_user(
    register_data: UserRegisterEncryptedRequest,
    db: AsyncSession = Depends(get_db)
) -> UserTokenResponse:
    """Register new user with or without invitation, supporting encrypted passwords"""

    # Handle password decryption if encrypted
    password_to_use = register_data.password

    if register_data.encrypted:
        try:
            # Decrypt the password if it's encrypted
            password_to_use = decrypt(register_data.password)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid encrypted password format"
            )

    company_id = None
    role = register_data.role or "user"
    encrypted_invite_data = None

    if register_data.encrypted_param:
        try:
            encrypted_invite_data = decrypt_registration_params(register_data.encrypted_param)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid encrypted invitation format"
            )

        invited_email = (encrypted_invite_data.get("email") or "").strip()
        if invited_email and not register_data.email_id:
            register_data.email_id = invited_email
        if invited_email and invited_email != register_data.email_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email does not match invitation"
            )

        register_data.invite_id = encrypted_invite_data.get("invite_code") or register_data.invite_id
        register_data.company_id = encrypted_invite_data.get("company_id") or register_data.company_id
        register_data.role = encrypted_invite_data.get("role") or register_data.role
        role = register_data.role or "user"

    stmt = select(User).where(User.email_id == register_data.email_id)
    result = await db.execute(stmt)
    existing_user = result.scalar_one_or_none()
    if existing_user and existing_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists"
        )
    if existing_user and not register_data.invite_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists"
        )

    if register_data.invite_id:
        # Validate invite_id as UUID
        try:
            invite_uuid = uuid.UUID(register_data.invite_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid invitation ID format. Must be a valid UUID."
            )

        # Registration with invitation
        stmt = select(Invitation).where(Invitation.id == invite_uuid)
        result = await db.execute(stmt)
        invitation = result.scalar_one_or_none()

        if not invitation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation not found"
            )

        if invitation.status == "used":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invitation has already been used"
            )

        if invitation.status == "expired" or not invitation.is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invitation has expired"
            )

        if invitation.email != register_data.email_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email does not match invitation"
            )

        company_id = invitation.company_id
        role = invitation.role

        # Mark invitation as used
        invitation.status = "used"
        invitation.updated_at = datetime.utcnow()

    else:
        # Registration without invitation
        if not register_data.company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Company ID is required when registering without invitation"
            )

        # Validate company exists
        stmt = select(Company).where(Company.id == register_data.company_id)
        result = await db.execute(stmt)
        company = result.scalar_one_or_none()

        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found"
            )

        company_id = register_data.company_id

    password_hash = get_password_hash(password_to_use)

    # Determine user name: use provided name, or extract from email, or use default
    if register_data.name and register_data.name.strip():
        # Use the name provided in the request
        user_name = register_data.name.strip()
    elif register_data.email_id:
        # Extract name from email if no name provided
        user_name = register_data.email_id.split('@')[0].replace('.', ' ').title()
    else:
        # Fallback to default
        user_name = "User"

    if existing_user:
        user = existing_user
        user.name = user_name
        user.email_id = register_data.email_id
        user.company_id = company_id
        user.role = role
        user.is_active = True
        user.is_verified = True
        user.password_hash = password_hash
        user.updated_datetime = datetime.utcnow()
    else:
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            name=user_name,
            email_id=register_data.email_id,
            company_id=company_id,
            role=role,
            is_verified=True,
            password_hash=password_hash
        )
        db.add(user)

    await db.commit()
    await db.refresh(user)

    # Get company information
    stmt = select(Company).where(Company.id == user.company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # Check if default workspace exists for this company
    stmt = select(Workspace).where(
        and_(
            Workspace.company_id == user.company_id,
            Workspace.name == company.name,
            Workspace.is_active == True
        )
    )
    result = await db.execute(stmt)
    default_workspace = result.scalar_one_or_none()

    # Create default workspace if it doesn't exist
    if not default_workspace:
        workspace_id = uuid.uuid4()
        default_workspace = Workspace(
            id=workspace_id,
            name=company.name,
            description=f"Default workspace for {company.name}",
            company_id=user.company_id,
            created_by=user.id,
            is_active=True,
            is_public=False,
            ai_enabled=True,
            ai_provider="openai",
            ai_model="gpt-4",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(default_workspace)
        await db.commit()
        await db.refresh(default_workspace)

    await ensure_workspace_membership(
        db,
        workspace=default_workspace,
        user=user,
        role="admin" if user.role == "admin" else "member",
    )
    await db.commit()

    # Create JWT tokens
    token_data = {
        "sub": str(user.id),
        "email": user.email_id,
        "role": user.role,
        "company_id": str(user.company_id),
        "type": "access"
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return UserTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=1800,  # 30 minutes
        user_id=str(user.id),
        email_id=user.email_id,
        name=user.name,
        avatar_url=user.avatar_url,
        role=user.role,
        company_id=str(user.company_id),
        default_workspace_id=str(default_workspace.id) if default_workspace else None
    )


@router.post("/login", response_model=UserTokenResponse)
async def login_user(
    login_data: UserLoginEncryptedRequest,
    db: AsyncSession = Depends(get_db)
) -> UserTokenResponse:
    """
    Authenticate user with email and password, returning JWT tokens.

    This endpoint handles user login by validating credentials and updating
    the user's last_login timestamp. It supports both encrypted and non-encrypted
    passwords based on the 'encrypted' flag in the request.

    Args:
        login_data: UserLoginEncryptedRequest containing email, password, and encrypted flag
        db: Database session dependency

    Returns:
        UserTokenResponse: JWT access and refresh tokens with user info

    Raises:
        HTTPException: 404 with error_code E004 when email not in DB,
                       401 with "Invalid password" for wrong password, 404 for company not found
    """

    # Find user by email in database
    stmt = select(User).where(User.email_id == login_data.email_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    # Return Account not found with error code E004 when email_id does not exist in DB
    # (early return only; all logic below unchanged: password check, tokens, company, workspace)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "Account not found",
                "error_code": "E004"
            }
        )

    # Check if user is active (RCA: Login endpoint does not validate user active status)
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Account is inactive. Please contact support.",
                "error_code": "E005"
            }
        )

    # Case 1: SSO-only user (no password set) attempting password login.
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

    # Handle password verification based on encryption flag
    password_to_verify = login_data.password

    # Debug logging for password processing
    print(f"🔍 Login Debug - Email: {login_data.email_id}")
    print(f"🔍 Login Debug - Encrypted flag: {login_data.encrypted}")
    print(f"🔍 Login Debug - Password length (bytes): {len(password_to_verify.encode('utf-8'))}")
    print(f"🔍 Login Debug - Password length (chars): {len(password_to_verify)}")

    if login_data.encrypted:
        try:
            # Decrypt the password if it's encrypted
            password_to_verify = decrypt(login_data.password)
            print(f"🔍 Login Debug - After decryption length (bytes): {len(password_to_verify.encode('utf-8'))}")
        except Exception as e:
            print(f"❌ Login Debug - Decryption error: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid encrypted password format"
            )

    # Verify password
    try:
        print(f"🔍 Login Debug - Stored hash preview: {user.password_hash[:20]}...")
        print(f"🔍 Login Debug - Stored hash length: {len(user.password_hash)}")
        password_valid = verify_password(password_to_verify, user.password_hash)
        print(f"🔍 Login Debug - Password verification result: {password_valid}")
    except Exception as e:
        print(f"❌ Login Debug - Password verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Password verification failed: {str(e)}"
        )

    # Valid email but wrong password: return Invalid password
    if not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password"
        )

    # Update last login time
    user.last_login = datetime.utcnow()
    await db.commit()

    # Get company information
    stmt = select(Company).where(Company.id == user.company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # Check if company is active (RCA: Login endpoint does not validate company active status)
    if not company.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Company account is inactive. Please contact support.",
                "error_code": "E006"
            }
        )

    # Check if default workspace exists for this company
    stmt = select(Workspace).where(
        and_(
            Workspace.company_id == user.company_id,
            Workspace.name == company.name,
            Workspace.is_active == True
        )
    )
    result = await db.execute(stmt)
    default_workspace = result.scalar_one_or_none()

    # Create default workspace if it doesn't exist
    if not default_workspace:
        workspace_id = uuid.uuid4()
        default_workspace = Workspace(
            id=workspace_id,
            name=company.name,
            description=f"Default workspace for {company.name}",
            company_id=user.company_id,
            created_by=user.id,
            is_active=True,
            is_public=False,
            ai_enabled=True,
            ai_provider="openai",
            ai_model="gpt-4",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(default_workspace)
        await db.commit()
        await db.refresh(default_workspace)

    await ensure_workspace_membership(
        db,
        workspace=default_workspace,
        user=user,
        role="admin" if user.role == "admin" else "member",
    )
    await db.commit()

    # Create JWT tokens
    token_data = {
        "sub": str(user.id),
        "email": user.email_id,
        "role": user.role,
        "company_id": str(user.company_id),
        "type": "access"
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return UserTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=1800,  # 30 minutes
        user_id=str(user.id),
        email_id=user.email_id,
        name=user.name,
        avatar_url=user.avatar_url,
        role=user.role,
        company_id=str(user.company_id),
        company_name=company.name,
        default_workspace_id=str(default_workspace.id) if default_workspace else None
    )
