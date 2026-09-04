"""
Socket event emission helpers — pure emission only, never raise.

Split out of the original app/routes/messages.py (2,513 lines) as part of
the Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5). Used by almost
every write endpoint in this package (thread/message create, update,
delete, ml-store), so it lives at the package root rather than inside any
one submodule.
"""

from app.services.socket_client_service import get_socket_service


async def emit_message_created_event(channel_id: str, thread_id: str, message_id: str) -> None:
    """
    Emit message created socket event (type 11) - PURE EMISSION ONLY

    Args:
        channel_id: Channel ID where message was created
        thread_id: Thread ID where message was created
        message_id: ID of the created message
    """
    try:
        socket_service = get_socket_service()
        if socket_service and socket_service.is_socket_connected():
            await socket_service.send_message_created_event(
                channel_id=channel_id,
                thread_id=thread_id,
                message_id=message_id
            )
        else:
            # Queue the event if socket is not connected
            from app.services.socket_event_handler import get_socket_event_handler
            event_handler = get_socket_event_handler()
            if event_handler:
                event_data = {
                    "type": 11,
                    "data": {
                        "channelId": channel_id,
                        "threadId": thread_id,
                        "messageId": message_id
                    }
                }
                event_handler.queue_event("shay_realtime", event_data)
    except Exception as e:
        print(f"Error emitting message created event: {e}")


async def emit_thread_created_event(channel_id: str, thread_id: str) -> None:
    """
    Emit thread created socket event (type 8) - PURE EMISSION ONLY

    Args:
        channel_id: Channel ID where thread was created
        thread_id: ID of the created thread
    """
    try:
        socket_service = get_socket_service()
        if socket_service and socket_service.is_socket_connected():
            await socket_service.send_thread_created_event(
                channel_id=channel_id,
                thread_id=thread_id
            )
        else:
            # Queue the event if socket is not connected
            from app.services.socket_event_handler import get_socket_event_handler
            event_handler = get_socket_event_handler()
            if event_handler:
                event_data = {
                    "type": 8,
                    "data": {
                        "channelId": channel_id,
                        "threadId": thread_id
                    }
                }
                event_handler.queue_event("shay_realtime", event_data)
    except Exception as e:
        print(f"Error emitting thread created event: {e}")
