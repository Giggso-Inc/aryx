"""Batch embedding-status writer, keyed by vault_unique_id."""

import logging
from typing import List

from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import literal

from app.models.datasource import Datasource

logger = logging.getLogger(__name__)


async def update_embedding_status_batch(vault_unique_ids: List[str], status: int, db: AsyncSession) -> None:
    """Update embedding status for a batch of datasources by vault_unique_id"""
    logger.info("=" * 80)
    logger.info("🔄 UPDATING EMBEDDING STATUS BATCH")
    logger.info("=" * 80)
    logger.info(f"📋 Vault Unique IDs: {vault_unique_ids}")
    logger.info(f"📊 Status: {status} ({'Not Required' if status == 0 else 'In Progress' if status == 1 else 'Completed' if status == 2 else 'Failed'})")
    logger.info("=" * 80)

    try:
        # Find datasources by vault_unique_id in metadata
        logger.info("🔍 Finding datasources by vault_unique_id in metadata...")
        stmt = select(Datasource).where(
            Datasource.datasource_metadata.op("->>")(literal("vault_unique_id", type_=String())).in_(vault_unique_ids)
        )
        result = await db.execute(stmt)
        datasources = result.scalars().all()

        logger.info(f"📊 Found {len(datasources)} datasources to update")

        # Update embedding status
        for datasource in datasources:
            old_status = datasource.embedding_status
            datasource.embedding_status = status
            if status == 3:  # Failed
                datasource.error_message = "Embedding processing failed"
            logger.info(f"📝 Updated datasource {datasource.id}: {old_status} -> {status}")

        await db.commit()
        logger.info(f"✅ Successfully updated embedding status to {status} for {len(datasources)} datasources")

    except Exception as e:
        logger.error("=" * 80)
        logger.error("💥 ERROR UPDATING EMBEDDING STATUS")
        logger.error("=" * 80)
        logger.error(f"❌ Error: {str(e)}")
        logger.error(f"🔍 Error Type: {type(e).__name__}")
        logger.error("🔄 Rolling back database transaction...")
        logger.error("=" * 80)
        await db.rollback()
