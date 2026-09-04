"""
Datasource upload / from-upload endpoints.
"""

import os
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.company import Company
from app.models.datasource import Datasource
from app.routes.aryx import (
    _resolve_aryx_workspace_id as _resolve_aryx_workspace_id_for_datasources,
    call_aryx_docs_read,
)
from app.routes.workspaces import _get_workspace_or_404
from app.schemas.datasource import (
    DatasourceBulkResponse,
    DatasourceFromUploadBulk,
    DatasourceResponse,
    FileUploadBulkResponse,
    FileUploadResponse,
)
from app.services.file_storage import generate_structured_path, get_file_storage_service
from app.services.vault_data_builder import enhance_datasource_metadata
from app.utils.file_validation import validate_file_content
from app.utils.permissions import require_active_workspace_role

from ._shared import (
    clean_metadata,
    generate_datasource_metadata,
    handle_vault_integration,
    sanitize_datasource_metadata,
)

router = APIRouter()


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    isValidationRequired: bool = Form(True),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> FileUploadResponse:
    """Upload a single file to the system"""
    user = await get_current_user_required(request)
    
    # Validate file
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File name is required"
        )
    
    # Get company information
    company_stmt = select(Company).where(Company.id == user.company_id)
    company_result = await db.execute(company_stmt)
    company = company_result.scalar_one_or_none()
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    # Get file storage service
    storage_service = get_file_storage_service()
    
    try:
        # Read file content
        file_content = await file.read()
        
        # Validate file content before uploading (if validation is required)
        if isValidationRequired and not validate_file_content(file_content, file.filename):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File validation failed - no valid section headers found"
            )
        
        # Generate structured path
        file_extension = os.path.splitext(file.filename)[1]
        base_filename = os.path.splitext(file.filename)[0]
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        # Use structured path for datasource files
        structured_path = generate_structured_path(
            company_name=company.name,
            company_id=str(company.id),
            file_type="datasource",
            original_filename=file.filename,
            base_filename=base_filename,
            file_extension=file_extension,
            current_date=current_date
        )
        
        # Upload file with structured path
        upload_result = await storage_service.upload_file(
            file_content=file_content,
            destination_path=structured_path,
            original_filename=file.filename
        )
        
        return FileUploadResponse(
            filename=file.filename,
            storage_path=upload_result["storage_path"],
            file_url=upload_result["file_url"],
            file_size=len(file_content),
            file_type=file.content_type or "application/octet-stream",
            provider=upload_result["provider"]
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )

