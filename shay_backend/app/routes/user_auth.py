"""
User authentication routes for registration, login, and invitations.

This module handles all user authentication operations including user registration,
login/logout, password management, and invitation workflows. It provides secure
JWT-based authentication and manages user sessions with proper security measures.

Author: Karthick Chandrasekar
Date: 2025-08-14
Version: 1.0.0
"""

# Standard library imports for UUID generation and date/time operations
import os
import re
import uuid
from datetime import datetime, timedelta

# Type hinting support for function parameters and return values
from typing import List, Optional

# FastAPI framework imports for routing, HTTP handling, and dependency injection
from fastapi import APIRouter, HTTPException, status, Request, Depends, UploadFile, File

# SQLAlchemy async support for database operations
from sqlalchemy.ext.asyncio import AsyncSession

# SQLAlchemy query building and logical operators
from sqlalchemy import select, func, and_

# Database connection dependency injection
from app.core.database import get_db

# Configuration settings
from app.core.config import settings

# Authentication utilities for JWT token creation and password verification
from app.core.auth import create_access_token, create_refresh_token, get_password_hash, verify_password
from app.core.encryption_utils import create_registration_url, decrypt, decrypt_registration_params
from app.services.email_service import email_service
from app.services.link_shortener_service import link_shortener_service
from app.services.workspace_membership import ensure_workspace_membership

# Authentication middleware for user verification
from app.middleware.auth_middleware import get_current_user_required

# File storage for profile image uploads
from app.services.file_storage import get_file_storage_service

# Database models for user, company, invitation, and workspace entities
from app.models.user import User
from app.models.company import Company
from app.models.invitation import Invitation
from app.models.workspace import Workspace

# Pydantic schemas for request/response validation and serialization
from app.schemas.user import (
    UserInviteRequest, UserInviteResponse, UserRegisterRequest, 
    UserLoginRequest, UserLoginEncryptedRequest, UserRegisterEncryptedRequest, UserResponse, UserTokenResponse, UserUpdateRequest, UserListResponse,
    BulkUserInviteRequest, BulkUserInviteResponse, BulkUserInviteItem, CurrentUserResponse, CurrentUserUpdateRequest,
    ProfileUpdateRequest, ProfileUpdateResponse, ProfileImageUploadResponse, ProfilePhotoRemoveResponse, PasswordUpdateResponse,
    SimplePasswordUpdateRequest, ForgetPasswordRequest, ForgetPasswordResponse,
    ResetPasswordRequest, ResetPasswordResponse
)
from app.schemas.sso import (
    SetPasswordRequestBody,
    SetPasswordRequestResponse,
    SetPasswordConfirmRequest,
    SetPasswordConfirmResponse,
)

router = APIRouter()


def _format_user_name_from_email(email: str, default: str = "User") -> str:
    """
    Convert the local part of an email address into a display name with each word capitalized.

    Args:
        email: The email address to parse.
        default: Fallback value when the email is missing or cannot be parsed.

    Returns:
        A title-cased name derived from the email address, or the provided default.
    """
    if not email or '@' not in email:
        return default

    local_part = email.split('@')[0]
    # Replace common separators with spaces and collapse multiple spaces
    cleaned = re.sub(r"[._\-]+", " ", local_part)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned.title() if cleaned else default


