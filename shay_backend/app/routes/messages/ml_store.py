"""
POST /ml-store — store_ml_messages: ML services call this to persist both a
user prompt and its generated response in one call.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5.

Stated exception: kept as one file rather than split further. The two
Message rows created here (user prompt, then system response linked to it
via query_id) share sequence-number bookkeeping and thread/channel metadata
updates that must stay atomic within one transaction — splitting them into
"create user message" / "create system message" helpers would mean passing
the shared sequence counter and half-committed state across module
boundaries for no real readability gain. It also matches the original
function's own top-level try/except contract: ANY exception here (including
a raw DB error) is caught and reported as HTTP 200 with status="failed",
never as an HTTP error status — documented, not "fixed", by the
characterization tests.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import generate_message_id
from app.middleware.auth_middleware import get_current_user_required
from app.services.audit_service import log as audit_log_write
from app.models.channel import Channel
from app.models.message import Message, Thread
from app.schemas.message import MLMessageRequest, MLMessageResponse, MessageResponse, UserBean, Citation
from .socket_events import emit_message_created_event
from .system_user import get_or_create_system_user

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
        # Get authenticated user for the prompt message
        user = await get_current_user_required(request)
        # Convert string UUID to UUID object
        try:
            thread_uuid = UUID(ml_data.thread_id)
        except ValueError:
            return MLMessageResponse(
                status="failed",
                message="Invalid thread_id format",
                data=[]
            )

        # Get thread
        stmt = select(Thread).where(Thread.id == thread_uuid)
        result = await db.execute(stmt)
        thread = result.scalar_one_or_none()

        if not thread:
            return MLMessageResponse(
                status="failed",
                message="Thread not found",
                data=[]
            )

        # Get channel
        stmt = select(Channel).where(Channel.id == thread.channel_id)
        result = await db.execute(stmt)
        channel = result.scalar_one_or_none()

        if not channel:
            return MLMessageResponse(
                status="failed",
                message="Channel not found",
                data=[]
            )

        # Get system user for the response
        system_user = await get_or_create_system_user(db)

        # Get next sequence numbers
        seq_query = select(func.max(Message.sequence_number)).where(Message.thread_id == thread_uuid)
        seq_result = await db.execute(seq_query)
        max_seq = seq_result.scalar() or 0

        # Create user message with the prompt (using authenticated user); mark as AI-processed since ML stored it
        user_message_id = UUID(generate_message_id())
        user_message = Message(
            id=user_message_id,
            content=ml_data.prompt,
            message_type="user",
            thread_id=thread_uuid,
            user_id=user.id,  # Use authenticated user for the prompt
            query_id=None,
            sequence_number=max_seq + 1,
            is_ai_processed=True,  # This message was processed by ML (response stored via this API)
        )
        db.add(user_message)
        max_seq += 1

        # Create system response message linked to the user message
        system_message_id = UUID(generate_message_id())

        citations_data = None
        citations_for_response = None
        if ml_data.citations:
            citations_data = [
                {
                    "name": citation.name,
                    "type": citation.type
                }
                for citation in ml_data.citations
            ]
            # Keep the original Citation objects for response
            citations_for_response = ml_data.citations

        # Persist usage_metrics from request for system message (token_usage, time_usage, etc.)
        usage_metrics_data = ml_data.usage_metrics if ml_data.usage_metrics else None
        usage_metrics_for_response = usage_metrics_data
        # Derive ai_processing_time from usage_metrics if present (e.g. time_usage in ms)
        ai_processing_time_ms = None
        if isinstance(usage_metrics_data, dict) and usage_metrics_data.get("time_usage") is not None:
            try:
                ai_processing_time_ms = int(usage_metrics_data["time_usage"])
            except (TypeError, ValueError):
                pass

        system_message = Message(
            id=system_message_id,
            content=ml_data.response,
            message_type="system",
            thread_id=thread_uuid,
            user_id=system_user.id,
            query_id=user_message_id,  # Link to the user message we just created
            sequence_number=max_seq + 1,
            citations=citations_data,  # Store citations for system messages only
            usage_metrics=usage_metrics_data,  # Store usage_metrics for system messages only
            is_ai_processed=True,  # System message is the AI response
            ai_processing_time=ai_processing_time_ms,
        )
        db.add(system_message)

        # Update thread metadata
        thread.message_count += 2  # We're adding 2 messages
        thread.last_message_at = datetime.utcnow()

        # Update channel metadata
        channel.message_count += 2  # We're adding 2 messages
        channel.last_message_at = datetime.utcnow()
        await audit_log_write(db, user.id, "message.created", "message", user_message.id, channel_id=thread.channel_id, thread_id=thread_uuid, details={"source": "ml-store", "message_type": "user"})
        await audit_log_write(db, user.id, "message.created", "message", system_message.id, channel_id=thread.channel_id, thread_id=thread_uuid, details={"source": "ml-store", "message_type": "system"})
        await db.commit()

        # Refresh messages to get the created data
        await db.refresh(user_message)
        await db.refresh(system_message)

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

        # Prepare response data
        response_data = []

        # Add user message to response (using authenticated user info)
        user_bean = UserBean(
            id=str(user.id),
            email=user.email_id,
            name=user.name,
            role=user.role,
            avatar_url=user.avatar_url
        )

        response_data.append(MessageResponse(
            id=str(user_message.id),
            content=user_message.content,
            message_type=user_message.message_type,
            thread_id=str(user_message.thread_id),
            channel_id=str(thread.channel_id),
            user_id=str(user_message.user_id),
            query_id=str(user_message.query_id) if user_message.query_id else None,
            userBean=user_bean,
            is_ai_processed=user_message.is_ai_processed,
            ai_provider=user_message.ai_provider,
            ai_model=user_message.ai_model,
            ai_processing_time=user_message.ai_processing_time,
            is_visible=user_message.is_visible,
            is_pinned=user_message.is_pinned,
            sequence_number=user_message.sequence_number,
            attachment_ids=[str(aid) for aid in user_message.attachment_ids] if user_message.attachment_ids else None,
            citations=None,  # User messages don't have citations
            usage_metrics=None,  # User messages don't have usage_metrics
            created_at=user_message.created_at,
            updated_at=user_message.updated_at
        ))

        # Add system message to response
        system_bean = UserBean(
            id=str(system_user.id),
            email=system_user.email_id,
            name=system_user.name,
            role=system_user.role,
            avatar_url=system_user.avatar_url
        )

        # Use citations from request (already in Citation format) or from database
        citations_response = None
        if citations_for_response:
            # Use the citations we already have from the request
            citations_response = citations_for_response
        elif system_message.citations and len(system_message.citations) > 0:
            # Fallback: convert from JSONB if not available from request
            citations_response = [
                Citation(name=citation["name"], type=citation["type"])
                for citation in system_message.citations
            ]

        # Use usage_metrics from request or from database (after persist)
        usage_metrics_response = usage_metrics_for_response if usage_metrics_for_response is not None else (system_message.usage_metrics or None)

        response_data.append(MessageResponse(
            id=str(system_message.id),
            content=system_message.content,
            message_type=system_message.message_type,
            thread_id=str(system_message.thread_id),
            channel_id=str(thread.channel_id),
            user_id=str(system_message.user_id),
            query_id=str(system_message.query_id),
            userBean=system_bean,
            is_ai_processed=system_message.is_ai_processed,
            ai_provider=system_message.ai_provider,
            ai_model=system_message.ai_model,
            ai_processing_time=system_message.ai_processing_time,
            is_visible=system_message.is_visible,
            is_pinned=system_message.is_pinned,
            sequence_number=system_message.sequence_number,
            attachment_ids=[str(aid) for aid in system_message.attachment_ids] if system_message.attachment_ids else None,
            citations=citations_response,  # Include citations for system messages
            usage_metrics=usage_metrics_response,  # Include usage_metrics for system messages
            created_at=system_message.created_at,
            updated_at=system_message.updated_at
        ))

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
