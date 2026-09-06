"""
POST /ml-store — store_ml_messages: ML services call this to persist both a
user prompt and its generated response in one call.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Wave B2 follow-up: the Phase-5 file kept this endpoint as one long function
under a "stated exception" (shared sequence-number bookkeeping + one
atomic transaction). Re-examined: the sequence number is just an int
threaded through explicit parameters (not an opaque shared object), so the
steps split cleanly into named helpers in sibling modules:
  - ml_store_lookup: thread_id parsing, thread/channel fetch
  - ml_store_build: user/system Message construction + citation/usage prep
  - ml_store_persist: metadata bump, audit log (both messages), commit, refresh
  - ml_store_response: response payload assembly
The one thing that must stay here is the endpoint's own top-level
try/except contract: ANY exception (including a raw DB error) is caught
and reported as HTTP 200 with status="failed", never as an HTTP error
status — that is an orchestrator-level concern, not something a sub-step
helper can own, so it remains the genuine reason this function stays a
single try block.
"""

from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.schemas.message import MLMessageRequest, MLMessageResponse
from .socket_events import emit_message_created_event
from .system_user import get_or_create_system_user
from .messages_create_lookup import get_next_sequence_number
from .ml_store_lookup import parse_thread_uuid, get_thread, get_channel
from .ml_store_build import build_user_message, prepare_system_message_fields, build_system_message
from .ml_store_persist import persist_ml_messages
from .ml_store_response import build_ml_response_data

router = APIRouter()


@router.post("/ml-store", response_model=MLMessageResponse)
async def store_ml_messages(
    ml_data: MLMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> MLMessageResponse:
    """
    Store both user query and ML response in a single API call.

    This endpoint is designed for ML services to store both the user's query
    and the generated response in the database. It creates two messages:
    1. A user message with the prompt (saved with authenticated user)
    2. A system message with the response, linked to the user message (saved with system user)

    Author: Karthick Chandrasekar
    Version: 1.0.0
    Last date modified: 2025-09-02
    """
    try:
        user = await get_current_user_required(request)

        thread_uuid = parse_thread_uuid(ml_data.thread_id)
        if thread_uuid is None:
            return MLMessageResponse(status="failed", message="Invalid thread_id format", data=[])

        thread = await get_thread(db, thread_uuid)
        if not thread:
            return MLMessageResponse(status="failed", message="Thread not found", data=[])

        channel = await get_channel(db, thread.channel_id)
        if not channel:
            return MLMessageResponse(status="failed", message="Channel not found", data=[])

        system_user = await get_or_create_system_user(db)

        next_seq = await get_next_sequence_number(db, thread_uuid)

        user_message = build_user_message(ml_data, thread_uuid, user, next_seq)
        db.add(user_message)
        next_seq += 1

        citations_data, citations_for_response, usage_metrics_data, usage_metrics_for_response, ai_processing_time_ms = \
            prepare_system_message_fields(ml_data)

        system_message = build_system_message(
            ml_data, thread_uuid, system_user, user_message.id, next_seq,
            citations_data, usage_metrics_data, ai_processing_time_ms,
        )
        db.add(system_message)

        await persist_ml_messages(db, thread, channel, user_message, system_message, user.id)

        # Emit socket events for both messages - PURE EMISSION ONLY
        await emit_message_created_event(
            channel_id=str(thread.channel_id),
            thread_id=str(user_message.thread_id),
            message_id=str(user_message.id)
        )
        await emit_message_created_event(
            channel_id=str(thread.channel_id),
            thread_id=str(system_message.thread_id),
            message_id=str(system_message.id)
        )

        response_data = build_ml_response_data(
            user, system_user, user_message, system_message, thread,
            citations_for_response, usage_metrics_for_response,
        )

        return MLMessageResponse(
            status="success",
            message="Response received successfully",
            data=response_data
        )

    except Exception as e:
        # Rollback any changes
        await db.rollback()
        return MLMessageResponse(
            status="failed",
            message=f"There is some issue while getting connection to database: {str(e)}",
            data=[]
        )