@router.post("/invite", response_model=UserInviteResponse)
async def invite_user(
    invite_data: UserInviteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Send user invitation to email with platform link"""
    # Validate template exists if template_id is provided
    if invite_data.template_id:
        try:
            from app.services.template_service import template_service
            await template_service.get_template_content(invite_data.template_id, db)
        except HTTPException as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template not found: {invite_data.template_id}"
            )
    
    # Validate company exists
    try:
        company_uuid = uuid.UUID(invite_data.company_id)
        stmt = select(Company).where(Company.id == company_uuid)
        result = await db.execute(stmt)
        company = result.scalar_one_or_none()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid company_id format: {str(e)}"
        )
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    company_name = company.name
    
    # Fetch invited_by user name if user_id is provided
    invited_by_name = "System User"  # Default fallback
    if invite_data.user_id:
        try:
            user_uuid = uuid.UUID(invite_data.user_id)
            stmt = select(User).where(User.id == user_uuid)
            result = await db.execute(stmt)
            inviting_user = result.scalar_one_or_none()
            if inviting_user:
                invited_by_name = inviting_user.name or inviting_user.email_id
        except ValueError:
            # Invalid user_id format, use default
            pass
    
    # Check if user already exists
    stmt = select(User).where(User.email_id == invite_data.email)
    result = await db.execute(stmt)
    existing_user = result.scalar_one_or_none()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists"
        )
    
    # Check if invitation already exists
    existing_invitation_stmt = select(Invitation).where(
        and_(
            Invitation.email == invite_data.email,
            Invitation.company_id == company_uuid,
            Invitation.status == "pending"
        )
    )
    existing_invitation_result = await db.execute(existing_invitation_stmt)
    existing_invitation = existing_invitation_result.scalar_one_or_none()
    
    if existing_invitation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invitation already exists for this email"
        )
    
    # Create invitation
    invite_id = uuid.uuid4()
    expires_at = datetime.utcnow() + timedelta(days=7)
    
    # Use provided user_id or default system user
    invited_by_user_id = invite_data.user_id if invite_data.user_id else "bd6aedd9-657e-4033-a9d6-1cc0b31cfd85"
    
    invitation = Invitation(
        id=invite_id,
        email=invite_data.email,
        company_id=company_uuid,
        role=invite_data.role,
        invited_by=uuid.UUID(invited_by_user_id),
        status="pending",
        expires_at=expires_at
    )
    
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)
    
    # Generate encrypted registration link
    platform_url = settings.PLATFORM_URL
    registration_link = create_registration_url(
        base_url=platform_url,
        email=invite_data.email,
        invite_code=str(invite_id),
        company_id=str(invite_data.company_id),
        role=invite_data.role
    )
    short_registration_link = await link_shortener_service.shorten(registration_link, db=db)
    
    
    # Send invitation email
    invitation_data = {
        'company_name': company_name,
        'role': invite_data.role,
        'registration_link': registration_link,
        'registration_short_link': short_registration_link,
        'invite_id': str(invite_id),
        'expires_at': expires_at.isoformat(),
        'email': invite_data.email,  # Add email for personalization
        'invited_by': invited_by_name,  # Use fetched user name
        'user_name': _format_user_name_from_email(invite_data.email),  # Extract formatted name from email
        'platform_name': invite_data.platform_name
    }
    
    # Use template-based email if template_id is provided
    if invite_data.template_id:
        email_sent = await email_service.send_template_invitation_email(
            to_email=invite_data.email,
            invitation_data=invitation_data,
            template_id=invite_data.template_id,
            platform_url=platform_url,
            db=db
        )
    else:
        # Fallback to default email
        email_sent = email_service.send_invitation_email(
            to_email=invite_data.email,
            invitation_data=invitation_data,
            platform_url=platform_url
        )
    
    if not email_sent:
        # Log the error but don't fail the invitation creation
        print(f"⚠️ Warning: Failed to send email to {invite_data.email}")
    
    return UserInviteResponse(
        message="Invitation sent successfully" + (" (Email sent)" if email_sent else " (Email failed)"),
        invite_id=str(invite_id),
        email_id=invite_data.email,
        registration_link=short_registration_link,
        expires_at=expires_at
    )


@router.post("/bulk-invite", response_model=BulkUserInviteResponse)
async def bulk_invite_users(
    bulk_invite_data: BulkUserInviteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Send bulk user invitations"""
    # Validate template exists if template_id is provided
    if bulk_invite_data.template_id:
        try:
            from app.services.template_service import template_service
            await template_service.get_template_content(bulk_invite_data.template_id, db)
        except HTTPException as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template not found: {bulk_invite_data.template_id}"
            )
    
    # Fetch invited_by user name if user_id is provided
    invited_by_name = "System User"  # Default fallback
    if bulk_invite_data.user_id:
        try:
            user_uuid = uuid.UUID(bulk_invite_data.user_id)
            stmt = select(User).where(User.id == user_uuid)
            result = await db.execute(stmt)
            inviting_user = result.scalar_one_or_none()
            if inviting_user:
                invited_by_name = inviting_user.name or inviting_user.email_id
        except ValueError:
            # Invalid user_id format, use default
            pass
    
    successful_invitations = []
    failed_invitations = []
    
    for user_invite in bulk_invite_data.users:
        try:
            # Validate company exists
            stmt = select(Company).where(Company.id == user_invite.company_id)
            result = await db.execute(stmt)
            company = result.scalar_one_or_none()
            
            if not company:
                failed_invitations.append({
                    "email_id": user_invite.email,
                    "reason": "Company not found"
                })
                continue
            company_name = company.name
            
            # Check if user already exists
            stmt = select(User).where(User.email_id == user_invite.email)
            result = await db.execute(stmt)
            existing_user = result.scalar_one_or_none()
            
            if existing_user:
                failed_invitations.append({
                    "email_id": user_invite.email,
                    "reason": "User with this email already exists"
                })
                continue
            
            # Create invitation
            invite_id = uuid.uuid4()
            expires_at = datetime.utcnow() + timedelta(days=7)
            
            # Use provided user_id or default system user
            invited_by_user_id = bulk_invite_data.user_id if bulk_invite_data.user_id else "bd6aedd9-657e-4033-a9d6-1cc0b31cfd85"
            
            invitation = Invitation(
                id=invite_id,
                email=user_invite.email,
                company_id=user_invite.company_id,
                role=user_invite.role,
                invited_by=uuid.UUID(invited_by_user_id),
                status="pending",
                expires_at=expires_at
            )
            
            db.add(invitation)
            await db.commit()
            await db.refresh(invitation)
            
            # Generate encrypted registration link
            platform_url = settings.PLATFORM_URL
            registration_link = create_registration_url(
                base_url=platform_url,
                email=user_invite.email,
                invite_code=str(invite_id),
                company_id=str(user_invite.company_id),
                role=user_invite.role
            )
            short_registration_link = await link_shortener_service.shorten(registration_link, db=db)
            
            
            # Send invitation email
            invitation_data = {
                'company_name': company_name,
                'role': user_invite.role,
                'registration_link': registration_link,
                'registration_short_link': short_registration_link,
                'invite_id': str(invite_id),
                'expires_at': expires_at.isoformat(),
                'email': user_invite.email,  # Add email for personalization
                'invited_by': invited_by_name,  # Use fetched user name
                'user_name': _format_user_name_from_email(user_invite.email),  # Extract formatted name from email
                'platform_name': bulk_invite_data.platform_name
            }
            
            # Use template-based email if template_id is provided (only from bulk request)
            if bulk_invite_data.template_id:
                email_sent = await email_service.send_template_invitation_email(
                    to_email=user_invite.email,
                    invitation_data=invitation_data,
                    template_id=bulk_invite_data.template_id,
                    platform_url=platform_url,
                    db=db
                )
            else:
                # Fallback to default email
                email_sent = email_service.send_invitation_email(
                    to_email=user_invite.email,
                    invitation_data=invitation_data,
                    platform_url=platform_url
                )
            
            message = "Invitation sent successfully" + (" (Email sent)" if email_sent else " (Email failed)")
            
            successful_invitations.append(UserInviteResponse(
                message=message,
                invite_id=str(invite_id),
                email_id=user_invite.email,
                registration_link=short_registration_link,
                expires_at=expires_at
            ))
            
        except Exception as e:
            failed_invitations.append({
                "email_id": user_invite.email,
                "reason": f"Error: {str(e)}"
            })
    
    await db.commit()
    
    return BulkUserInviteResponse(
        message=f"Bulk invitation completed. {len(successful_invitations)} successful, {len(failed_invitations)} failed",
        total_invited=len(successful_invitations),
        successful_invitations=successful_invitations,
        failed_invitations=failed_invitations
    )


