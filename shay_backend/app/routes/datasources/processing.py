"""
Datasource /process and /{datasource_id}/download endpoints.
"""

import asyncio
import logging
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.datasource import Datasource
from app.models.giggso_vault import GiggsoVault
from app.schemas.datasource import DatasourceProcessingRequest, DatasourceProcessingResponse
from app.services.file_storage import get_file_storage_service
from app.services.ml_service import extract_table_names_from_datasources, ml_service

from ._shared import (
    DATASOURCE_DATABASE_PROVIDERS,
    get_external_view_url_for_datasource,
    get_media_type_for_download,
    get_storage_file_path_for_deletion,
    get_vault_credentials_for_datasource,
    get_openai_vault_token_for_company,
    download_from_azure_with_vault_credentials,
    download_from_gcp_with_vault_credentials,
    download_from_s3_with_vault_credentials,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{datasource_id}/download")
async def download_datasource(
    datasource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    view: bool = Query(False, description="If true, use inline disposition for browser display; else attachment for download"),
    s3: bool = Query(False, description="If true, download from S3 using credentials from vault (datasource must have giggso_vault_id)"),
    azure: bool = Query(False, description="If true, download from Azure Blob using credentials from vault (datasource must have giggso_vault_id)"),
    gcp: bool = Query(False, description="If true, download from GCP Cloud Storage using credentials from vault (datasource must have giggso_vault_id)")
) -> Response:
    """
    Download or view datasource file content. One API for all sources:
    - Tabular files (Excel, CSV, etc.): view or download. Files in our S3/local storage are
      streamed with correct Content-Type (e.g. text/csv, spreadsheet) so browsers can display them.
    - Google Drive (and other app) datasources: view or download via redirect to the external
      view URL (webViewLink/webContentLink or file_url) so the same API works for Drive-added docs.
    - S3-stored files: files uploaded through the app (stored in our S3) are streamed and support
      both view (inline) and download (attachment); external S3 file_url is served via redirect.
    - When s3=1: credentials are taken from vault (using datasource_id -> giggso_vault_id); file is downloaded from S3 and streamed.
    - When azure=1: credentials are taken from vault (using datasource_id -> giggso_vault_id); file is downloaded from Azure Blob and streamed.
    - When gcp=1: credentials are taken from vault (using datasource_id -> giggso_vault_id); file is downloaded from GCP Cloud Storage and streamed.
    - Database datasources (Oracle, Redshift, MySQL, etc.): no file; returns 404 with clear message.
    Use view=1 for in-browser display (e.g. PDF, CSV, Excel), or omit for download.
    """
    user = await get_current_user_required(request)
    
    # Get datasource
    stmt = select(Datasource).where(Datasource.id == datasource_id)
    result = await db.execute(stmt)
    datasource = result.scalar_one_or_none()
    
    if not datasource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datasource not found"
        )
    
    # Check permissions
    if not datasource.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to datasource"
        )
    
    # Case: s3=true — download from S3 using vault credentials (datasource_id -> vault -> S3 creds)
    if s3:
        if not datasource.giggso_vault_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Datasource has no vault integration; cannot download from S3 with vault credentials."
            )
        vault_creds = await get_vault_credentials_for_datasource(datasource, db)
        if not vault_creds:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vault record or credentials not found for this datasource."
            )
        file_content = await download_from_s3_with_vault_credentials(datasource, vault_creds, db)
        if not file_content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Could not download file from S3 (check vault credentials and datasource bucket/key or file_url)."
            )
        media_type = get_media_type_for_download(datasource)
        filename = datasource.filename or "datasource_file"
        disposition = "inline" if view else "attachment"
        return Response(
            content=file_content,
            media_type=media_type,
            headers={"Content-Disposition": f'{disposition}; filename="{filename}"'}
        )
    
    # Case: azure=true — download from Azure Blob using vault credentials (datasource_id -> vault -> Azure creds)
    if azure:
        if not datasource.giggso_vault_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Datasource has no vault integration; cannot download from Azure with vault credentials."
            )
        vault_creds = await get_vault_credentials_for_datasource(datasource, db)
        if not vault_creds:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vault record or credentials not found for this datasource."
            )
        file_content = await download_from_azure_with_vault_credentials(datasource, vault_creds, db)
        if not file_content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Could not download file from Azure (check vault credentials and datasource container/blob or file_url)."
            )
        media_type = get_media_type_for_download(datasource)
        filename = datasource.filename or "datasource_file"
        disposition = "inline" if view else "attachment"
        return Response(
            content=file_content,
            media_type=media_type,
            headers={"Content-Disposition": f'{disposition}; filename="{filename}"'}
        )
    
    # Case: gcp=true — download from GCP Cloud Storage using vault credentials (datasource_id -> vault -> GCP creds)
    if gcp:
        if not datasource.giggso_vault_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Datasource has no vault integration; cannot download from GCP with vault credentials."
            )
        vault_creds = await get_vault_credentials_for_datasource(datasource, db)
        if not vault_creds:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vault record or credentials not found for this datasource."
            )
        file_content = await download_from_gcp_with_vault_credentials(datasource, vault_creds, db)
        if not file_content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Could not download file from GCP (check vault credentials and datasource bucket/blob or file_url)."
            )
        media_type = get_media_type_for_download(datasource)
        filename = datasource.filename or "datasource_file"
        disposition = "inline" if view else "attachment"
        return Response(
            content=file_content,
            media_type=media_type,
            headers={"Content-Disposition": f'{disposition}; filename="{filename}"'}
        )
    
    # Case 1: File stored in our storage (manual upload via upload/from-upload/bulk)
    storage_file_path = get_storage_file_path_for_deletion(datasource)
    if storage_file_path:
        try:
            storage_service = get_file_storage_service()
            file_content = await storage_service.download_file(storage_file_path)
        except Exception as e:
            logger.error(f"Failed to download datasource file {datasource_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File not found or failed to download: {str(e)}"
            )
        # Content type for view: use correct media type for tabular (Excel, CSV) and others
        media_type = get_media_type_for_download(datasource)
        filename = datasource.filename or "datasource_file"
        disposition = "inline" if view else "attachment"
        return Response(
            content=file_content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'{disposition}; filename="{filename}"'
            }
        )
    
    # Case 2: External view/download URL (cloud storage, app integrations e.g. Google Drive, SharePoint)
    external_url = get_external_view_url_for_datasource(datasource)
    if external_url:
        if "application/json" in (request.headers.get("accept") or "").lower():
            return JSONResponse(status_code=200, content={"url": external_url})
        return RedirectResponse(url=external_url, status_code=302)
    
    # Case 3: Database datasources (Oracle, Redshift, MySQL, PostgreSQL, SQL Server, MongoDB, DynamoDB, Snowflake)
    # No file to view or download; only table/collection references
    if datasource.storage_type == "database" or (
        getattr(datasource, "provider", None) and datasource.provider in DATASOURCE_DATABASE_PROVIDERS
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Database datasources (e.g. Oracle, Redshift, MySQL, PostgreSQL, SQL Server, MongoDB, DynamoDB, Snowflake) do not have a viewable or downloadable file; they reference tables or collections."
        )
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No downloadable file found for this datasource"
    )

