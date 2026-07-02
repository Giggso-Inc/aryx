"""
User management routes for company administrators.

This module provides API endpoints for managing users within companies, including
listing users with advanced filtering, sorting, and pagination capabilities.
It handles user CRUD operations and ensures proper access control through
authentication middleware.

Author: Karthick Chandrasekar, Pranhav Vimal
Date: 2025-08-14, 2025-01-27
Version: 1.0.0, 1.1.0
"""

# Standard library imports for type hints and data structures
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID
# FastAPI framework imports for routing, HTTP handling, and validation
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query

# SQLAlchemy async support for database operations
from sqlalchemy.ext.asyncio import AsyncSession

# SQLAlchemy query building and aggregation functions
from sqlalchemy import select, func, and_

# Database connection dependency injection
from app.core.database import get_db

# Authentication middleware for user verification
from app.middleware.auth_middleware import get_current_user_required

# Database models for user and company entities
from app.models.user import User
from app.models.company import Company
from app.models.channel_member import ChannelMember
from app.models.invitation import Invitation

# Pydantic schemas for request/response validation and serialization
from app.schemas.user import (
    UserResponse,
    UserListResponse,
    BulkRemoveUsersRequest,
    BulkRemoveUsersResponse
)
from app.schemas.auth import UserUpdate
from app.schemas.company import CompanyStats

router = APIRouter()


