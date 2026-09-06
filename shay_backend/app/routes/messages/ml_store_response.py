"""
store_ml_messages sub-step: assemble the MLMessageResponse payload for the
newly created user + system messages.

Split out of app/routes/messages/ml_store.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from typing import List, Optional

from app.models.message import Message, Thread
from app.models.user import User
from app.schemas.message import MessageResponse, UserBean, Citation


def build_ml_response_data(
    user: User,
    system_user: User,
    user_message: Message,
    system_message: Message,
    thread: Thread,
    citations_for_response: Optional[list],
    usage_metrics_for_response: Optional[dict],
) -> List[MessageResponse]:
    """Build the two-element [user, system] MessageResponse list."""
    user_bean = UserBean(
        id=str(user.id),
        email=user.email_id,
        name=user.name,
        role=user.role,
        avatar_url=user.avatar_url
    )

    user_response = MessageResponse(
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
    )

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

    system_response = MessageResponse(
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
    )

    return [user_response, system_response]