@router.post("/register", response_model=UserTokenResponse)
async def register_user(
    register_data: UserRegisterEncryptedRequest,
    db: AsyncSession = Depends(get_db)
):
    """Register new user with or without invitation, supporting encrypted passwords"""
    
    # Check if user already exists
    stmt = select(User).where(User.email_id == register_data.email_id)
    result = await db.execute(stmt)
    existing_user = result.scalar_one_or_none()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists"
        )
    
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

        if encrypted_invite_data.get("email") and encrypted_invite_data["email"] != register_data.email_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email does not match invitation"
            )

        register_data.invite_id = encrypted_invite_data.get("invite_code") or register_data.invite_id
        register_data.company_id = encrypted_invite_data.get("company_id") or register_data.company_id
        register_data.role = encrypted_invite_data.get("role") or register_data.role
        role = register_data.role or "user"

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
    
    # Create user
    user_id = uuid.uuid4()
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
):
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


@router.post("/set-password/request", response_model=SetPasswordRequestResponse)
async def request_set_password(
    body: SetPasswordRequestBody,
    db: AsyncSession = Depends(get_db),
):
    """
    For SSO-only users who want to add a password.
    Always returns the same response to avoid email enumeration.
    """
    from app.models.email_verification_token import EmailVerificationToken

    result = await db.execute(
        select(User).where(User.email_id == body.email_id)
    )
    user = result.scalar_one_or_none()

    # Never reveal whether the email exists or whether the account is SSO-only.
    if user and user.password_hash is None:
        token = EmailVerificationToken.create_token(
            email=user.email_id,
            company_id=str(user.company_id),
            user_id=str(user.id),
            token_type="set_password",
            expires_in_hours=24,
        )
        db.add(token)
        await db.commit()
        set_password_link = (
            f"{settings.FRONTEND_URL}/set-password"
            f"?token={token.token}&user_id={user.id}"
        )
        email_service.send_password_reset_email(
            user.email_id,
            {
                "email": user.email_id,
                "user_name": user.name or "User",
                "reset_url": set_password_link,
                "expires_at": "24 hours",
                "platform_name": settings.PLATFORM_NAME,
            },
            settings.FRONTEND_URL,
        )  # reuse the existing password-reset email template flow.

    return SetPasswordRequestResponse(
        message="If this email exists, a password setup link has been sent."
    )


