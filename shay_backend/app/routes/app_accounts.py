"""
AppAccount routes for managing app connections to channels
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
import uuid
import copy

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.app import App
from app.models.channel import Channel
from app.models.app_account import AppAccount
from app.models.giggso_vault import GiggsoVault
from app.schemas.app_account import (
    AppAccountCreate,
    AppAccountUpdate,
    AppAccountResponse,
    AppAccountList,
    AppAccountStats,
    AppConnectionRequest,
    UserMetadata
)
from app.core.config import settings
from app.services.vault_service import vault_service
from datetime import datetime
from typing import Dict, Any

router = APIRouter()
security = HTTPBearer()


def build_user_metadata(user: Optional[User]) -> Optional[UserMetadata]:
    """Build user_metadata (email_id, name, user_id, avatar_url) from User for app account response."""
    if not user:
        return None
    return UserMetadata(
        email_id=user.email_id,
        name=user.name,
        user_id=str(user.id),
        avatar_url=user.avatar_url
    )


def build_app_account_response(account: AppAccount, connected_user: Optional[User] = None) -> AppAccountResponse:
    """Build AppAccountResponse with optional user_metadata from the connected user."""
    return AppAccountResponse(
        id=str(account.id),
        app_id=str(account.app_id),
        channel_id=str(account.channel_id),
        connection_name=account.connection_name,
        connection_status=account.connection_status,
        connection_settings=account.connection_settings,
        webhook_url=account.webhook_url,
        callback_url=account.callback_url,
        is_active=account.is_active,
        auto_sync=account.auto_sync,
        sync_interval=account.sync_interval,
        connected_by=str(account.connected_by),
        user_metadata=build_user_metadata(connected_user),
        last_sync_at=account.last_sync_at,
        sync_status=account.sync_status,
        error_message=account.error_message,
        created_at=account.created_at,
        updated_at=account.updated_at
    )


def build_sharepoint_credentials_metadata(connection_settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build SharePoint credentials metadata for vault storage
    
    Args:
        connection_settings: Connection settings dictionary containing SharePoint credentials
        
    Returns:
        Dictionary containing SharePoint credentials formatted for vault storage
    """
    if not connection_settings or not isinstance(connection_settings, dict):
        return {}
    
    metadata = {
        "sharePointConfigured": True,
        "clientId": "",
        "clientSecret": "",
        "tenantId": "",
        "siteUrl": "",
        "refreshToken": "",
        "accessToken": "",
        "emailId": "",
        "scope": "",
        "oauthProvider": "microsoft",
        "connectionMethod": "oauth"
    }
    
    # Extract SharePoint credentials from connection_settings
    if connection_settings.get("client_id"):
        metadata["clientId"] = connection_settings.get("client_id")
    if connection_settings.get("client_secret"):
        metadata["clientSecret"] = connection_settings.get("client_secret")
    if connection_settings.get("tenant_id"):
        metadata["tenantId"] = connection_settings.get("tenant_id")
    if connection_settings.get("site_url"):
        metadata["siteUrl"] = connection_settings.get("site_url")
    if connection_settings.get("refresh_token"):
        metadata["refreshToken"] = connection_settings.get("refresh_token")
    if connection_settings.get("access_token"):
        metadata["accessToken"] = connection_settings.get("access_token")
    if connection_settings.get("email_id"):
        metadata["emailId"] = connection_settings.get("email_id")
    if connection_settings.get("scope"):
        metadata["scope"] = connection_settings.get("scope")
    if connection_settings.get("oauth_provider"):
        metadata["oauthProvider"] = connection_settings.get("oauth_provider")
    if connection_settings.get("connection_method"):
        metadata["connectionMethod"] = connection_settings.get("connection_method")
    
    return metadata