@router.post("/upload/bulk", response_model=FileUploadBulkResponse)
async def upload_files_bulk(
    files: List[UploadFile] = File(...),
    isValidationRequired: bool = Form(True),
    kind: Optional[str] = Form(None),
    workspace_id: Optional[str] = Form(None),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> FileUploadBulkResponse:
    """Upload multiple files to the system.

    Additive Aryx integration: pass kind="aryx" together with workspace_id
    (a Shay workspace UUID already bridged to Aryx) to ALSO start Aryx
    knowledge-graph ingestion for each successfully-uploaded file, using the
    same bytes already read for the storage upload — no re-read, no
    duplicate network transfer of the file. This runs ALONGSIDE the existing
    storage upload below, never instead of it: the storage-upload result is
    always computed and appended first, exactly as before; the Aryx result
    (or a per-file error) is then attached as an additional aryx_ingestion
    key on that same entry.

    Omitting kind (or any value other than "aryx") is byte-for-byte
    identical to the endpoint's behavior before this change — no existing
    caller is affected.
    """
    user = await get_current_user_required(request)

    # Get company information
    company_stmt = select(Company).where(Company.id == user.company_id)
    company_result = await db.execute(company_stmt)
    company = company_result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # --- Additive Aryx setup — resolved once for the whole batch, only when
    # kind="aryx" was actually requested. Any failure here becomes a per-file
    # aryx_ingestion.error below rather than a hard failure of the upload
    # (which must still succeed for callers not opting into this feature).
    aryx_workspace_id: Optional[int] = None
    aryx_setup_error: Optional[str] = None
    if kind == "aryx":
        if not workspace_id:
            aryx_setup_error = "workspace_id is required when kind='aryx'"
        else:
            try:
                target_workspace = await _get_workspace_or_404(db, workspace_id)
                await require_active_workspace_role(db, user.id, uuid.UUID(str(target_workspace.id)))
                aryx_workspace_id = await _resolve_aryx_workspace_id_for_datasources(workspace_id)
            except HTTPException as exc:
                aryx_setup_error = str(exc.detail)

    # Get file storage service
    storage_service = get_file_storage_service()

    uploaded_files = []
    failed_files = []

    for file in files:
        try:
            # Validate file
            if not file.filename:
                failed_files.append({
                    "filename": "unknown",
                    "error": "File name is required"
                })
                continue

            # Read file content
            file_content = await file.read()

            # Validate file content before uploading (if validation is required)
            if isValidationRequired and not validate_file_content(file_content, file.filename):
                failed_files.append({
                    "filename": file.filename,
                    "error": "File validation failed - no valid section headers found"
                })
                continue

            # Generate structured path
            file_extension = os.path.splitext(file.filename)[1]
            base_filename = os.path.splitext(file.filename)[0]
            current_date = datetime.now().strftime("%Y-%m-%d")

            # Use structured path for datasource files
            structured_path = generate_structured_path(
                company_name=company.name,
                company_id=str(company.id),
                file_type="datasource",
                original_filename=file.filename,
                base_filename=base_filename,
                file_extension=file_extension,
                current_date=current_date
            )

            # Upload file with structured path
            upload_result = await storage_service.upload_file(
                file_content=file_content,
                destination_path=structured_path,
                original_filename=file.filename
            )

            uploaded_entry = {
                "filename": file.filename,
                "storage_path": upload_result["storage_path"],
                "file_url": upload_result["file_url"],
                "file_size": len(file_content),
                "file_type": file.content_type or "application/octet-stream",
                "provider": upload_result["provider"]
            }

            # --- Additive: start Aryx ingestion for this file using the
            # bytes already read above. Never touches uploaded_entry's
            # existing keys — only adds aryx_ingestion.
            if kind == "aryx":
                if aryx_setup_error:
                    uploaded_entry["aryx_ingestion"] = {"error": aryx_setup_error}
                else:
                    try:
                        aryx_result = await call_aryx_docs_read(
                            aryx_workspace_id,
                            [(file.filename, file_content, file.content_type)],
                        )
                        uploaded_entry["aryx_ingestion"] = {
                            "discovery_id": aryx_result.get("discovery_id"),
                            "status": "queued",
                        }
                    except HTTPException as exc:
                        uploaded_entry["aryx_ingestion"] = {"error": str(exc.detail)}

            uploaded_files.append(uploaded_entry)

        except Exception as e:
            failed_files.append({
                "filename": file.filename,
                "error": str(e)
            })

    return FileUploadBulkResponse(
        uploaded_files=uploaded_files,
        failed_files=failed_files,
        total_uploaded=len(uploaded_files),
        total_failed=len(failed_files)
    )

@router.post("/from-upload", response_model=DatasourceResponse)
async def create_datasource_from_upload(
    name: Optional[str] = Form(None),
    channel_id: str = Form(...),
    log_type: Optional[str] = Form(None),
    datasource_metadata: Optional[str] = Form(None),  # JSON string
    file: UploadFile = File(...),
    isValidationRequired: bool = Form(True),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> DatasourceResponse:
    """Create a datasource from uploaded file"""
    user = await get_current_user_required(request)
    
    # Parse datasource_metadata if provided
    parsed_metadata = None
    if datasource_metadata:
        try:
            import json
            parsed_metadata = json.loads(datasource_metadata)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON in datasource_metadata"
            )
    
    # Get channel
    stmt = select(Channel).where(Channel.id == channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()
    
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )
    
    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to channel"
        )
    
    # Check for duplicate datasource in the same channel (if name provided)
    if name:
        existing_datasource_stmt = select(Datasource).where(
            and_(
                Datasource.name == name,
                Datasource.channel_id == channel_id
            )
        )
        existing_datasource_result = await db.execute(existing_datasource_stmt)
        existing_datasource = existing_datasource_result.scalars().first()
        
        if existing_datasource:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Datasource with name '{name}' already exists in this channel"
            )
    
    # Validate file
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File name is required"
        )
    
    # Get company information
    company_stmt = select(Company).where(Company.id == user.company_id)
    company_result = await db.execute(company_stmt)
    company = company_result.scalar_one_or_none()
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    # Get file storage service
    storage_service = get_file_storage_service()
    
    try:
        # Read file content
        file_content = await file.read()
        
        # Validate file content before uploading (if validation is required)
        if isValidationRequired and not validate_file_content(file_content, file.filename):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File validation failed - no valid section headers found"
            )
        
        # Generate structured path
        file_extension = os.path.splitext(file.filename)[1]
        base_filename = os.path.splitext(file.filename)[0]
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        # Use structured path for datasource files
        structured_path = generate_structured_path(
            company_name=company.name,
            company_id=str(company.id),
            file_type="datasource",
            original_filename=file.filename,
            base_filename=base_filename,
            file_extension=file_extension,
            current_date=current_date
        )
        
        # Upload file with structured path
        upload_result = await storage_service.upload_file(
            file_content=file_content,
            destination_path=structured_path,
            original_filename=file.filename
        )
        
        # Auto-generate name from filename if not provided
        datasource_name = name
        if not datasource_name:
            # Remove extension and replace underscores/hyphens with spaces
            base_filename = os.path.splitext(file.filename)[0]
            datasource_name = base_filename.replace('_', ' ').replace('-', ' ').title()
        
        # Determine storage type and provider from upload result
        storage_type = "cloud" if upload_result["provider"] in ["aws", "azure", "oracle"] else "local"
        provider = upload_result["provider"]
        
        # Build config with provider-specific details
        config = {
            "file_path": upload_result["storage_path"],
            "original_filename": file.filename
        }
        
        # Add provider-specific configuration details
        if provider == "aws":
            config.update({
                "bucket_name": upload_result.get("bucket_name"),
                "region": upload_result.get("region")
            })
        elif provider == "azure":
            config.update({
                "container_name": upload_result.get("container_name"),
                "account_name": upload_result.get("account_name")
            })
        elif provider == "oracle":
            config.update({
                "bucket_name": upload_result.get("bucket_name"),
                "namespace": upload_result.get("namespace"),
                "compartment_id": upload_result.get("compartment_id")
            })
        
        # Generate metadata structure
        metadata = generate_datasource_metadata(
            filename=file.filename,
            storage_type=storage_type,
            channel_id=channel_id,
            workspace_id=str(channel.workspace_id),
            user_id=str(user.id),
            file_size=len(file_content),
            file_type=file.content_type or "application/octet-stream",
            provider=provider,
            app_type=None,
            log_type=log_type,
            config=config,
            file_url=upload_result["file_url"]
        )
        
        # Clean the metadata to remove null, empty, and default values
        cleaned_metadata = clean_metadata(metadata)
        
        # Enhance metadata with vault-specific fields AFTER cleaning
        from app.services.vault_data_builder import enhance_datasource_metadata
        
        enhanced_metadata = await enhance_datasource_metadata(
            existing_metadata=cleaned_metadata,
            storage_type=storage_type,
            provider=provider,
            config=config,
            db=db,
            channel_id=channel_id
        )
        
        # Handle vault integration for datasource metadata
        vault_unique_id = None
        if enhanced_metadata:
            # Vault integration is REQUIRED for ALL datasource types to ensure data security
            # This includes both cloud datasources (with sensitive credentials) and local files
            vault_required = True
            
            try:
                vault_result = await handle_vault_integration(
                    datasource_metadata=enhanced_metadata,
                    user_id=str(user.id),
                    company_id=str(channel.company_id),
                    db=db,
                    required=vault_required
                )
                vault_unique_id = vault_result["vault_unique_id"] if vault_result else None
                giggso_vault_id = vault_result["giggso_vault_id"] if vault_result else None
            except HTTPException as e:
                # Re-raise HTTPException for required vault integration
                raise e
            except Exception as e:
                # For unexpected errors, log and fail
                print(f"Unexpected error during vault integration: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to integrate with vault service"
                )
        
        # Store enhanced metadata directly in database (with vault integration for backup)
        final_metadata = enhanced_metadata.copy()
        if vault_unique_id:
            final_metadata["vault_unique_id"] = str(vault_unique_id)
        
        # Create datasource
        datasource = Datasource(
            id=str(uuid.uuid4()),
            name=datasource_name,
            filename=file.filename,
            storage_type=storage_type,
            provider=provider,
            app_type=None,
            log_type=log_type,
            config=config,
            datasource_metadata=final_metadata,
            file_size=len(file_content),
            file_type=file.content_type or "application/octet-stream",
            file_url=upload_result["file_url"],
            channel_id=channel_id,
            added_by=user.id,
            giggso_vault_id=giggso_vault_id  # Set the vault ID
        )
        
        db.add(datasource)
        await db.commit()
        await db.refresh(datasource)
        
        return DatasourceResponse(
            id=str(datasource.id),
            name=datasource.name,
            filename=datasource.filename,
            storage_type=datasource.storage_type,
            provider=datasource.provider,
            app_type=datasource.app_type,
            config=datasource.config,
            datasource_metadata=sanitize_datasource_metadata(datasource.datasource_metadata),
            giggso_vault_id=str(datasource.giggso_vault_id) if datasource.giggso_vault_id else None,
            file_size=datasource.file_size,
            file_type=datasource.file_type,
            file_url=datasource.file_url,
            channel_id=str(datasource.channel_id),
            workspace_id=str(channel.workspace_id),
            company_id=str(channel.company_id),
            added_by=str(datasource.added_by),
            is_active=datasource.is_active,
            is_connected=datasource.is_connected,
            is_processed=datasource.is_processed,
            processing_status=datasource.processing_status,
            error_message=datasource.error_message,
            last_processed_at=datasource.last_processed_at,
            processing_time=datasource.processing_time,
            record_count=datasource.record_count,
            created_at=datasource.created_at,
            updated_at=datasource.updated_at
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create datasource from upload: {str(e)}"
        )

