"""
Shared "trigger embedding for a batch of just-created datasources" logic for
bulk_create.py (POST /bulk) and bulk_create_internal.py (POST /internal/bulk).

Both endpoints, after creating their datasources, group the ones that need
embedding into textual/tabular buckets (by embedd_type) and fire one ML API
call per bucket, emitting a socket event per datasource based on the result.
This was ~285 lines duplicated almost verbatim between the two endpoints;
extracted here so each endpoint stays under the line cap. The only real
differences between the two call sites are how jwt_token and
embedded_vault_unique_ids are sourced, and internal/bulk's extra
thread-level scoping (thread_id) — both are left as explicit parameters so
each caller can supply them exactly as before.

Stated exception (188 lines): grouping was already extracted to
_bulk_embedding_grouping.py; what remains (_process_embedding_group +
trigger_bulk_embeddings) is the vault-lookup -> group -> per-bucket ML-call
-> socket-emit pipeline, which is one dependent sequence rather than
independent reusable units.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.giggso_vault import GiggsoVault
from app.services.ml_service import extract_table_names_from_datasources, ml_service
from app.services.socket_client_service import get_socket_service

from ._bulk_embedding_grouping import build_vault_id_mapping, group_by_embedd_type
from ._embedding_helpers import get_openai_vault_token_for_company

logger = logging.getLogger(__name__)


async def _process_embedding_group(
    group_label: str,
    group: List[Dict[str, Any]],
    vault_id_mapping: Dict[str, Any],
    *,
    user_id: str,
    company_id: str,
    channel_id: str,
    embedded_vault_unique_ids: List[str],
    jwt_token: Optional[str],
    thread_id: Optional[str],
    openai_vault_token: Optional[str],
) -> None:
    """Call the ML API for one embedd_type group (textual or tabular) and emit socket events."""
    vault_unique_ids = [
        vault_id_mapping[str(ds["giggso_vault_id"])]
        for ds in group
        if ds["giggso_vault_id"] and str(ds["giggso_vault_id"]) in vault_id_mapping
    ]
    logger.debug(f"{group_label} vault_unique_ids: {vault_unique_ids} (from {len(group)} {group_label} datasources)")
    if not vault_unique_ids:
        return

    ds_list = [ds["datasource"] for ds in group]

    # Extract table_name from first datasource metadata that has it
    table_name = None
    for ds in group:
        metadata = ds["datasource"].get("datasource_metadata")
        if metadata and isinstance(metadata, dict):
            table_name = metadata.get("tableName")
            if table_name:
                break

    try:
        table_names = extract_table_names_from_datasources(ds_list) if len(ds_list) > 1 else None
        logger.info(f"🚀 Calling ML API for {len(vault_unique_ids)} {group_label} file(s) with embedd_type='{group_label}'")

        result = await ml_service.request_embedding_processing(
            vault_unique_ids=vault_unique_ids,
            user_id=user_id,
            company_id=company_id,
            channel_id=channel_id,
            embedded_vault_unique_ids=embedded_vault_unique_ids,
            jwt_token=jwt_token,
            embedd_type=group_label,
            table_name=table_name,
            table_names=table_names,
            thread_id=thread_id,
            openai_vault_token=openai_vault_token
        )

        # Emit socket event based on ML API response
        socket_service = get_socket_service()
        if socket_service.is_socket_connected():
            ml_status = 2 if result.get("success") else 3  # 2 = success, 3 = failure
            for ds in group:
                datasource_id = ds["datasource"].get("id")
                if datasource_id:
                    socket_event_data = {"type": 16, "data": {"channelId": channel_id, "status": ml_status, "datasourceId": datasource_id}}
                    try:
                        await socket_service.emit("shay_realtime", socket_event_data)
                        logger.info(f"✅ Emitted socket event for {group_label} datasource {datasource_id}: status={ml_status}")
                    except Exception as socket_error:
                        logger.error(f"❌ Failed to emit socket event for datasource {datasource_id}: {socket_error}")

        if result.get("success"):
            logger.info(f"✅ ML API call successful for {len(vault_unique_ids)} {group_label} file(s)")
        else:
            logger.error(f"❌ ML API call failed for {group_label} files: {result.get('message', 'Unknown error')}")

    except Exception as e:
        logger.error(f"❌ Error calling ML API for {group_label} files: {e}")

        # Emit socket event for failure
        socket_service = get_socket_service()
        if socket_service.is_socket_connected():
            for ds in group:
                datasource_id = ds["datasource"].get("id")
                if datasource_id:
                    try:
                        await socket_service.emit("shay_realtime", {
                            "type": 16,
                            "data": {"channelId": channel_id, "status": 3, "datasourceId": datasource_id}  # failure
                        })
                    except Exception:
                        pass


async def trigger_bulk_embeddings(
    created_datasources: List[Dict[str, Any]],
    db: AsyncSession,
    *,
    user_id: str,
    company_id: str,
    jwt_token: Optional[str],
    embedded_vault_unique_ids_for_channel,
    log_prefix: str = "",
    mapping_log_suffix: str = "",
    thread_id: Optional[str] = None,
) -> None:
    """Group created_datasources needing embedding and dispatch one ML API call per
    embedd_type bucket. embedded_vault_unique_ids_for_channel is an async callable
    taking (channel_id, db) — or, for internal/bulk's thread scope, the caller
    passes a zero-arg async callable that already resolves thread vs. channel scope.
    """
    embedding_required_datasources = [ds for ds in created_datasources if ds.get("is_embedding_required", False)]
    if not embedding_required_datasources:
        return

    giggso_vault_ids = [ds["giggso_vault_id"] for ds in embedding_required_datasources if ds.get("giggso_vault_id")]

    vault_unique_ids = []
    vault_records = []
    if giggso_vault_ids:
        stmt = select(GiggsoVault).where(GiggsoVault.giggso_vault_id.in_(giggso_vault_ids))
        result = await db.execute(stmt)
        vault_records = result.scalars().all()
        vault_unique_ids = [record.vault_unique_id for record in vault_records if record.vault_unique_id]

        logger.info("=" * 80)
        logger.info(f"🔍 VAULT ID CONVERSION{log_prefix}")
        logger.info("=" * 80)
        logger.info(f"📊 Found {len(embedding_required_datasources)} datasources requiring embedding")
        logger.info(f"🔑 giggso_vault_ids: {giggso_vault_ids}")
        logger.info(f"📦 vault_unique_ids: {vault_unique_ids}")
        logger.info("=" * 80)

    if not vault_unique_ids:
        return

    first_datasource = embedding_required_datasources[0]
    channel_id = first_datasource.get("channel_id")

    vault_id_mapping = build_vault_id_mapping(embedding_required_datasources, vault_records)
    logger.debug(f"🔍 Vault ID Mapping created{mapping_log_suffix}: {len(vault_id_mapping)} mappings")
    logger.debug(f"   Mapping keys: {list(vault_id_mapping.keys())}")

    textual_datasources, tabular_datasources = group_by_embedd_type(embedding_required_datasources)
    logger.info("=" * 80)
    logger.info(f"📊 FILE CLASSIFICATION FOR BULK EMBEDDING{log_prefix}")
    logger.info("=" * 80)
    logger.info(f"📄 Textual files: {len(textual_datasources)}")
    logger.info(f"📊 Tabular files: {len(tabular_datasources)}")
    logger.info("=" * 80)

    embedded_vault_unique_ids = await embedded_vault_unique_ids_for_channel(channel_id)
    openai_vault_token = await get_openai_vault_token_for_company(db, company_id)

    for group_label, group in (("textual", textual_datasources), ("tabular", tabular_datasources)):
        if group:
            await _process_embedding_group(
                group_label, group, vault_id_mapping,
                user_id=user_id, company_id=company_id, channel_id=channel_id,
                embedded_vault_unique_ids=embedded_vault_unique_ids, jwt_token=jwt_token,
                thread_id=thread_id, openai_vault_token=openai_vault_token,
            )