async def handle_app_account_vault_integration(
    credentials_metadata: Dict[str, Any],
    user_id: str,
    company_id: str,
    db: AsyncSession,
    required: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Handle vault integration for app account credentials
    
    Args:
        credentials_metadata: Credentials metadata dictionary to store in vault
        user_id: User ID
        company_id: Company ID
        db: Database session
        required: If True, vault failure will raise HTTPException. If False, returns None on failure.
        
    Returns:
        Dict with 'vault_unique_id' and 'giggso_vault_id' if successful, None if failed and not required
        
    Raises:
        HTTPException: If vault integration fails and vault is required
    """
    if not credentials_metadata:
        return None
    
    # Generate vault unique ID
    vault_unique_id = vault_service.generate_vault_unique_id(str(user_id), "app_account")
    
    # Save credentials to vault
    saved_vault_id = await vault_service.save_to_vault(credentials_metadata, vault_unique_id)
    
    # If vault save failed, handle based on required flag
    if not saved_vault_id:
        if required:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save credentials to vault. App account creation cannot proceed without secure storage."
            )
        else:
            return None
    
    # Create vault record if external vault save was successful
    try:
        base_label = f"app_{vault_unique_id[:8]}"
        vault_label = f"{base_label}_ok"
        
        vault_record = GiggsoVault(
            vault_unique_id=vault_unique_id,
            user_id=user_id,
            vault_label=vault_label,
            vault_type="app_account_credentials",
            company_id=company_id,
            created_by=user_id,
            created_datetime=datetime.utcnow()
        )
        
        db.add(vault_record)
        await db.flush()
        await db.commit()
        
        await db.refresh(vault_record)
        
        return {
            "vault_unique_id": vault_unique_id,
            "giggso_vault_id": vault_record.giggso_vault_id
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create vault record: {str(e)}"
        )


@router.post("/", response_model=AppAccountResponse)
async def create_app_account(
    app_account_data: AppAccountCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Create a new app account connection"""
    user = await get_current_user_required(request, db)
    
    # Verify app exists and is active
    app_stmt = select(App).where(
        and_(
            App.id == app_account_data.app_id,
            App.is_active == True
        )
    )
    app_result = await db.execute(app_stmt)
    app = app_result.scalar_one_or_none()
    
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App not found or not active"
        )
    
    # Verify channel exists and user has access
    channel_stmt = select(Channel).where(Channel.id == app_account_data.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()
    
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )
    
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this channel"
        )
    
    # Check if connection already exists
    existing_connection_stmt = select(AppAccount).where(
        and_(
            AppAccount.app_id == app_account_data.app_id,
            AppAccount.channel_id == app_account_data.channel_id,
            AppAccount.is_active == True
        )
    )
    existing_connection_result = await db.execute(existing_connection_stmt)
    existing_connection = existing_connection_result.scalar_one_or_none()
    
    if existing_connection:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="App is already connected to this channel"
        )
    
    # Process connection_settings - append Client ID and Secret for Jira
    connection_settings = app_account_data.connection_settings
    if connection_settings and isinstance(connection_settings, dict):
        # Create a copy to avoid modifying the original
        connection_settings = copy.deepcopy(connection_settings)
        provider = connection_settings.get("provider")
        if provider == "jira":
            connection_settings["client_id"] = settings.JIRA_CLIENT_ID
            connection_settings["client_secret"] = settings.JIRA_CLIENT_SECRET
    
    # Handle vault integration for SharePoint credentials
    if app.app_key and app.app_key.lower() in ['sharepoint', 'share_point']:
        if connection_settings and isinstance(connection_settings, dict):
            # Build SharePoint credentials metadata for vault
            credentials_metadata = build_sharepoint_credentials_metadata(connection_settings)
            
            if credentials_metadata:
                try:
                    vault_result = await handle_app_account_vault_integration(
                        credentials_metadata=credentials_metadata,
                        user_id=str(user.id),
                        company_id=str(channel.company_id),
                        db=db,
                        required=True
                    )
                    if vault_result:
                        # Remove sensitive credentials from connection_settings (keep only non-sensitive metadata)
                        sanitized_settings = {
                            "provider": connection_settings.get("provider"),
                            "oauth_provider": connection_settings.get("oauth_provider"),
                            "connection_method": connection_settings.get("connection_method"),
                            "email_id": connection_settings.get("email_id"),
                            "scope": connection_settings.get("scope")
                        }
                        connection_settings = sanitized_settings
                except HTTPException as e:
                    raise e
                except Exception as e:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to integrate with vault service: {str(e)}"
                    )
    
    # Create app account
    app_account = AppAccount(
        id=str(uuid.uuid4()),
        app_id=app_account_data.app_id,
        channel_id=app_account_data.channel_id,
        connected_by=user.id,
        connection_name=app_account_data.connection_name,
        connection_status=app_account_data.connection_status,
        connection_settings=connection_settings,
        webhook_url=app_account_data.webhook_url,
        callback_url=app_account_data.callback_url,
        is_active=app_account_data.is_active,
        auto_sync=app_account_data.auto_sync,
        sync_interval=app_account_data.sync_interval
    )
    
    db.add(app_account)
    await db.commit()
    await db.refresh(app_account)
    
    # Include user_metadata (email_id, name, user_id, avatar_url) for the user who created the connection
    return build_app_account_response(app_account, user)