@router.post("/set-password/confirm", response_model=SetPasswordConfirmResponse)
async def confirm_set_password(
    body: SetPasswordConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Confirm and set a password for an SSO-only user using the emailed token.
    """
    from app.models.email_verification_token import EmailVerificationToken

    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token == body.token
        )
    )
    token_record = result.scalar_one_or_none()
    if not token_record:
        raise HTTPException(400, detail={
            "error_code": "SET_PWD_001",
            "message": "Invalid or expired token",
        })
    if not token_record.is_valid:
        raise HTTPException(400, detail={
            "error_code": "SET_PWD_002",
            "message": "This link has expired or already been used",
        })
    if token_record.token_type != "set_password":
        raise HTTPException(400, detail={
            "error_code": "SET_PWD_001",
            "message": "Invalid token type",
        })
    if str(token_record.user_id) != body.user_id:
        raise HTTPException(400, detail={
            "error_code": "SET_PWD_001",
            "message": "Token does not match user",
        })

    result = await db.execute(
        select(User).where(User.id == token_record.user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, detail={"message": "User not found"})

    new_password_to_use = body.new_password
    confirm_password_to_use = body.confirm_password
    if body.encrypted:
        try:
            new_password_to_use = decrypt(body.new_password)
            confirm_password_to_use = decrypt(body.confirm_password)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid encrypted password format",
            )
    if new_password_to_use != confirm_password_to_use:
        raise HTTPException(400, detail={
            "error_code": "SET_PWD_003",
            "message": "Passwords do not match",
        })
    if len(new_password_to_use) < 8 or not any(c.isupper() for c in new_password_to_use) or not any(c.islower() for c in new_password_to_use) or not any(c.isdigit() for c in new_password_to_use) or not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in new_password_to_use):
        raise HTTPException(400, detail={
            "error_code": "SET_PWD_004",
            "message": "Password must include uppercase, lowercase, digit, and special character",
        })

    user.password_hash = get_password_hash(new_password_to_use)
    token_record.mark_as_used()  # keep oauth_provider unchanged so both auth modes remain available.
    await db.commit()

    return SetPasswordConfirmResponse(
        message=(
            "Password set successfully. "
            f"You can now log in with your password or continue with "
            f"{(user.oauth_provider or 'SSO').title()}."
        ),
        success=True,
    )


@router.get("/profile", response_model=dict)
async def get_current_user_profile_details(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Get current user's detailed profile information.
    
    This endpoint retrieves the authenticated user's profile details with
    personal information, role, and preferences.
    
    Args:
        request: FastAPI request object for authentication
        db: Database session dependency
    
    Returns:
        dict: Current user's detailed profile information
        
    Raises:
        HTTPException: 401 if not authenticated
        
    Sample Response Schema:
    {
        "id": "uuid-string",
        "name": "John Doe",
        "email_id": "john.doe@example.com",
        "avatar_url": "https://example.com/avatar.jpg",
        "role": "senior_developer",
        "is_active": true,
        "is_verified": true,
        "oauth_provider": "local",
        "preferences": {
            "theme": "dark",
            "language": "en",
            "notifications": true
        },
        "last_login": "2025-01-20T10:30:00Z",
        "created_datetime": "2025-01-15T09:00:00Z",
        "updated_datetime": "2025-01-20T10:30:00Z"
    }
    
    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 20/01/2025
    """
    user = await get_current_user_required(request)
    
    # Build user profile response
    user_profile = {
        "id": str(user.id),
        "name": user.name,
        "email_id": user.email_id,
        "avatar_url": user.avatar_url,
        "role": user.role,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "oauth_provider": user.oauth_provider,
        "preferences": user.preferences,
        "last_login": user.last_login,
        "created_datetime": user.created_datetime,
        "updated_datetime": user.updated_datetime
    }
    
    return user_profile


# Allowed image extensions for profile avatar upload
PROFILE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
# Max size for profile image (5MB)
MAX_PROFILE_IMAGE_SIZE_BYTES = 5 * 1024 * 1024


@router.post("/profile/upload-image", response_model=ProfileImageUploadResponse)
async def upload_profile_image(
    file: UploadFile = File(..., description="Profile image file (jpg, png, gif, webp)"),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a profile image for the current user.
    Returns the avatar_url to use in PUT /profile (avatar_url field).
    After upload, call PUT /profile with { "avatar_url": "<returned avatar_url>" } to save it to the profile.
    """
    user = await get_current_user_required(request)
    # Validate file extension
    file_ext = os.path.splitext(file.filename or "")[1].lower()
    if file_ext not in PROFILE_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(PROFILE_IMAGE_EXTENSIONS)}"
        )
    content = await file.read()
    # Validate size
    if len(content) > MAX_PROFILE_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is {MAX_PROFILE_IMAGE_SIZE_BYTES // (1024*1024)}MB"
        )
    # Build storage path: profile/{user_id}/avatar_{timestamp}.ext
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    destination_path = f"profile/{user.id}/avatar_{timestamp}{file_ext}"
    try:
        storage_service = get_file_storage_service()
        upload_result = await storage_service.upload_file(
            file_content=content,
            destination_path=destination_path,
            original_filename=file.filename or "avatar"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload profile image: {str(e)}"
        )
    return ProfileImageUploadResponse(
        avatar_url=upload_result["file_url"],
        message="Profile image uploaded successfully"
    )


@router.delete("/profile/photo", response_model=ProfilePhotoRemoveResponse)
async def remove_profile_photo(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Remove the current user's profile photo (set avatar_url to null).

    Requires authentication. After removal, the user's avatar_url is cleared in the database.
    """
    # Resolve current user (required)
    user = await get_current_user_required(request)
    # Load user in this session for update
    stmt = select(User).where(User.id == user.id)
    result = await db.execute(stmt)
    user_row = result.scalar_one_or_none()
    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    # Clear profile photo
    user_row.avatar_url = None
    user_row.updated_datetime = datetime.utcnow()
    await db.commit()
    return ProfilePhotoRemoveResponse(message="Profile photo removed successfully")


@router.put("/profile", response_model=ProfileUpdateResponse)
async def update_current_user_personal_info(
    profile_update: ProfileUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Update current user's personal information only.
    
    This endpoint allows authenticated users to update only their personal
    information such as name, avatar URL, and preferences. Users cannot
    change sensitive fields like email, role, company association, or
    system-related fields.
    
    Args:
        profile_update: ProfileUpdateRequest containing personal fields to update
        request: FastAPI request object for authentication
        db: Database session dependency
    
    Returns:
        dict: Updated user profile information
        
    Raises:
        HTTPException: 401 if not authenticated, 400 if invalid data
        
    Sample Request Schema:
    {
        "name": "John Smith",
        "avatar_url": "https://example.com/new-avatar.jpg",
        "preferences": {
            "theme": "light",
            "language": "en",
            "notifications": true,
            "timezone": "UTC-8",
            "date_format": "MM/DD/YYYY"
        }
    }
    
    Sample Response Schema:
    {
        "message": "Profile updated successfully",
        "updated_fields": ["name", "avatar_url", "preferences"],
        "user": {
            "id": "uuid-string",
            "name": "John Smith",
            "email_id": "john.doe@example.com",
            "avatar_url": "https://example.com/new-avatar.jpg",
            "role": "senior_developer",
            "is_active": true,
            "is_verified": true,
            "oauth_provider": "local",
            "preferences": {
                "theme": "light",
                "language": "en",
                "notifications": true,
                "timezone": "UTC-8",
                "date_format": "MM/DD/YYYY"
            },
            "last_login": "2025-01-20T10:30:00Z",
            "created_datetime": "2025-01-15T09:00:00Z",
            "updated_datetime": "2025-01-20T11:45:00Z"
        }
    }
    
    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 19/08/2025
    """
    # Get current user from request state
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Query user in current database session
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Define allowed fields for personal information updates (avatar_url may be None to remove photo)
    allowed_fields = {
        "name": str,
        "avatar_url": (str, type(None)),  # str or None to clear profile photo
        "preferences": dict
    }
    
    # Convert Pydantic model to dict and filter update data
    profile_update_dict = profile_update.model_dump(exclude_unset=True)
    update_data = {}
    updated_fields = []
    
    for field, value in profile_update_dict.items():
        if field in allowed_fields:
            # Type validation (allow None for avatar_url to remove profile photo)
            allowed_types = allowed_fields[field]
            if not isinstance(allowed_types, tuple):
                allowed_types = (allowed_types,)
            if isinstance(value, allowed_types):
                update_data[field] = value
                updated_fields.append(field)
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid type for field '{field}'."
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Field '{field}' is not allowed for personal information updates"
            )
    
    # Apply updates
    if update_data:
        for field, value in update_data.items():
            if hasattr(user, field):
                setattr(user, field, value)
        
        # Update the updated_datetime field
        user.updated_datetime = datetime.utcnow()
        
        await db.commit()
        await db.refresh(user)
    
    # Build response
    user_profile = {
        "id": str(user.id),
        "name": user.name,
        "email_id": user.email_id,
        "avatar_url": user.avatar_url,
        "role": user.role,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "oauth_provider": user.oauth_provider,
        "preferences": user.preferences,
        "last_login": user.last_login,
        "created_datetime": user.created_datetime,
        "updated_datetime": user.updated_datetime
    }
    
    return ProfileUpdateResponse(
        message="Profile updated successfully",
        updated_fields=updated_fields,
        user=user_profile
    )



@router.put("/password", response_model=PasswordUpdateResponse)
async def update_current_user_password(
    password_update: SimplePasswordUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Update current user's password with a three-field validation process.
    
    This endpoint allows authenticated users to update their password by:
    1. Confirming their current password
    2. Entering a new password
    3. Confirming the new password
    
    Args:
        password_update: SimplePasswordUpdateRequest containing confirm old password, new password, and confirm new password
        request: FastAPI request object for authentication
        db: Database session dependency
    
    Returns:
        PasswordUpdateResponse: Success message and update timestamp
        
    Raises:
        HTTPException: 401 if not authenticated, 400 if validation fails, 404 if user not found
        
    Author: Pranhav Vimalbalaji
    Version: 1.0.0
    Last date modified: 19/08/2025
    """
    # Get current user from request state
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Query user in current database session
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Handle password decryption if encrypted
    old_password_to_verify = password_update.confirm_old_password
    new_password_to_use = password_update.new_password
    confirm_new_password_to_use = password_update.confirm_new_password
    
    if password_update.encrypted:
        try:
            # Decrypt the passwords if they are encrypted
            old_password_to_verify = decrypt(password_update.confirm_old_password)
            new_password_to_use = decrypt(password_update.new_password)
            confirm_new_password_to_use = decrypt(password_update.confirm_new_password)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid encrypted password format"
            )
        # Validate decrypted password strength (schema skips validation when encrypted=True)
        v = new_password_to_use
        if len(v) < 8:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters long")
        if not any(c.isupper() for c in v):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one digit")
        if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in v):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must contain at least one special character")
    
    # STEP 1: Verify old password matches stored password
    if not verify_password(old_password_to_verify, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    # STEP 2: Verify new password and confirm new password match
    if new_password_to_use != confirm_new_password_to_use:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password and confirm new password do not match"
        )
    
    # Check if new password is different from old password
    if old_password_to_verify == new_password_to_use:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password"
        )
    
    # Hash the new password using bcrypt
    new_password_hash = get_password_hash(new_password_to_use)
    
    # Update user's password hash
    user.password_hash = new_password_hash
    user.updated_datetime = datetime.utcnow()
    
    # Commit changes to database
    await db.commit()
    await db.refresh(user)
    
    # Return success response
    return PasswordUpdateResponse(
        message="Password updated successfully",
        updated_at=user.updated_datetime
    )


