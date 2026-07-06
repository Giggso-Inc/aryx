"""
Company routes for CRUD operations and management.

This module provides API endpoints for company management operations including
company creation, updates, user invitations, and company statistics. It handles
company-user relationships and ensures proper access control through authentication.

Author: Karthick Chandrasekar
Date: 2025-08-14
Version: 1.0.0
"""

# Type hinting support for function parameters and return values
from typing import List, Optional

# FastAPI framework imports for routing, HTTP handling, and dependency injection
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query

# SQLAlchemy async support for database operations
from sqlalchemy.ext.asyncio import AsyncSession

# SQLAlchemy query building and logical operators
from sqlalchemy import select, func, and_, or_

# Database connection dependency injection
from app.core.database import get_db

# Authentication utilities for company ID generation
from app.core.auth import generate_company_id

# Authentication middleware for user verification
from app.middleware.auth_middleware import get_current_user_required

# Database models for user, company, and invitation entities
from app.models.user import User
from app.models.company import Company
from app.models.invitation import Invitation

# Pydantic schemas for request/response validation and serialization
from app.schemas.company import (
    CompanyCreate,
    CompanyUpdate,
    CompanyResponse,
    CompanyList,
    CompanyStats,
    CompanyProfileUpdate,
    UserInvitation,
    UserInvitationResponse,
    InvitationAccept,
    InvitationListResponse,
    InvitedByUser
)

router = APIRouter()


@router.get("/test", response_model=dict)
async def test_models():
    """Test endpoint to check if models are working"""
    try:
        from app.models.workspace import Workspace
        from app.models.message import Message
        from app.models.attachment import Attachment
        return {"status": "success", "message": "Models imported successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/", response_model=CompanyList)
async def list_companies(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None
):
    """List companies (admin only)"""
    user = await get_current_user_required(request)
    
    # Only admins can list all companies
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can list all companies"
        )
    
    # Build query
    query = select(Company)
    
    if search:
        query = query.where(
            Company.name.ilike(f"%{search}%") | 
            Company.domain.ilike(f"%{search}%")
        )
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # Pagination
    query = query.offset((page - 1) * size).limit(size)
    
    # Execute query
    result = await db.execute(query)
    companies = result.scalars().all()
    
    return CompanyList(
        companies=[CompanyResponse.from_orm(company) for company in companies],
        total=total,
        page=page,
        size=size
    )


@router.get("/my", response_model=CompanyResponse)
async def get_my_company(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get current user's company"""
    user = await get_current_user_required(request)
    
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not associated with any company"
        )
    
    stmt = select(Company).where(Company.id == user.company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    return CompanyResponse.from_orm(company)


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get company by ID"""
    user = await get_current_user_required(request)
    
    # Check if user can access this company
    if user.company_id != company_id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    stmt = select(Company).where(Company.id == company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    return CompanyResponse.from_orm(company)


@router.put("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: str,
    company_update: CompanyUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Update company (admin only)"""
    user = await get_current_user_required(request)
    
    # Check if user can update this company
    if user.company_id != company_id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    stmt = select(Company).where(Company.id == company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    # Update company fields
    update_data = company_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(company, field, value)
    
    await db.commit()
    await db.refresh(company)
    
    return CompanyResponse.from_orm(company)


@router.get("/{company_id}/stats", response_model=CompanyStats)
async def get_company_stats(
    company_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get company statistics"""
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
    
    # Get statistics
    # Note: This is a simplified version. In a real app, you'd want to optimize these queries
    from app.models.workspace import Workspace
    from app.models.message import Message
    from app.models.attachment import Attachment
    
    try:
        # Count users
        user_count_stmt = select(func.count(User.id)).where(User.company_id == company_id)
        user_count_result = await db.execute(user_count_stmt)
        total_users = user_count_result.scalar() or 0
        
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


@router.post("/{company_id}/invite", response_model=UserInvitationResponse)
async def invite_user(
    company_id: str,
    invitation: UserInvitation,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Invite a user to the company"""
    user = await get_current_user_required(request)
    
    # Check if user can invite to this company
    if user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only invite users to your own company"
        )
    
    # Check if user is admin or has invite permissions
    if user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to invite users"
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
    
    # Check if user already exists
    existing_user_stmt = select(User).where(User.email_id == invitation.email)
    existing_user_result = await db.execute(existing_user_stmt)
    existing_user = existing_user_result.scalar_one_or_none()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )
    
    # Check if invitation already exists
    existing_invitation_stmt = select(Invitation).where(
        and_(
            Invitation.email == invitation.email,
            Invitation.company_id == company_id,
            Invitation.status == "pending"
        )
    )
    existing_invitation_result = await db.execute(existing_invitation_stmt)
    existing_invitation = existing_invitation_result.scalar_one_or_none()
    
    if existing_invitation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation already exists for this email"
        )
    
    # Create invitation
    new_invitation = Invitation.create_invitation(
        email=invitation.email,
        role=invitation.role,
        company_id=company_id,
        invited_by=user.id,
        message=invitation.message
    )
    
    db.add(new_invitation)
    await db.commit()
    await db.refresh(new_invitation)
    
    # Create InvitedByUser object from the current user (include avatar_url for UI)
    invited_by_obj = InvitedByUser(
        userId=user.id,
        userEmail=user.email_id,
        username=user.name,
        avatar_url=user.avatar_url,
        role=user.role
    )
    
    # Create UserInvitationResponse with invited_by object
    return UserInvitationResponse(
        id=new_invitation.id,
        email=new_invitation.email,
        role=new_invitation.role,
        company_id=new_invitation.company_id,
        invited_by=invited_by_obj,
        status=new_invitation.status,
        message=new_invitation.message,
        created_at=new_invitation.created_at,
        expires_at=new_invitation.expires_at
    )