@router.get("/", response_model=AppAccountList)
async def list_app_accounts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    app_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    connection_status: Optional[str] = None,
    is_active: Optional[bool] = None
):
    """List app accounts with filtering and pagination"""
    user = await get_current_user_required(request, db)
    
    # Build query with joins including User for user_metadata (email_id, name, user_id, avatar_url)
    query = select(AppAccount, User).join(App).join(Channel).join(User, AppAccount.connected_by == User.id)
    
    # Apply filters
    filters = []
    
    # Filter by user's company channels
    filters.append(Channel.company_id == user.company_id)
    
    if app_id:
        filters.append(AppAccount.app_id == app_id)
    
    if channel_id:
        filters.append(AppAccount.channel_id == channel_id)
    
    if connection_status:
        filters.append(AppAccount.connection_status == connection_status)
    
    if is_active is not None:
        filters.append(AppAccount.is_active == is_active)
    
    # Apply filters to query
    if filters:
        query = query.where(and_(*filters))
    
    # Get total count (from same filter set, without User join for count)
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar()
    
    # Apply pagination
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)
    
    # Execute query; each row is (AppAccount, User)
    result = await db.execute(query)
    rows = result.all()
    
    # Calculate pagination info
    pages = (total + size - 1) // size
    
    return AppAccountList(
        app_accounts=[build_app_account_response(account, connected_user) for account, connected_user in rows],
        total=total,
        page=page,
        size=size,
        pages=pages
    )


@router.get("/stats", response_model=AppAccountStats)
async def get_app_account_stats(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get app account statistics"""
    user = await get_current_user_required(request, db)
    
    # Get total connections for user's company
    total_connections_query = select(func.count(AppAccount.id)).join(Channel).where(
        Channel.company_id == user.company_id
    )
    total_connections_result = await db.execute(total_connections_query)
    total_connections = total_connections_result.scalar()
    
    # Get active connections
    active_connections_query = select(func.count(AppAccount.id)).join(Channel).where(
        and_(
            Channel.company_id == user.company_id,
            AppAccount.is_active == True
        )
    )
    active_connections_result = await db.execute(active_connections_query)
    active_connections = active_connections_result.scalar()
    
    # Get error connections
    error_connections_query = select(func.count(AppAccount.id)).join(Channel).where(
        and_(
            Channel.company_id == user.company_id,
            AppAccount.connection_status == "error"
        )
    )
    error_connections_result = await db.execute(error_connections_query)
    error_connections = error_connections_result.scalar()
    
    # Get unique apps connected
    apps_connected_query = select(AppAccount.app_id).join(Channel).where(
        Channel.company_id == user.company_id
    ).distinct()
    apps_connected_result = await db.execute(apps_connected_query)
    apps_connected = [row[0] for row in apps_connected_result.fetchall()]
    
    # Get unique channels connected
    channels_connected_query = select(AppAccount.channel_id).join(Channel).where(
        Channel.company_id == user.company_id
    ).distinct()
    channels_connected_result = await db.execute(channels_connected_query)
    channels_connected = [row[0] for row in channels_connected_result.fetchall()]
    
    # Get recent connections
    recent_connections_query = select(AppAccount).join(Channel).where(
        Channel.company_id == user.company_id
    ).order_by(AppAccount.created_at.desc()).limit(5)
    recent_connections_result = await db.execute(recent_connections_query)
    recent_connections = recent_connections_result.scalars().all()
    
    # Load connected users for user_metadata (batch by ids)
    connected_by_ids = [acc.connected_by for acc in recent_connections]
    users_stmt = select(User).where(User.id.in_(connected_by_ids))
    users_result = await db.execute(users_stmt)
    users_by_id = {u.id: u for u in users_result.scalars().all()}
    
    return AppAccountStats(
        total_connections=total_connections,
        active_connections=active_connections,
        error_connections=error_connections,
        apps_connected=apps_connected,
        channels_connected=channels_connected,
        recent_connections=[build_app_account_response(account, users_by_id.get(account.connected_by)) for account in recent_connections]
    )


@router.get("/{app_account_id}", response_model=AppAccountResponse)
async def get_app_account(
    app_account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific app account by ID"""
    user = await get_current_user_required(request, db)
    
    # Get app account with channel company_id to avoid lazy loading
    app_account_stmt = select(AppAccount, Channel.company_id).join(Channel).where(AppAccount.id == app_account_id)
    app_account_result = await db.execute(app_account_stmt)
    app_account_row = app_account_result.first()
    
    if not app_account_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App account not found"
        )
    
    app_account, channel_company_id = app_account_row
    
    # Check if user has access to this connection
    if channel_company_id != user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this app account"
        )
    
    # Load connected user for user_metadata
    connected_user_stmt = select(User).where(User.id == app_account.connected_by)
    connected_user_result = await db.execute(connected_user_stmt)
    connected_user = connected_user_result.scalar_one_or_none()
    
    return build_app_account_response(app_account, connected_user)