@router.post("/forgot-password", response_model=ForgetPasswordResponse)
async def forgot_password(
    forgot_password_data: ForgetPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Send password reset link to user's email.
    
    This endpoint generates an encrypted reset link containing user information
    and timestamp, then sends it via email using template system. The link expires after 1 hour.
    
    Args:
        forgot_password_data: ForgetPasswordRequest containing email address, base_url, 
                            optional template_id, and optional app_name for product name
        db: Database session dependency
    
    Returns:
        ForgetPasswordResponse: Confirmation that email was sent
        
    Raises:
        HTTPException: 404 if email not found, 403 if account is inactive
    """
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from app.services.email_service import EmailService
    from app.core.encryption_utils import create_password_reset_url
    from app.services.template_service import template_service

    # Note: Template validation is now handled in the main processing section with graceful fallback

    # Find user by email with company information
    from app.models.company import Company
    stmt = select(User, Company).outerjoin(Company, User.company_id == Company.id).where(User.email_id == forgot_password_data.email_id)
    result = await db.execute(stmt)
    row = result.first()
    
    # If user doesn't exist, return error
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email doesn't exist"
        )
    
    user, company = row

    # Do not send reset email to inactive users; return error in response instead.
    # Active users continue with the same flow as before (reset URL + email).
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Password reset is not available."
        )

    # Get product name - use app_name if provided, otherwise determine from base_url
    def get_product_name_from_base_url(base_url: str) -> str:
        """Map base URL to product name"""
        base_url = base_url.lower().strip()
        if "dev-zaptag.shay-ai.com" in base_url:
            return "ZapTag"
        elif "zaptag.accsell.ai" in base_url:
            return "ZapTag"  # ZapTag production
        elif "dev-loger.shay-ai.com" in base_url:
            return "Log Analyser"
        elif "dev-fourd.shay-ai.com" in base_url:
            return "Email Support App"
        elif "dev-accell.shay-ai.com" in base_url:
            return "Accsell"
        elif "app.accsell.ai" in base_url:
            return "Accsell"  # Production Accsell
        else:
            return "Shay Suite"  # Default fallback

    # Use app_name if provided and not empty, otherwise use base_url method
    if forgot_password_data.app_name and forgot_password_data.app_name.strip():
        product_name = forgot_password_data.app_name.strip()
    else:
        product_name = get_product_name_from_base_url(forgot_password_data.base_url)

    # If user exists, send reset email
    email_sent = False
    try:
        # Generate encrypted reset link using base_url from request
        timestamp = str(int(datetime.utcnow().timestamp()))
        reset_url = create_password_reset_url(
            base_url=forgot_password_data.base_url,
            user_id=str(user.id),
            email=user.email_id,
            timestamp=timestamp
        )
        # Shorten reset link for email (in-platform; falls back to original URL if shortening fails)
        short_reset_url = await link_shortener_service.shorten(reset_url, db=db)
        # Commit so ShortenedUrl row is persisted (get_db does not auto-commit)
        await db.commit()

        # Prepare template variables (use short link in email)
        template_variables = {
            'user_name': user.name or 'User',
            'company_name': product_name,  # Product name based on base_url
            'reset_link': short_reset_url,
            'expiry_hours': 1,
            'email': user.email_id,
            'timestamp': timestamp
        }

        # Use template-based email if template_id is provided
        if forgot_password_data.template_id:
            try:
                # Get template content
                template_data = await template_service.get_template_content(forgot_password_data.template_id, db)
                template_content = template_data['content']

                # Process template with variables
                processed_html = template_service.process_template_content(template_content, template_variables)

                # Create email message with HTML as primary content (subject/plain use product_name)
                msg = MIMEMultipart('related')
                msg['Subject'] = f"Password Reset - {product_name} Account"
                msg['From'] = settings.SMTP_FROM
                msg['To'] = user.email_id

                # Create HTML wrapper
                html_wrapper = MIMEMultipart('alternative')

                # Add HTML content as primary
                html_part = MIMEText(processed_html, 'html', 'utf-8')
                html_part.add_header('Content-Type', 'text/html; charset=utf-8')
                html_wrapper.attach(html_part)

                # Add minimal plain text fallback (uses product_name for branding)
                text_content = f"""Password Reset Request - {product_name} Account

Hello {template_variables['user_name']},

We received a request to reset your password for your {product_name} account.

Reset Link: {short_reset_url}

This link will expire in 1 hour.

© 2025 {product_name}. All rights reserved."""

                text_part = MIMEText(text_content, 'plain', 'utf-8')
                html_wrapper.attach(text_part)

                msg.attach(html_wrapper)

                # Send email
                email_service = EmailService()
                email_sent = email_service._send_email(msg)

            except HTTPException as e:
                print(f"❌ Template not found or error: {e.detail}")
                # Fallback to default email when template is missing (use short link like other fallbacks)
                email_sent = await _send_default_password_reset_email(user, short_reset_url, product_name)
            except Exception as e:
                print(f"❌ Error processing template: {e}")
                # Fallback to default email for other errors (use short link)
                email_sent = await _send_default_password_reset_email(user, short_reset_url, product_name)
        else:
            # Default email (use short link)
            email_sent = await _send_default_password_reset_email(user, short_reset_url, product_name)
        
    except Exception as e:
        print(f"❌ Error sending forgot password email: {e}")
        email_sent = False
    
    # Return success response (same shape as invite: include short link for frontend parity with register flow)
    return ForgetPasswordResponse(
        message="Password reset link sent to your email address",
        email_sent=email_sent,
        reset_link=short_reset_url if email_sent else None,
    )


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    reset_data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Reset user password using decrypted parameters from frontend.
    
    This endpoint accepts decrypted user information from the frontend,
    validates the user exists, and updates the user's password.
    
    Args:
        reset_data: ResetPasswordRequest containing user_id, email_id, and new password
        db: Database session dependency
    
    Returns:
        ResetPasswordResponse: Confirmation of password reset
        
    Raises:
        HTTPException: 400 for invalid data, 404 for user not found, 403 if account is inactive
    """
    try:
        # Note: base_url is available in reset_data.base_url if needed for validation
        # Find user by ID and email to verify the request
        stmt = select(User).where(
            and_(
                User.id == reset_data.user_id,
                User.email_id == reset_data.email_id
            )
        )
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found or invalid reset request"
            )

        # Reject password reset for inactive users only. Active users follow same flow as before.
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive. Password reset is not available."
            )
        
        # Handle password decryption if encrypted
        new_password_to_use = reset_data.new_password
        confirm_new_password_to_use = reset_data.confirm_new_password
        
        if reset_data.encrypted:
            try:
                # Decrypt the passwords if they are encrypted
                new_password_to_use = decrypt(reset_data.new_password)
                confirm_new_password_to_use = decrypt(reset_data.confirm_new_password)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid encrypted password format"
                )
        
        # Validate password strength after decryption (if encrypted) or for plain text
        def validate_password_strength(password: str) -> None:
            """Validate password strength"""
            if len(password) < 8:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password must be at least 8 characters long"
                )
            if not any(c.isupper() for c in password):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password must contain at least one uppercase letter"
                )
            if not any(c.islower() for c in password):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password must contain at least one lowercase letter"
                )
            if not any(c.isdigit() for c in password):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password must contain at least one digit"
                )
            if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password must contain at least one special character"
                )

        # Validate the decrypted/plain text password
        validate_password_strength(new_password_to_use)

        # Verify new password and confirm new password match
        if new_password_to_use != confirm_new_password_to_use:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password and confirm new password do not match"
            )
        
        # Hash the new password
        new_password_hash = get_password_hash(new_password_to_use)
        
        # Update user's password
        user.password_hash = new_password_hash
        user.updated_datetime = datetime.utcnow()
        
        # Commit changes
        await db.commit()
        await db.refresh(user)
        
        return ResetPasswordResponse(
            message="Password has been reset successfully",
            success=True
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error resetting password: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password reset failed"
        )


