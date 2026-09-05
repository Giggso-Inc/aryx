"""
Embedding-status / vault-token / Aryx-status query helpers shared across
datasource create, bulk, embedding-status, and download routes.

Private module: used by create.py, bulk_create.py, bulk_create_internal.py,
embedding_status.py, embedding_regenerate.py, and download_datasource.py
(and their _*.py helper files).

Stated exception (165 lines): five small, independent query/lookup
functions genuinely used across most of the package; splitting further
would mean one function per file for functions that are already ~15-30
lines each and share no internal state.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import String, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import literal

from app.models.datasource import Datasource
from app.models.giggso_vault import GiggsoVault
from app.routes.aryx import call_aryx_job_status

logger = logging.getLogger(__name__)


async def _aryx_ingestion_status_for(datasource_metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Best-effort live Aryx job status for a datasource, additive only.

    Returns None (never raises) unless datasource_metadata carries an
    aryx.discovery_id — i.e. this datasource was created via a kind="aryx"
    bulk upload. A datasource without that key is completely unaffected;
    a transient Aryx-unreachable error degrades to None rather than failing
    the caller's whole response.
    """
    if not datasource_metadata:
        return None
    aryx_meta = datasource_metadata.get("aryx")
    if not isinstance(aryx_meta, dict):
        return None
    discovery_id = aryx_meta.get("discovery_id")
    if not discovery_id:
        return None
    try:
        return await call_aryx_job_status(discovery_id)
    except Exception as exc:  # noqa: BLE001 — status enrichment must never break the caller
        logger.warning("aryx_ingestion_status lookup failed for discovery_id=%s: %s", discovery_id, exc)
        return {"error": "status temporarily unavailable"}


async def get_openai_vault_token_for_company(db: AsyncSession, company_id: str) -> Optional[str]:
    """
    Fetch vault_unique_id from gg_vault for the company and vault_type='gpt_token'.
    Used as openaiVaultToken when calling the ML API (/shay/email/embeddings).
    """
    try:
        company_uuid = uuid.UUID(company_id) if isinstance(company_id, str) else company_id
    except (ValueError, TypeError):
        return None
    stmt = (
        select(GiggsoVault.vault_unique_id)
        .where(
            GiggsoVault.company_id == company_uuid,
            GiggsoVault.vault_type == "gpt_token",
        )
        .order_by(GiggsoVault.created_datetime.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return row if row else None


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