@router.post("/from-upload/bulk", response_model=DatasourceBulkResponse)
async def create_datasources_from_upload_bulk(
    datasources_data: DatasourceFromUploadBulk,
    files: List[UploadFile] = File(...),
    isValidationRequired: bool = Form(True),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> DatasourceBulkResponse:
    """Create multiple datasources from uploaded files"""
    user = await get_current_user_required(request)
    
    created_datasources = []
    failed_datasources = []
    
    # Validate that number of files matches number of datasources
    if len(files) != len(datasources_data.datasources):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Number of files must match number of datasources"
        )
    
    # Get company information
    company_stmt = select(Company).where(Company.id == user.company_id)
    company_result = await db.execute(company_stmt)
    company = company_result.scalar_one_or_none()
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    # Get file storage service
    storage_service = get_file_storage_service()
    
    for i, (datasource_data, file) in enumerate(zip(datasources_data.datasources, files)):
        try:
            # Get channel
            stmt = select(Channel).where(Channel.id == datasource_data.channel_id)
            result = await db.execute(stmt)
            channel = result.scalar_one_or_none()
            
            if not channel:
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "Channel not found"
                })
                continue
            
            # Check permissions
            if not channel.is_accessible_by_user(user.company_id, user.role):
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "Access denied to channel"
                })
                continue
            
            # Check for duplicate datasource in the same channel
            existing_datasource_stmt = select(Datasource).where(
                and_(
                    Datasource.name == datasource_data.name,
                    Datasource.channel_id == datasource_data.channel_id
                )
            )
            existing_datasource_result = await db.execute(existing_datasource_stmt)
            existing_datasource = existing_datasource_result.scalars().first()
            
            if existing_datasource:
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": f"Datasource with name '{datasource_data.name}' already exists in this channel"
                })
                continue
            
            # Validate file
            if not file.filename:
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "File name is required"
                })
                continue
            
            # Read file content
            file_content = await file.read()
            
            # Validate file content before uploading (if validation is required)
            if isValidationRequired and not validate_file_content(file_content, file.filename):
                failed_datasources.append({
                    "name": datasource_data.name,
                    "error": "File validation failed - no valid section headers found"
                })
                continue
            
            # Generate structured path
            file_extension = os.path.splitext(file.filename)[1]
            base_filename = os.path.splitext(file.filename)[0]
            current_date = datetime.now().strftime("%Y-%m-%d")
            
            # Use structured path for datasource files
            structured_path = generate_structured_path(
                company_name=company.name,
                company_id=str(company.id),
                file_type="datasource",
                original_filename=file.filename,
                base_filename=base_filename,
                file_extension=file_extension,
                current_date=current_date
            )
            
            # Upload file with structured path
            upload_result = await storage_service.upload_file(
                file_content=file_content,
                destination_path=structured_path,
                original_filename=file.filename
            )
            
            # Auto-generate name from filename if not provided
            datasource_name = datasource_data.name
            if not datasource_name:
                # Remove extension and replace underscores/hyphens with spaces
                base_filename = os.path.splitext(file.filename)[0]
                datasource_name = base_filename.replace('_', ' ').replace('-', ' ').title()
            
            # Determine storage type and provider from upload result
            storage_type = "cloud" if upload_result["provider"] in ["aws", "azure", "oracle"] else "local"
            provider = upload_result["provider"]
            
            # Build config with provider-specific details
            config = {
                "file_path": upload_result["storage_path"],
                "original_filename": file.filename
            }
            
            # Add provider-specific configuration details
            if provider == "aws":
                config.update({
                    "bucket_name": upload_result.get("bucket_name"),
                    "region": upload_result.get("region")
                })
            elif provider == "azure":
                config.update({
                    "container_name": upload_result.get("container_name"),
                    "account_name": upload_result.get("account_name")
                })
            elif provider == "oracle":
                config.update({
                    "bucket_name": upload_result.get("bucket_name"),
                    "namespace": upload_result.get("namespace"),
                    "compartment_id": upload_result.get("compartment_id")
                })
            
            # Generate metadata structure
            metadata = generate_datasource_metadata(
                filename=file.filename,
                storage_type=storage_type,
                channel_id=datasource_data.channel_id,
                workspace_id=str(channel.workspace_id),
                user_id=str(user.id),
                file_size=len(file_content),
                file_type=file.content_type or "application/octet-stream",
                provider=provider,
                app_type=None,
                log_type=datasource_data.log_type,
                config=config,
                file_url=upload_result["file_url"]
            )
            
            # Clean the metadata to remove null, empty, and default values
            cleaned_metadata = clean_metadata(metadata)
            
            # Enhance metadata with vault-specific fields AFTER cleaning
            from app.services.vault_data_builder import enhance_datasource_metadata
            
            enhanced_metadata = await enhance_datasource_metadata(
                existing_metadata=cleaned_metadata,
                storage_type=storage_type,
                provider=provider,
                config=config,
                db=db,
                channel_id=datasource_data.channel_id
            )
            
            # Handle vault integration for datasource metadata
            vault_unique_id = None
            if enhanced_metadata:
                # Vault integration is REQUIRED for ALL datasource types to ensure data security
                # This includes both cloud datasources (with sensitive credentials) and local files
                vault_required = True
                
                try:
                    vault_result = await handle_vault_integration(
                        datasource_metadata=enhanced_metadata,
                        user_id=str(user.id),
                        company_id=str(channel.company_id),
                        db=db,
                        required=vault_required
                    )
                    vault_unique_id = vault_result["vault_unique_id"] if vault_result else None
                    giggso_vault_id = vault_result["giggso_vault_id"] if vault_result else None
                    
                    # If vault integration failed, we cannot proceed with datasource creation
                    if not vault_unique_id:
                        failed_datasources.append({
                            "name": datasource_data.name,
                            "error": "Vault integration failed. Cannot create datasource without secure storage."
                        })
                        continue
                        
                except HTTPException as e:
                    # Vault integration failed - add to failed datasources
                    failed_datasources.append({
                        "name": datasource_data.name,
                        "error": f"Vault integration failed: {e.detail}"
                    })
                    continue
                except Exception as e:
                    # For unexpected errors, log and fail
                    print(f"Unexpected error during vault integration: {str(e)}")
                    failed_datasources.append({
                        "name": datasource_data.name,
                        "error": "Failed to integrate with vault service"
                    })
                    continue
            
            # Store enhanced metadata directly in database (with vault integration for backup)
            final_metadata = enhanced_metadata.copy()
            if vault_unique_id:
                final_metadata["vault_unique_id"] = str(vault_unique_id)
            
            # Create datasource
            datasource = Datasource(
                id=str(uuid.uuid4()),
                name=datasource_name,
                filename=file.filename,
                storage_type=storage_type,
                provider=provider,
                app_type=datasource_data.app_type,
                log_type=datasource_data.log_type,
                config=config,
                datasource_metadata=final_metadata,
                giggso_vault_id=giggso_vault_id,  # Store vault ID in dedicated column
                file_size=len(file_content),
                file_type=file.content_type or "application/octet-stream",
                file_url=upload_result["file_url"],
                channel_id=datasource_data.channel_id,
                added_by=user.id
            )
            
            db.add(datasource)
            await db.commit()
            await db.refresh(datasource)
            
            created_datasources.append({
                "id": str(datasource.id),
                "name": datasource.name,
                "filename": datasource.filename,
                "storage_type": datasource.storage_type,
                "provider": datasource.provider,
                "app_type": datasource.app_type,
                "config": datasource.config,
                "datasource_metadata": sanitize_datasource_metadata(datasource.datasource_metadata),
                "giggso_vault_id": str(datasource.giggso_vault_id) if datasource.giggso_vault_id else None,
                "file_size": datasource.file_size,
                "file_type": datasource.file_type,
                "file_url": datasource.file_url,
                "channel_id": str(datasource.channel_id),
                "workspace_id": str(channel.workspace_id),
                "company_id": str(channel.company_id),
                "added_by": str(datasource.added_by),
                "is_active": datasource.is_active,
                "is_connected": datasource.is_connected,
                "is_processed": datasource.is_processed,
                "processing_status": datasource.processing_status,
                "error_message": datasource.error_message,
                "last_processed_at": datasource.last_processed_at,
                "processing_time": datasource.processing_time,
                "record_count": datasource.record_count,
                "is_embedding_required": datasource.is_embedding_required,
                "embedding_status": datasource.embedding_status,
                "created_at": datasource.created_at,
                "updated_at": datasource.updated_at
            })
            
        except Exception as e:
            failed_datasources.append({
                "name": datasource_data.name,
                "error": str(e)
            })
    
    return DatasourceBulkResponse(
        created_datasources=created_datasources,
        failed_datasources=failed_datasources,
        total_created=len(created_datasources),
        total_failed=len(failed_datasources)
    )