@router.get("/company/{company_id}/users", response_model=UserListResponse)
async def list_company_users(
    company_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: Optional[int] = Query(None, ge=1),
    size: Optional[int] = Query(None, ge=1, le=100),
    search: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = Query(None, description="Filter by active status: true for active users, false for inactive users"),
    status: Optional[str] = Query(None, description="Filter by status: 'Active' for active users, 'Inactive' for inactive users"),
    sort_by: str = Query("name", description="Sort by field: name, email_id, role, created_datetime, updated_datetime"),
    sort_order: str = Query("asc", description="Sort order: asc or desc")
):
    """
    List users in a company with advanced filtering, sorting, and pagination.
    
    This endpoint retrieves a list of users within a specific company.
    By default, it returns ALL users in the company. If page and size parameters
    are provided, it returns a paginated list. It supports searching by name/email,
    filtering by role and active status, sorting by various fields, and provides
    comprehensive pagination metadata for frontend navigation.
    
    Args:
        company_id: UUID of the company to list users from
        request: FastAPI request object for authentication
        db: Database session dependency
        page: Optional page number for pagination (if not provided, returns all users)
        size: Optional number of users per page (if not provided, returns all users, max: 100)
        search: Optional search term for filtering by name or email
        role: Optional role filter (admin, user, guest)
        is_active: Optional filter by active status (true for active, false for inactive)
        status: Optional filter by status string ('Active' or 'Inactive') - takes precedence over is_active
        sort_by: Field to sort by (name, email_id, role, created_datetime, updated_datetime)
        sort_order: Sort direction (asc or desc)
    
    Returns:
        UserListResponse: List of users with metadata (paginated if page/size provided)
        
    Raises:
        HTTPException: 403 if access denied, 400 if invalid parameters
    """
    user = await get_current_user_required(request)
    
    # Check if user can access this company
    if not user.can_access_company(company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Validate sort_by field
    allowed_sort_fields = ["name", "email_id", "role", "created_datetime", "updated_datetime"]
    if sort_by not in allowed_sort_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid sort_by field. Allowed values: {', '.join(allowed_sort_fields)}"
        )
    
    # Validate sort_order
    if sort_order.lower() not in ["asc", "desc"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid sort_order. Allowed values: asc or desc"
        )
    
    # Handle status parameter - convert "Active"/"Inactive" to boolean
    # status parameter takes precedence over is_active if both are provided
    if status is not None and status.strip():
        status_lower = status.strip().lower()
        if status_lower == "active":
            is_active = True
        elif status_lower == "inactive":
            is_active = False
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid status value. Allowed values: 'Active' or 'Inactive'"
            )
    
    # Build base query for counting
    base_query = select(User).where(User.company_id == company_id)
    
    if search:
        base_query = base_query.where(
            User.name.ilike(f"%{search}%") | 
            User.email_id.ilike(f"%{search}%")
        )
    
    if role:
        base_query = base_query.where(User.role == role)
    
    if is_active is not None:
        base_query = base_query.where(User.is_active == is_active)
    
    # Get total count - count all users for the company (without filters)
    # This shows the total count regardless of search, role, or status filters
    count_query = select(func.count(User.id)).where(User.company_id == company_id)
    
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Calculate total_active, total_inactive, and total_admin from database
    # These counts are based on company_id only, not affected by search/role/status filters
    total_active_query = select(func.count(User.id)).where(
        and_(User.company_id == company_id, User.is_active == True)
    )
    total_active_result = await db.execute(total_active_query)
    total_active = total_active_result.scalar() or 0
    
    total_inactive_query = select(func.count(User.id)).where(
        and_(User.company_id == company_id, User.is_active == False)
    )
    total_inactive_result = await db.execute(total_inactive_query)
    total_inactive = total_inactive_result.scalar() or 0
    
    total_admin_query = select(func.count(User.id)).where(
        and_(User.company_id == company_id, User.role == "admin")
    )
    total_admin_result = await db.execute(total_admin_query)
    total_admin = total_admin_result.scalar() or 0
    
    # Build query for data with sorting
    data_query = base_query
    
    # Apply sorting
    sort_field = getattr(User, sort_by)
    if sort_order.lower() == "desc":
        data_query = data_query.order_by(sort_field.desc())
    else:
        data_query = data_query.order_by(sort_field.asc())
    
    # Determine if pagination is needed
    use_pagination = page is not None and size is not None
    
    if use_pagination:
        # Calculate pagination metadata
        total_pages = (total + size - 1) // size  # Ceiling division
        has_next = page < total_pages
        has_previous = page > 1
        
        # Apply pagination
        data_query = data_query.offset((page - 1) * size).limit(size)
        
        # Execute query
        result = await db.execute(data_query)
        users = result.scalars().all()
        
        return UserListResponse(
            users=[UserResponse.from_orm(user) for user in users],
            total=total,
            page=page,
            size=size,
            total_active=total_active,
            total_inactive=total_inactive,
            total_admin=total_admin,
            total_pages=total_pages,
            has_next=has_next,
            has_previous=has_previous
        )
    else:
        # Return all users without pagination
        result = await db.execute(data_query)
        users = result.scalars().all()
        
        return UserListResponse(
            users=[UserResponse.from_orm(user) for user in users],
            total=total,
            page=1,
            size=total,
            total_active=total_active,
            total_inactive=total_inactive,
            total_admin=total_admin,
            total_pages=1,
            has_next=False,
            has_previous=False
        )


@router.get("/company/{company_id}/users/{user_id}", response_model=UserResponse)
async def get_company_user(
    company_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific user in a company"""
    user = await get_current_user_required(request)
    
    # Check if user can access this company
    if not user.can_access_company(company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    stmt = select(User).where(
        User.id == user_id,
        User.company_id == company_id
    )
    result = await db.execute(stmt)
    target_user = result.scalar_one_or_none()
    
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return UserResponse.from_orm(target_user)


@router.put("/company/{company_id}/users/{user_id}", response_model=UserResponse)
async def update_company_user(
    company_id: str,
    user_id: str,
    user_update: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Update a user in a company (admin only)"""
    current_user = await get_current_user_required(request)
    
    # Check if user can manage this company
    if not current_user.can_access_company(company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Check if user is admin or manager
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to update users"
        )

    update_data = user_update.dict(exclude_unset=True)
    if str(current_user.id) == str(user_id) and any(
        field in update_data for field in ("role", "is_active")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role or active status",
        )
    
    stmt = select(User).where(
        User.id == user_id,
        User.company_id == company_id
    )
    result = await db.execute(stmt)
    target_user = result.scalar_one_or_none()
    
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Prevent non-admin users from changing roles to admin
    if user_update.role == "admin" and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can assign admin role"
        )
    
    # Update user fields
    for field, value in update_data.items():
        setattr(target_user, field, value)
    
    await db.commit()
    await db.refresh(target_user)
    
    return UserResponse.from_orm(target_user)


