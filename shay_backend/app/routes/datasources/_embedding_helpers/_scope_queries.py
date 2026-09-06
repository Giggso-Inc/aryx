"""Completed-embedding vault_unique_id lookups, scoped by channel or by thread."""

import logging
from typing import List

from sqlalchemy import String, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import literal

from app.models.datasource import Datasource
from app.models.giggso_vault import GiggsoVault

logger = logging.getLogger(__name__)


async def get_completed_embeddings_by_channel(channel_id: str, db: AsyncSession) -> List[str]:
    """Get vault_unique_ids of datasources with completed embeddings in a channel (channel-level scope)"""
    try:
        # Find datasources with completed embeddings (status = 2) in the channel
        # Exclude thread-level datasources (have thread_id in metadata) - those use thread scope
        stmt = select(GiggsoVault.vault_unique_id).join(
            Datasource, GiggsoVault.giggso_vault_id == Datasource.giggso_vault_id
        ).where(
            and_(
                Datasource.channel_id == channel_id,
                Datasource.embedding_status == 2,  # 2 = completed
                Datasource.is_embedding_required == True,
                # Channel-level: no thread_id in metadata, or metadata null
                or_(
                    Datasource.datasource_metadata.is_(None),
                    ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
                )
            )
        )
        result = await db.execute(stmt)
        vault_unique_ids = result.scalars().all()

        logger.info(f"Found {len(vault_unique_ids)} completed channel-level embeddings for channel {channel_id}")
        return list(vault_unique_ids)

    except Exception as e:
        logger.error(f"Error getting completed embeddings for channel {channel_id}: {e}")
        return []


async def get_completed_embeddings_by_thread(thread_id: str, db: AsyncSession) -> List[str]:
    """Get vault_unique_ids of datasources with completed embeddings in a thread (thread-level scope)"""
    try:
        # Find datasources with completed embeddings (status = 2) in this specific thread
        stmt = select(GiggsoVault.vault_unique_id).join(
            Datasource, GiggsoVault.giggso_vault_id == Datasource.giggso_vault_id
        ).where(
            and_(
                Datasource.embedding_status == 2,  # 2 = completed
                Datasource.is_embedding_required == True,
                Datasource.datasource_metadata.isnot(None),
                Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
                Datasource.datasource_metadata.op("->>")(literal("thread_id", type_=String())) == literal(str(thread_id), type_=String())
            )
        )
        result = await db.execute(stmt)
        vault_unique_ids = result.scalars().all()

        logger.info(f"Found {len(vault_unique_ids)} completed thread-level embeddings for thread {thread_id}")
        return list(vault_unique_ids)

    except Exception as e:
        logger.error(f"Error getting completed embeddings for thread {thread_id}: {e}")
        return []