async def _send_default_password_reset_email(user, reset_url, product_name="Shay Suite"):
    """Send default password reset email (fallback when no template is used)"""
    try:
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from app.services.email_service import EmailService
        from app.core.config import settings

        # Create email content
        subject = f"Password Reset - {product_name} Account"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Password Reset - {product_name}</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #f8f9fa; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                .content {{ background-color: #ffffff; padding: 30px; border: 1px solid #e9ecef; }}
                .footer {{ background-color: #f8f9fa; padding: 20px; text-align: center; border-radius: 0 0 8px 8px; font-size: 14px; color: #6c757d; }}
                .reset-button {{ display: inline-block; background-color: #007bff; color: #ffffff !important; padding: 15px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; font-weight: bold; }}
                .warning {{ background-color: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .link-fallback {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; font-family: monospace; font-size: 12px; word-break: break-all; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🔐 Password Reset Request</h1>
                </div>
                <div class="content">
                    <h2>Hello {user.name or 'User'},</h2>

                    <p>We received a request to reset your password for your {product_name} account. Click the button below to reset your password.</p>

                    <div style="text-align: center; margin: 24px 0;">
                        <a href="{reset_url}" class="reset-button" style="display: inline-block; background-color: #007bff; color: #ffffff; padding: 14px 28px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 16px; font-family: Arial, sans-serif;">Reset My Password</a>
                    </div>

                    <div class="warning">
                        <strong>⚠️ Important Security Information:</strong>
                        <ul>
                            <li>This link will expire in <strong>1 hour</strong></li>
                            <li>If you didn't request this reset, please ignore this email</li>
                            <li>For security, this link can only be used once</li>
                        </ul>
                    </div>

                    <p>If the button doesn't work, you can copy and paste this link into your browser:</p>
                    <div class="link-fallback">{reset_url}</div>

                    <p>If you have any questions or need assistance, please contact your system administrator.</p>
                </div>
                <div class="footer">
                    <p>This email was sent from {settings.SMTP_FROM}</p>
                    <p>© 2025 {product_name}. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_content = f"""
        Password Reset Request - {product_name} Account

        Hello {user.name or 'User'},

        We received a request to reset your password for your {product_name} account. Click the link below to reset your password.

        Reset Link: {reset_url}

        IMPORTANT SECURITY INFORMATION:
        - This link will expire in 1 hour
        - If you didn't request this reset, please ignore this email
        - For security, this link can only be used once

        If you have any questions or need assistance, please contact your system administrator.

        This email was sent from {settings.SMTP_FROM}
        © 2025 {product_name}. All rights reserved.
        """

        # Create email message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = settings.SMTP_FROM
        msg['To'] = user.email_id

        # Add text and HTML parts
        text_part = MIMEText(text_content, 'plain')
        html_part = MIMEText(html_content, 'html')

        msg.attach(text_part)
        msg.attach(html_part)

        # Send email
        email_service = EmailService()
        return email_service._send_email(msg)

    except Exception as e:
        print(f"❌ Error sending default password reset email: {e}")
        return False