@router.post("/process", response_model=DatasourceProcessingResponse)
async def process_datasources(
    processing_request: DatasourceProcessingRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> DatasourceProcessingResponse:
    """Process datasources in background"""
    user = await get_current_user_required(request)
    
    # Get datasource
    stmt = select(Datasource).where(Datasource.id == processing_request.datasource_id)
    result = await db.execute(stmt)
    datasource = result.scalar_one_or_none()
    
    if not datasource:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datasource not found"
        )
    
    # Check permissions through channel
    if not datasource.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to datasource"
        )
    
    # Add background task
    background_tasks.add_task(
        process_datasource_background,
        processing_request.datasource_id
    )
    
    return DatasourceProcessingResponse(
        datasource_id=processing_request.datasource_id,
        status="processing_started",
        message="Datasource processing started in background"
    )

async def process_datasource_background(datasource_id: str) -> None:
    """Background task to process datasource"""
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get datasource
            stmt = select(Datasource).where(Datasource.id == datasource_id)
            result = await db.execute(stmt)
            datasource = result.scalar_one_or_none()
            
            if not datasource:
                return
            
            # Mark as processing
            datasource.mark_processing_started()
            await db.commit()
            
            # Close session before long operation
            await db.close()
            
            # Simulate processing (replace with actual processing logic)
            await asyncio.sleep(5)
            
            # Create new session for final operations
            async with AsyncSessionLocal() as db:
                stmt = select(Datasource).where(Datasource.id == datasource_id)
                result = await db.execute(stmt)
                datasource = result.scalar_one_or_none()
                
                if datasource:
                    # Mark as completed
                    datasource.mark_processing_completed(record_count=100, processing_time=5000)
                    await db.commit()
            
        except Exception as e:
            # Create new session for error handling
            async with AsyncSessionLocal() as db:
                stmt = select(Datasource).where(Datasource.id == datasource_id)
                result = await db.execute(stmt)
                datasource = result.scalar_one_or_none()
                
                if datasource:
                    datasource.mark_processing_failed(str(e))
                    await db.commit()