@router.get("/{company_id}/invitations", response_model=InvitationListResponse)
async def list_invitations(
    company_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    search: Optional[str] = Query(None, description="Search term for filtering by email"),
    role: Optional[str] = Query(None, description="Filter by role (e.g., admin, user, manager)"),
    sort_by: str = Query("email", description="Sort by field: email, created_at"),
    sort_order: str = Query("asc", description="Sort order: asc or desc")
):
    """
    List company invitations with pagination, search, role filtering, and sorting.
    
    This endpoint retrieves a paginated list of pending invitations for a specific company.
    It supports searching by email, filtering by role, sorting by email or created_at, 
    and provides comprehensive pagination metadata.
    
    Args:
        company_id: UUID of the company to list invitations from
        request: FastAPI request object for authentication
        db: Database session dependency
        page: Page number for pagination (default: 1)
        size: Number of items per page (default: 10, max: 100)
        search: Optional search term for filtering by email
        role: Optional role filter (e.g., admin, user, manager)
        sort_by: Field to sort by (email, created_at) - default: email
        sort_order: Sort direction (asc or desc) - default: asc
    
    Returns:
        InvitationListResponse: List of pending invitations with pagination metadata
        
    Raises:
        HTTPException: 403 if access denied, 400 if invalid sort parameters
    """
    user = await get_current_user_required(request)
    
    # Check if user can view invitations for this company
    if user.company_id != company_id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Build base query with status filter for pending invitations
    # Step 1: Deduplicate by email first (get most recent invitation per email)
    # Step 2: Then apply role filter to the deduplicated results
    # Base conditions for deduplication (without role filter)
    dedup_conditions = [
        Invitation.company_id == company_id,
        Invitation.status == "pending"
    ]
    
    # Apply search filter if provided (for deduplication)
    if search:
        dedup_conditions.append(Invitation.email.ilike(f"%{search}%"))
    
    # Create subquery to get the most recent invitation per email (deduplication)
    dedup_subquery = (
        select(
            Invitation.id,
            Invitation.role,
            func.row_number()
            .over(
                partition_by=Invitation.email,
                order_by=Invitation.created_at.desc()
            )
            .label("rn")
        )
        .where(and_(*dedup_conditions))
    ).subquery()
    
    # Get only the most recent invitation per email (row_number = 1)
    distinct_invitation_ids_query = select(dedup_subquery.c.id).where(dedup_subquery.c.rn == 1)
    
    # Apply role filter AFTER deduplication if provided
    if role:
        distinct_invitation_ids_query = distinct_invitation_ids_query.where(dedup_subquery.c.role == role)
    
    # Build base query using the distinct invitation IDs (already filtered by role if provided)
    base_query = select(Invitation).where(Invitation.id.in_(distinct_invitation_ids_query))
    
    # Get total count - ALWAYS count overall distinct emails (without role filter)
    # This should not change based on filters
    total_count_subquery = (
        select(
            Invitation.email,
            func.row_number()
            .over(
                partition_by=Invitation.email,
                order_by=Invitation.created_at.desc()
            )
            .label("rn")
        )
        .where(
            and_(
                Invitation.company_id == company_id,
                Invitation.status == "pending"
            )
        )
    ).subquery()
    
    # Count distinct emails (overall total, not filtered)
    count_query = select(func.count()).select_from(
        total_count_subquery
    ).where(total_count_subquery.c.rn == 1)
    
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Validate sort_by field
    allowed_sort_fields = ["email", "created_at"]
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
    
    # Apply sorting
    if sort_by == "email":
        if sort_order.lower() == "desc":
            data_query = base_query.order_by(Invitation.email.desc())
        else:
            data_query = base_query.order_by(Invitation.email.asc())
    else:  # Default: sort by created_at
        if sort_order.lower() == "desc":
            data_query = base_query.order_by(Invitation.created_at.desc())
        else:
            data_query = base_query.order_by(Invitation.created_at.asc())
    
    # Calculate pagination metadata
    total_pages = (total + size - 1) // size if total > 0 else 0  # Ceiling division
    has_next = page < total_pages
    has_previous = page > 1
    
    # Apply pagination
    data_query = data_query.offset((page - 1) * size).limit(size)
    
    # Execute query
    result = await db.execute(data_query)
    invitations = result.scalars().all()
    
    # Collect unique user IDs from invitations to fetch user data
    invited_by_user_ids = list(set([invitation.invited_by for invitation in invitations]))
    
    # Fetch all users who sent invitations in a single query
    users_query = select(User).where(User.id.in_(invited_by_user_ids))
    users_result = await db.execute(users_query)
    users = users_result.scalars().all()
    
    # Create a mapping of user_id -> user object for quick lookup
    users_map = {user.id: user for user in users}
    
    # Build invitation responses with invited_by user objects
    invitation_responses = []
    for invitation in invitations:
        # Get the user who sent the invitation
        invited_by_user = users_map.get(invitation.invited_by)
        
        # Create InvitedByUser object (include avatar_url for Admin Hub Invitations tab)
        if invited_by_user:
            invited_by_obj = InvitedByUser(
                userId=invited_by_user.id,
                userEmail=invited_by_user.email_id,
                username=invited_by_user.name,
                avatar_url=invited_by_user.avatar_url,
                role=invited_by_user.role
            )
        else:
            # Fallback if user not found (shouldn't happen, but handle gracefully)
            invited_by_obj = InvitedByUser(
                userId=invitation.invited_by,
                userEmail=None,
                username=None,
                avatar_url=None,
                role=None
            )
        
        # Create UserInvitationResponse with invited_by object
        invitation_response = UserInvitationResponse(
            id=invitation.id,
            email=invitation.email,
            role=invitation.role,
            company_id=invitation.company_id,
            invited_by=invited_by_obj,
            status=invitation.status,
            message=invitation.message,
            created_at=invitation.created_at,
            expires_at=invitation.expires_at
        )
        invitation_responses.append(invitation_response)
    
    return InvitationListResponse(
        invitations=invitation_responses,
        total=total,
        page=page,
        size=size,
        total_pages=total_pages,
        has_next=has_next,
        has_previous=has_previous
    )


@router.post("/invitations/{invitation_id}/accept", response_model=dict)
async def accept_invitation(
    invitation_id: str,
    accept_data: InvitationAccept,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Accept an invitation"""
    # Get invitation
    stmt = select(Invitation).where(Invitation.id == invitation_id)
    result = await db.execute(stmt)
    invitation = result.scalar_one_or_none()
    
    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found"
        )
    
    if not invitation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation is not valid or has expired"
        )
    
    # Check if user already exists
    existing_user_stmt = select(User).where(User.email_id == invitation.email)
    existing_user_result = await db.execute(existing_user_stmt)
    existing_user = existing_user_result.scalar_one_or_none()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )
    
    # Create user
    from app.core.auth import generate_user_id
    
    user = User(
        id=generate_user_id(),
        name=accept_data.name,
        email_id=invitation.email_id,
        role=invitation.role,
        company_id=invitation.company_id
    )
    
    # Mark invitation as accepted
    invitation.accept()
    
    db.add(user)
    await db.commit()
    
    return {
        "message": "Invitation accepted successfully",
                        "user_id": str(user.id),
        "company_id": str(user.company_id) if user.company_id else None
    } 