@router.put("/{app_account_id}", response_model=AppAccountResponse)
async def update_app_account(
    app_account_id: str,
    app_account_data: AppAccountUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Update an app account"""
    user = await get_current_user_required(request, db)
    
    # Get app account with channel company_id to avoid lazy loading
    app_account_stmt = select(AppAccount, Channel.company_id).join(Channel).where(AppAccount.id == app_account_id)
    app_account_result = await db.execute(app_account_stmt)
    app_account_row = app_account_result.first()
    
    if not app_account_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App account not found"
        )
    
    app_account, channel_company_id = app_account_row
    
    # Check if user has access to this connection
    if channel_company_id != user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this app account"
        )
    
    # Get app to check if it's SharePoint
    app_stmt = select(App).where(App.id == app_account.app_id)
    app_result = await db.execute(app_stmt)
    app = app_result.scalar_one_or_none()
    
    # Update app account fields
    update_data = app_account_data.dict(exclude_unset=True)
    
    # Process connection_settings - append Client ID and Secret for Jira if being updated
    if "connection_settings" in update_data:
        connection_settings = update_data["connection_settings"]
        if connection_settings and isinstance(connection_settings, dict):
            # Create a copy to avoid modifying the original
            connection_settings = copy.deepcopy(connection_settings)
            provider = connection_settings.get("provider")
            if provider == "jira":
                connection_settings["client_id"] = settings.JIRA_CLIENT_ID
                connection_settings["client_secret"] = settings.JIRA_CLIENT_SECRET
            
            # Handle vault integration for SharePoint credentials if being updated
            if app and app.app_key and app.app_key.lower() in ['sharepoint', 'share_point']:
                # Build SharePoint credentials metadata for vault
                credentials_metadata = build_sharepoint_credentials_metadata(connection_settings)
                
                if credentials_metadata:
                    try:
                        vault_result = await handle_app_account_vault_integration(
                            credentials_metadata=credentials_metadata,
                            user_id=str(user.id),
                            company_id=str(channel_company_id),
                            db=db,
                            required=True
                        )
                        if vault_result:
                            # Remove sensitive credentials from connection_settings
                            sanitized_settings = {
                                "provider": connection_settings.get("provider"),
                                "oauth_provider": connection_settings.get("oauth_provider"),
                                "connection_method": connection_settings.get("connection_method"),
                                "email_id": connection_settings.get("email_id"),
                                "scope": connection_settings.get("scope")
                            }
                            update_data["connection_settings"] = sanitized_settings
                    except HTTPException as e:
                        raise e
                    except Exception as e:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Failed to integrate with vault service: {str(e)}"
                        )
            else:
                update_data["connection_settings"] = connection_settings
    
    for field, value in update_data.items():
        setattr(app_account, field, value)
    
    await db.commit()
    await db.refresh(app_account)
    
    # Load connected user for user_metadata
    connected_user_stmt = select(User).where(User.id == app_account.connected_by)
    connected_user_result = await db.execute(connected_user_stmt)
    connected_user = connected_user_result.scalar_one_or_none()
    
    return build_app_account_response(app_account, connected_user)


@router.delete("/{app_account_id}")
async def delete_app_account(
    app_account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Delete an app account"""
    user = await get_current_user_required(request, db)
    
    # Get app account with channel company_id to avoid lazy loading
    from sqlalchemy import select, and_
    app_account_stmt = select(AppAccount, Channel.company_id).join(Channel).where(AppAccount.id == app_account_id)
    app_account_result = await db.execute(app_account_stmt)
    app_account_row = app_account_result.first()
    
    if not app_account_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App account not found"
        )
    
    app_account, channel_company_id = app_account_row
    
    # Check if user has access to this connection
    if channel_company_id != user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this app account"
        )
    
    # Delete app account
    await db.delete(app_account)
    await db.commit()
    
    return {"message": "App account deleted successfully"}


