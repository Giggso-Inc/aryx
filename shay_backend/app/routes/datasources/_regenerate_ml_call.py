"""
ML API call + socket-emit step for embedding_regenerate.py's
regenerate_embedding endpoint.

Private module: extracted verbatim so the endpoint function itself stays
under the line cap.
"""

import logging

from app.services.ml_service import extract_table_names_from_datasources, ml_service
from app.services.socket_client_service import get_socket_service

logger = logging.getLogger(__name__)


async def call_ml_and_emit_socket_for_regenerate(
    *, datasource, datasource_id, embedd_type, table_name, vault_unique_id,
    current_user_id, current_company_id, embedded_vault_unique_ids, jwt_token, openai_vault_token,
) -> None:
    """Call ml_service.request_embedding_processing and emit a socket event based on the result.
    Best-effort: any failure is logged and also emits a failure socket event, never raised.
    """
    try:
        table_names = extract_table_names_from_datasources([datasource]) if table_name is None else None
        result = await ml_service.request_embedding_processing(
            vault_unique_ids=[vault_unique_id],
            user_id=current_user_id,
            company_id=current_company_id,
            channel_id=str(datasource.channel_id),
            embedded_vault_unique_ids=embedded_vault_unique_ids,
            jwt_token=jwt_token,
            embedd_type=embedd_type,
            table_name=table_name,
            table_names=table_names,
            openai_vault_token=openai_vault_token
        )

        # Emit socket event based on ML API response
        socket_service = get_socket_service()
        if socket_service.is_socket_connected():
            # Determine status based on ML API response
            ml_status = 2 if result.get("success") else 3  # 2 = success, 3 = failure

            socket_event_data = {
                "type": 16,
                "data": {
                    "channelId": str(datasource.channel_id),
                    "status": ml_status,
                    "datasourceId": datasource_id
                }
            }

            try:
                await socket_service.emit("shay_realtime", socket_event_data)
                logger.info(f"✅ Emitted socket event for datasource {datasource_id}: status={ml_status}")
            except Exception as socket_error:
                logger.error(f"❌ Failed to emit socket event for datasource {datasource_id}: {socket_error}")

        if result.get("success"):
            logger.info("✅ ML API call successful - embedding processing initiated")
        else:
            logger.error(f"❌ ML API call failed: {result.get('message', 'Unknown error')}")
            # TODO: Status update to failed is handled by ML team via webhook
            # datasource.embedding_status = 3  # 3 = failed
            # await db.commit()

    except Exception as e:
        logger.error(f"❌ Error calling ML API: {e}")

        # Emit socket event for failure
        socket_service = get_socket_service()
        if socket_service.is_socket_connected():
            socket_event_data = {
                "type": 16,
                "data": {
                    "channelId": str(datasource.channel_id),
                    "status": 3,  # 3 = failure
                    "datasourceId": datasource_id
                }
            }

            try:
                await socket_service.emit("shay_realtime", socket_event_data)
                logger.info(f"✅ Emitted socket event for datasource {datasource_id}: status=3 (failure)")
            except Exception as socket_error:
                logger.error(f"❌ Failed to emit socket event for datasource {datasource_id}: {socket_error}")

        # TODO: Status update to failed is handled by ML team via webhook
        # datasource.embedding_status = 3  # 3 = failed
        # await db.commit()
