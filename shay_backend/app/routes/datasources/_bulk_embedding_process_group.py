"""
Per-embedd_type-group ML dispatch, used by
_bulk_embedding_dispatch.trigger_bulk_embeddings.

Extracted out of what used to be a 194-line _bulk_embedding_dispatch.py:
this is the "call the ML API for one bucket (textual or tabular) and emit
one socket event per datasource based on the result" step, which stands on
its own once vault_id_mapping is already built.
"""

import logging
from typing import Any, Dict, List, Optional

from app.services.ml_service import extract_table_names_from_datasources, ml_service
from app.services.socket_client_service import get_socket_service

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