@router.post("/connect", response_model=AppAccountResponse)
async def connect_app_to_channel(
    connection_data: AppConnectionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Connect an app to a channel"""
    user = await get_current_user_required(request, db)
    
    # Verify app exists and is active
    app_stmt = select(App).where(
        and_(
            App.id == connection_data.app_id,
            App.is_active == True
        )
    )
    app_result = await db.execute(app_stmt)
    app = app_result.scalar_one_or_none()
    
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App not found or not active"
        )
    
    # Verify channel exists and user has access
    channel_stmt = select(Channel).where(Channel.id == connection_data.channel_id)
    channel_result = await db.execute(channel_stmt)
    channel = channel_result.scalar_one_or_none()
    
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )
    
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this channel"
        )
    
    # Check if connection already exists
    existing_connection_stmt = select(AppAccount).where(
        and_(
            AppAccount.app_id == connection_data.app_id,
            AppAccount.channel_id == connection_data.channel_id,
            AppAccount.is_active == True
        )
    )
    existing_connection_result = await db.execute(existing_connection_stmt)
    existing_connection = existing_connection_result.scalar_one_or_none()
    
    if existing_connection:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="App is already connected to this channel"
        )
    
    # Process connection_settings - append Client ID and Secret for Jira
    connection_settings = connection_data.connection_settings
    if connection_settings and isinstance(connection_settings, dict):
        # Create a copy to avoid modifying the original
        connection_settings = copy.deepcopy(connection_settings)
        provider = connection_settings.get("provider")
        if provider == "jira":
            connection_settings["client_id"] = settings.JIRA_CLIENT_ID
            connection_settings["client_secret"] = settings.JIRA_CLIENT_SECRET
    
    # Handle vault integration for SharePoint credentials
    if app.app_key and app.app_key.lower() in ['sharepoint', 'share_point']:
        if connection_settings and isinstance(connection_settings, dict):
            # Build SharePoint credentials metadata for vault
            credentials_metadata = build_sharepoint_credentials_metadata(connection_settings)
            
            if credentials_metadata:
                try:
                    vault_result = await handle_app_account_vault_integration(
                        credentials_metadata=credentials_metadata,
                        user_id=str(user.id),
                        company_id=str(channel.company_id),
                        db=db,
                        required=True
                    )
                    if vault_result:
                        # Remove sensitive credentials from connection_settings (keep only non-sensitive metadata)
                        sanitized_settings = {
                            "provider": connection_settings.get("provider"),
                            "oauth_provider": connection_settings.get("oauth_provider"),
                            "connection_method": connection_settings.get("connection_method"),
                            "email_id": connection_settings.get("email_id"),
                            "scope": connection_settings.get("scope")
                        }
                        connection_settings = sanitized_settings
                except HTTPException as e:
                    raise e
                except Exception as e:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to integrate with vault service: {str(e)}"
                    )
    
    # Create app account
    app_account = AppAccount(
        id=str(uuid.uuid4()),
        app_id=connection_data.app_id,
        channel_id=connection_data.channel_id,
        connected_by=user.id,
        connection_name=connection_data.connection_name,
        connection_status="active",
        connection_settings=connection_settings,
        webhook_url=connection_data.webhook_url,
        callback_url=connection_data.callback_url,
        is_active=True,
        auto_sync=connection_data.auto_sync,
        sync_interval=connection_data.sync_interval
    )
    
    db.add(app_account)
    await db.commit()
    await db.refresh(app_account)
    
    # Include user_metadata (email_id, name, user_id, avatar_url) for the user who connected
    return build_app_account_response(app_account, user)