async def process_embedding_background(
    vault_unique_ids: List[str],
    user_id: str,
    company_id: str,
    db
) -> None:
    """Background task to process embedding for datasources"""
    import logging
    from sqlalchemy import select
    from app.models.datasource import Datasource
    from app.models.giggso_vault import GiggsoVault
    from app.services.ml_service import get_embedd_type_from_file_type
    
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 80)
    logger.info("🚀 STARTING EMBEDDING BACKGROUND PROCESSING")
    logger.info("=" * 80)
    logger.info(f"📋 Vault Unique IDs: {vault_unique_ids}")
    logger.info(f"👤 User ID: {user_id}")
    logger.info(f"🏢 Company ID: {company_id}")
    logger.info(f"📊 Total Datasources: {len(vault_unique_ids)}")
    logger.info("=" * 80)
    
    try:
        # Get file types, storage types, and providers from datasources to determine embedd_type
        embedd_type = "textual"  # Default
        datasources = []
        
        if vault_unique_ids:
            # Query datasources by vault_unique_ids to get file types, storage types, and providers
            stmt = select(Datasource).join(GiggsoVault, Datasource.giggso_vault_id == GiggsoVault.giggso_vault_id).where(
                GiggsoVault.vault_unique_id.in_(vault_unique_ids)
            )
            result = await db.execute(stmt)
            datasources = result.scalars().all()
            
            if datasources:
                # Determine embedd_type for each datasource
                embedd_types = []
                for ds in datasources:
                    embedd_type_item = get_embedd_type_from_file_type(
                        file_type=ds.file_type,
                        storage_type=ds.storage_type,
                        provider=ds.provider
                    )
                    embedd_types.append(embedd_type_item)
                
                if embedd_types:
                    # Extract base types (remove provider suffix for comparison)
                    base_types = [et.split("_")[0] for et in embedd_types]
                    
                    if all(bt == "tabular" for bt in base_types):
                        # All are tabular - check if they're all database with same provider
                        database_datasources = [ds for ds in datasources if ds.storage_type == "database" and ds.provider]
                        if len(database_datasources) == len(datasources):
                            # All are database datasources
                            providers = [ds.provider.lower() for ds in database_datasources if ds.provider]
                            if len(set(providers)) == 1:
                                # All same database provider
                                embedd_type = f"tabular_{providers[0]}"
                            else:
                                # Mixed database providers - use first one
                                embedd_type = f"tabular_{providers[0]}" if providers else "tabular"
                        else:
                            # Mixed tabular types (files + databases or different providers)
                            embedd_type = "tabular"
                    else:
                        # Default to textual if mixed types or any textual files
                        embedd_type = "textual"
                
                logger.debug(f"Determined embedd_type: {embedd_type} based on {len(datasources)} datasources")
                
                # Extract table_name from first datasource metadata that has it (for database datasources)
                table_name = None
                for ds in datasources:
                    if ds.datasource_metadata and isinstance(ds.datasource_metadata, dict):
                        table_name = ds.datasource_metadata.get("tableName")
                        if table_name:
                            break
        
        # Fetch OpenAI vault token (gpt_token) for company to send to ML API
        openai_vault_token = await get_openai_vault_token_for_company(db, company_id)
        # Call ML API to request embedding processing
        logger.info("🔄 Calling ML API for embedding processing...")
        table_names = extract_table_names_from_datasources(datasources) if len(datasources) > 1 else None
        result = await ml_service.request_embedding_processing(
            vault_unique_ids=vault_unique_ids,
            user_id=user_id,
            company_id=company_id,
            channel_id="",  # Background task doesn't have channel_id context
            embedded_vault_unique_ids=[],
            embedd_type=embedd_type,
            table_name=table_name,
            table_names=table_names,
            openai_vault_token=openai_vault_token
        )
        
        logger.info("=" * 80)
        logger.info("📥 ML API CALL RESULT")
        logger.info("=" * 80)
        logger.info(f"✅ Success: {result['success']}")
        logger.info(f"📝 Message: {result['message']}")
        if 'data' in result:
            logger.info(f"📊 Data: {result['data']}")
        if 'error' in result:
            logger.info(f"❌ Error: {result['error']}")
        logger.info("=" * 80)
        
        if result["success"]:
            logger.info(f"✅ Successfully requested embedding processing for {len(vault_unique_ids)} datasources")
        else:
            logger.error(f"❌ Failed to request embedding processing: {result['message']}")
            logger.info("🔄 Status update to failed is handled by ML team via webhook...")
            # TODO: Status update to failed is handled by ML team via webhook
            # await update_embedding_status_batch(vault_unique_ids, 3, db)
            
    except Exception as e:
        logger.error("=" * 80)
        logger.error("💥 EMBEDDING BACKGROUND PROCESSING ERROR")
        logger.error("=" * 80)
        logger.error(f"❌ Error: {str(e)}")
        logger.error(f"🔍 Error Type: {type(e).__name__}")
        logger.error("🔄 Status update to failed is handled by ML team via webhook...")
        logger.error("=" * 80)
        # TODO: Status update to failed is handled by ML team via webhook
        # await update_embedding_status_batch(vault_unique_ids, 3, db)
