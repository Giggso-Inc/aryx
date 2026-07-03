"""
Channel Access Authorization Utilities

This module provides helper functions to check if a user has access to a channel.
Access is granted if:
1. User is an active member of the channel (checked via gg_channel_members table)
   - Channel admins (role == "admin" in gg_channel_members) can view their channel
   - Channel users (role == "user" in gg_channel_members) can view their channel

Note: Super admin check is commented out for now. When needed, check gg_users table for is_root_admin (boolean column)

Author: Auto-generated
Date: 2025-01-XX
Version: 1.0.0
"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from fastapi import HTTPException, status

from app.models.user import User
from app.models.channel import Channel
from app.models.channel_member import ChannelMember


async def check_channel_access(
    db: AsyncSession,
    user: User,
    channel_id: str,
    raise_on_denied: bool = True
) -> bool:
    """
    Check if a user has access to a channel.
    
    Access is granted if:
    - User is an active member of the channel (checked via gg_channel_members table)
      - Channel admins (role == "admin" in gg_channel_members) can view
      - Channel users (role == "user" in gg_channel_members) can view
    
    Args:
        db: Database session
        user: Current user object
        channel_id: Channel ID to check access for (UUID string)
        raise_on_denied: If True, raises HTTPException on access denied. If False, returns False.
        
    Returns:
        bool: True if user has access, False otherwise (only if raise_on_denied=False)
        
    Raises:
        HTTPException: 404 if channel not found, 403 if access denied (if raise_on_denied=True)
    """
    import uuid
    
    # Validate channel_id format
    try:
        channel_uuid = uuid.UUID(channel_id)
    except ValueError:
        if raise_on_denied:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid channel ID format"
            )
        return False
    
    # TODO: Super admin check - commented out for now
    # When needed, check gg_users table for is_root_admin (boolean) to allow super admins to view all channels
    # Example:
    # if user.is_root_admin:  # Check is_root_admin column from gg_users table
    #     # Verify channel exists
    #     channel_stmt = select(Channel).where(Channel.id == channel_uuid)
    #     channel_result = await db.execute(channel_stmt)
    #     channel = channel_result.scalar_one_or_none()
    #     
    #     if not channel:
    #         if raise_on_denied:
    #             raise HTTPException(
    #                 status_code=status.HTTP_404_NOT_FOUND,
    #                 detail="Channel not found"
    #             )
    #         return False
    #     
    #     return True
    
    # Verify channel exists first
    channel_stmt = select(Channel).where(Channel.id == channel_uuid)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()
    
    if not channel:
        if raise_on_denied:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Channel not found"
            )
        return False
    
    # Check if user is an active member of the channel via gg_channel_members table
    # This checks both channel admins (role == "admin") and channel users (role == "user")
    member_stmt = select(ChannelMember).where(
        and_(
            ChannelMember.channel_id == channel_uuid,
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True
        )
    )
    member_result = await db.execute(member_stmt)
    member = member_result.scalar_one_or_none()
    
    if member:
        # User is an active member of the channel (admin or user role) - grant access
        return True
    
    # User is not a member of the channel - deny access
    if raise_on_denied:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You must be a member of this channel to access it."
        )
    return False


async def check_channel_access_by_thread(
    db: AsyncSession,
    user: User,
    thread_id: str,
    raise_on_denied: bool = True
) -> Optional[str]:
    """
    Check if a user has access to a channel via thread_id.
    
    This function gets the channel_id from the thread and then checks access.
    
    Args:
        db: Database session
        user: Current user object
        thread_id: Thread ID to get channel from (UUID string)
        raise_on_denied: If True, raises HTTPException on access denied. If False, returns None.
        
    Returns:
        Optional[str]: Channel ID if user has access, None otherwise (only if raise_on_denied=False)
        
    Raises:
        HTTPException: 404 if thread not found, 403 if access denied (if raise_on_denied=True)
    """
    import uuid
    from app.models.message import Thread
    
    # Validate thread_id format
    try:
        thread_uuid = uuid.UUID(thread_id)
    except ValueError:
        if raise_on_denied:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid thread ID format"
            )
        return None
    
    # Get thread to find channel_id
    thread_stmt = select(Thread).where(Thread.id == thread_uuid)
    thread_result = await db.execute(thread_stmt)
    thread = thread_result.scalar_one_or_none()
    
    if not thread:
        if raise_on_denied:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Thread not found"
            )
        return None
    
    # Check access to the channel
    has_access = await check_channel_access(
        db=db,
        user=user,
        channel_id=str(thread.channel_id),
        raise_on_denied=raise_on_denied
    )
    
    if has_access:
        return str(thread.channel_id)
    return None