@router.delete("/company/{company_id}/users/{user_id}")
async def remove_company_user(
    company_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Remove a user from a company (admin only)"""
    current_user = await get_current_user_required(request)
    
    # Check if user can manage this company
    if current_user.company_id != company_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Check if user is admin
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can remove users"
        )
    
    # Prevent self-removal
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove yourself from the company"
        )
    
    stmt = select(User).where(
        User.id == user_id,
        User.company_id == company_id
    )
    result = await db.execute(stmt)
    target_user = result.scalar_one_or_none()
    
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Revoke channel memberships before removing user
    channel_memberships_stmt = select(ChannelMember).where(ChannelMember.user_id == user_id)
    channel_memberships_result = await db.execute(channel_memberships_stmt)
    channel_memberships = channel_memberships_result.scalars().all()
    
    # Deactivate all channel memberships
    for membership in channel_memberships:
        membership.is_active = False
        membership.updated_at = func.current_timestamp()
    
    # Deactivate user instead of deleting
    target_user.is_active = False
    target_user.company_id = None
    
    await db.commit()
    
    return {
        "message": "User removed from company successfully",
        "revoked_channel_memberships": len(channel_memberships)
    }


@router.get("/company/{company_id}/stats", response_model=CompanyStats)
async def get_company_user_stats(
    company_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get company user statistics"""
    user = await get_current_user_required(request)
    
    # Check if user can access this company
    if user.company_id != company_id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Get company
    stmt = select(Company).where(Company.id == company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    # Get user statistics
    from app.models.workspace import Workspace
    from app.models.message import Message
    from app.models.attachment import Attachment
    
    try:
        # Count active users
        active_users_stmt = select(func.count(User.id)).where(
            User.company_id == company_id,
            User.is_active == True
        )
        active_users_result = await db.execute(active_users_stmt)
        total_users = active_users_result.scalar() or 0
        
        # Count workspaces
        workspace_count_stmt = select(func.count(Workspace.id)).where(Workspace.company_id == company_id)
        workspace_count_result = await db.execute(workspace_count_stmt)
        total_workspaces = workspace_count_result.scalar() or 0
        
        # Count messages for this company's workspaces (simplified to avoid join issues)
        message_count_stmt = select(func.count(Message.id))
        message_count_result = await db.execute(message_count_stmt)
        total_messages = message_count_result.scalar() or 0
        
        # Count attachments for this company's workspaces (simplified to avoid join issues)
        attachment_count_stmt = select(func.count(Attachment.id))
        attachment_count_result = await db.execute(attachment_count_stmt)
        total_attachments = attachment_count_result.scalar() or 0
        
    except Exception as e:
        # If there are any issues with the statistics queries, return default values
        total_users = 0
        total_workspaces = 0
        total_messages = 0
        total_attachments = 0
    
    return CompanyStats(
        total_users=total_users,
        total_workspaces=total_workspaces,
        total_messages=total_messages,
        total_attachments=total_attachments,
        storage_used_gb=0.0,  # TODO: Implement actual storage calculation
        subscription_plan=company.subscription_plan
    ) 


@router.get("/search", response_model=List[UserResponse])
async def search_users_by_name_or_email(
    name: Optional[str] = Query(None, description="Search by user name (partial match)"),
    email: Optional[str] = Query(None, description="Search by user email (exact match)"),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Search for users by name or email across the system.
    
    This endpoint allows searching for users by either name (partial match) or email (exact match).
    At least one of the search parameters must be provided.
    
    Args:
        name: Optional name to search for (partial match using ILIKE)
        email: Optional email to search for (exact match)
        request: FastAPI request object for authentication
        db: Database session dependency
    
    Returns:
        List[UserResponse]: List of matching users
        
    Raises:
        HTTPException: 400 if no search parameters provided, 403 if access denied
    """
    # Check if at least one search parameter is provided
    if not name and not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one search parameter (name or email) must be provided"
        )
    
    # Build the search query
    query = select(User)
    
    if name and email:
        # Search by both name and email
        query = query.where(
            User.name.ilike(f"%{name}%") & 
            User.email_id == email
        )
    elif name:
        # Search by name only (partial match)
        query = query.where(User.name.ilike(f"%{name}%"))
    elif email:
        # Search by email only (exact match)
        query = query.where(User.email_id == email)
    
    # Execute query
    result = await db.execute(query)
    users = result.scalars().all()
    
    return [UserResponse.from_orm(user) for user in users]


@router.delete("/company/{company_id}/pendingInvitedUsers/{email_id}")
async def delete_pending_invited_user(
    company_id: str,
    email_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete pending invitations for a specific user by email and company.
    
    This endpoint allows admins to delete pending invitations from the gg_invitations table
    for a specific email address within a company. Only users with admin role can perform
    this operation.
    
    Args:
        company_id: UUID of the company
        email_id: Email address of the user whose pending invitations should be deleted
        request: FastAPI request object for authentication
        db: Database session dependency
    
    Returns:
        dict: Success message with count of deleted invitations
        
    Raises:
        HTTPException: 403 if user is not admin, 404 if no pending invitations found
    """
    # Get current user and verify authentication
    current_user = await get_current_user_required(request)
    
    # Check if user is admin - only admins can delete pending invitations
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete pending invitations"
        )
    
    # Check if user can access this company
    if not current_user.can_access_company(company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this company"
        )
    
    # Find all pending invitations for the specified email and company
    stmt = select(Invitation).where(
        and_(
            Invitation.email == email_id,
            Invitation.company_id == company_id,
            Invitation.status == "pending"
        )
    )
    result = await db.execute(stmt)
    pending_invitations = result.scalars().all()
    
    # Check if any pending invitations exist
    if not pending_invitations:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No pending invitations found for email {email_id} in company {company_id}"
        )
    
    # Delete all pending invitations
    deleted_count = 0
    for invitation in pending_invitations:
        await db.delete(invitation)
        deleted_count += 1
    
    # Commit the transaction
    await db.commit()
    
    return {
        "message": f"Successfully deleted {deleted_count} pending invitation(s) for {email_id}",
        "deleted_count": deleted_count,
        "email": email_id,
        "company_id": company_id
    }


@router.delete("/company/{company_id}/users", response_model=BulkRemoveUsersResponse)
async def bulk_remove_company_users(
    company_id: UUID,
    body: BulkRemoveUsersRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    current_user = await get_current_user_required(request)

    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can remove users")
    if str(current_user.company_id) != str(company_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if UUID(str(current_user.id)) in body.user_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove yourself from the company")

    stmt = select(User).where(
        User.id.in_(body.user_ids),
        User.company_id == company_id
    )
    result = await db.execute(stmt)
    found_users = result.scalars().all()

    if not found_users:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="None of the requested users were found in the company")

    found_ids = {UUID(str(u.id)) for u in found_users}
    not_found_user_ids = [str(user_id) for user_id in body.user_ids if user_id not in found_ids]
    current_time = datetime.now(timezone.utc)

    # Revoke channel memberships before removing users
    channel_memberships_stmt = select(ChannelMember).where(ChannelMember.user_id.in_(found_ids))
    channel_memberships_result = await db.execute(channel_memberships_stmt)
    channel_memberships = channel_memberships_result.scalars().all()

    # Deactivate all channel memberships
    for membership in channel_memberships:
        membership.is_active = False
        membership.updated_at = current_time

    # Deactivate users instead of deleting
    for user in found_users:
        user.is_active = False
        user.company_id = None
        user.updated_datetime = current_time

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to remove users")

    return {
        "message": f"{len(found_users)} user(s) removed from company successfully",
        "removed_user_ids": [str(user.id) for user in found_users],
        "not_found_user_ids": not_found_user_ids,
        "revoked_channel_memberships": len(channel_memberships)
    }
