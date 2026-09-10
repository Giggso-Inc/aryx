"""
store_ml_messages sub-steps: build the user-prompt Message and the
system-response Message rows.

Split out of app/routes/messages/ml_store.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2.
"""

from typing import Optional, Tuple
from uuid import UUID

from app.core.auth import generate_message_id
from app.models.message import Message
from app.models.user import User
from app.schemas.message import MLMessageRequest


def build_user_message(ml_data: MLMessageRequest, thread_uuid: UUID, user: User, next_seq: int) -> Message:
    """Build the user-prompt Message row (not yet added/committed)."""
    return Message(
        id=UUID(generate_message_id()),
        content=ml_data.prompt,
        message_type="user",
        thread_id=thread_uuid,
        user_id=user.id,  # Use authenticated user for the prompt
        query_id=None,
        sequence_number=next_seq,
        is_ai_processed=True,  # This message was processed by ML (response stored via this API)
    )


def prepare_system_message_fields(ml_data: MLMessageRequest) -> Tuple[Optional[list], Optional[list], Optional[dict], Optional[dict], Optional[int]]:
    """
    Derive the citations/usage_metrics fields for the system response message.

    Returns:
        (citations_data, citations_for_response, usage_metrics_data,
         usage_metrics_for_response, ai_processing_time_ms)
    """
    citations_data = None
    citations_for_response = None
    if ml_data.citations:
        citations_data = [
            {"name": citation.name, "type": citation.type}
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

    return citations_data, citations_for_response, usage_metrics_data, usage_metrics_for_response, ai_processing_time_ms


def build_system_message(
    ml_data: MLMessageRequest,
    thread_uuid: UUID,
    system_user: User,
    user_message_id: UUID,
    next_seq: int,
    citations_data,
    usage_metrics_data,
    ai_processing_time_ms,
) -> Message:
    """Build the system-response Message row, linked to the user message."""
    return Message(
        id=UUID(generate_message_id()),
        content=ml_data.response,
        message_type="system",
        thread_id=thread_uuid,
        user_id=system_user.id,
        query_id=user_message_id,  # Link to the user message we just created
        sequence_number=next_seq,
        citations=citations_data,  # Store citations for system messages only
        usage_metrics=usage_metrics_data,  # Store usage_metrics for system messages only
        is_ai_processed=True,  # System message is the AI response
        ai_processing_time=ai_processing_time_ms,
    )
