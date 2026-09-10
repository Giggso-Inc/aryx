"""
Post-create embedding trigger for create.py (POST / — single datasource
creation).

Private module: extracted verbatim from the original create_datasource
endpoint body.
"""

import logging

from sqlalchemy import select

from app.models.giggso_vault import GiggsoVault
from app.services.ml_service import extract_table_names_from_datasources, ml_service
from app.services.socket_client_service import get_socket_service

from ._embedding_helpers import get_completed_embeddings_by_channel, get_openai_vault_token_for_company

logger = logging.getLogger(__name__)


async def trigger_embedding_for_new_datasource(datasource, request, user, db) -> None:
    """Fire the ML embedding-processing request for a freshly created datasource, if required.

    Best-effort: any failure is logged, never raised (the datasource is
    already committed at this point).
    """
    if not (datasource.is_embedding_required and datasource.giggso_vault_id):
        return

    try:
        # Get vault_unique_id from gg_vault table
        vault_stmt = select(GiggsoVault).where(GiggsoVault.giggso_vault_id == datasource.giggso_vault_id)
        vault_result = await db.execute(vault_stmt)
        vault_record = vault_result.scalar_one_or_none()

        if not (vault_record and vault_record.vault_unique_id):
            logger.warning(f"Vault record not found for giggso_vault_id: {datasource.giggso_vault_id}")
            return

        # Determine embedd_type based on file type, storage type, and provider
        from app.services.ml_service import get_embedd_type_from_file_type
        embedd_type = get_embedd_type_from_file_type(
            file_type=datasource.file_type,
            storage_type=datasource.storage_type,
            provider=datasource.provider
        )

        # Extract table_name from datasource metadata (for database datasources)
        table_name = None
        if datasource.datasource_metadata and isinstance(datasource.datasource_metadata, dict):
            table_name = datasource.datasource_metadata.get("tableName")

        # Get completed embeddings for this channel
        embedded_vault_unique_ids = await get_completed_embeddings_by_channel(str(datasource.channel_id), db)

        # Extract JWT token from Authorization header
        auth_header = request.headers.get("Authorization")
        jwt_token = None
        if auth_header and auth_header.startswith("Bearer "):
            jwt_token = auth_header.split(" ")[1]

        logger.info(f"Triggering embedding for datasource {datasource.id}, embedd_type: {embedd_type}")

        # Fetch OpenAI vault token (gpt_token) for company to send to ML API
        openai_vault_token = await get_openai_vault_token_for_company(db, str(user.company_id))
        # Call ML API to request embedding processing
        table_names = extract_table_names_from_datasources([datasource]) if table_name is None else None
        result = await ml_service.request_embedding_processing(
            vault_unique_ids=[vault_record.vault_unique_id],
            user_id=str(user.id),
            company_id=str(user.company_id),
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
            ml_status = 2 if result.get("success") else 3
            socket_event_data = {
                "type": 16,
                "data": {
                    "channelId": str(datasource.channel_id),
                    "status": ml_status,
                    "datasourceId": str(datasource.id)
                }
            }
            socket_service.emit("datasource_event", socket_event_data)
    except Exception as e:
        logger.error(f"Error triggering embedding for datasource {datasource.id}: {e}", exc_info=True)
