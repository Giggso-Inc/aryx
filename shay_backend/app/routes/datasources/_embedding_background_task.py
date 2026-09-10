"""
Background task to process embedding for a batch of datasources by
vault_unique_id. Not currently called from any route in this package (no
router here) — kept as-is from the original processing.py, just relocated
so processing.py's actual endpoints stay under the line cap.
"""

import logging
from typing import List

from sqlalchemy import select

from app.models.datasource import Datasource
from app.models.giggso_vault import GiggsoVault
from app.services.ml_service import extract_table_names_from_datasources, ml_service

from ._embedding_helpers import get_openai_vault_token_for_company


async def process_embedding_background(
    vault_unique_ids: List[str],
    user_id: str,
    company_id: str,
    db
) -> None:
    """Background task to process embedding for datasources"""
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
                from app.services.ml_service import get_embedd_type_from_file_type
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
