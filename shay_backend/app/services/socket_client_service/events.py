"""
Event registration and emission mixin for SocketClientService.

Split out of the former app/services/socket_client_service.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a): this mixin owns
handler registration (on/off), raw emission (emit/force_emit), and the
higher-level `send_*` convenience wrappers used by callers to push
shay_realtime events. Combined with ConnectionMixin and
InternalHandlersMixin by SocketClientService in client.py.
"""

import logging
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from app.core.socket_constants import SOCKET_EVENTS
from app.schemas.socket_events import (
    MessageCreatedData,
    ShayRealtimeData,
    SocketMessage,
    ThreadCreatedData,
)

logger = logging.getLogger(__name__)


class EventEmissionMixin:
    """Event handler registration and message emission."""

    def on(self, event: str, callback: Callable) -> None:
        """
        Register event handler

        Args:
            event: Event name
            callback: Callback function
        """
        if event not in self._event_handlers:
            self._event_handlers[event] = []

        self._event_handlers[event].append(callback)

        # Register with socket if connected
        if self.socket:
            self.socket.on(event, callback)

        logger.debug(f"Registered handler for event: {event}")

    def off(self, event: str, callback: Optional[Callable] = None) -> None:
        """
        Unregister event handler

        Args:
            event: Event name
            callback: Optional specific callback to remove
        """
        if event in self._event_handlers:
            if callback:
                if callback in self._event_handlers[event]:
                    self._event_handlers[event].remove(callback)
            else:
                self._event_handlers[event].clear()

        # Unregister from socket if connected
        if self.socket:
            if callback:
                self.socket.off(event, callback)
            else:
                self.socket.off(event)

        logger.debug(f"Unregistered handler for event: {event}")

    async def emit(self, event: str, data: Optional[Any] = None) -> None:
        """
        Emit event to server

        Args:
            event: Event name
            data: Event data
        """
        if not self.is_socket_connected():
            logger.warning(f"Cannot emit event '{event}' - socket not connected")
            return

        try:
            await self.socket.emit(event, data)
            logger.debug(f"Emitted event: {event}")
        except Exception as e:
            logger.error(f"Failed to emit event '{event}': {e}")

    async def force_emit(self, event: str, data: Optional[Any] = None) -> bool:
        """
        Force emit event, attempt reconnection if needed

        Args:
            event: Event name
            data: Event data

        Returns:
            True if event was emitted successfully
        """
        if not self.is_socket_connected():
            logger.info(f"Socket not connected, attempting reconnection for event: {event}")
            if not await self.ensure_connection():
                logger.error(f"Failed to reconnect, cannot emit event: {event}")
                return False

        try:
            await self.emit(event, data)
            return True
        except Exception as e:
            logger.error(f"Failed to force emit event '{event}': {e}")
            return False

    async def send_socket_message(self, event_data: Dict[str, Any]) -> bool:
        """
        Send custom socket message

        Args:
            event_data: Message data dictionary

        Returns:
            True if message was sent successfully
        """
        try:
            # Create socket message
            message = SocketMessage(
                event=event_data.get("event", "message"),
                data=event_data.get("data"),
                room=event_data.get("room"),
                namespace=event_data.get("namespace"),
                id=str(uuid4()),
            )

            # Emit message
            await self.emit(message.event, message.dict())
            return True

        except Exception as e:
            logger.error(f"Failed to send socket message: {e}")
            return False

    async def send_shay_realtime_event(self, event_type: str, payload: Dict[str, Any], **kwargs) -> bool:
        """
        Send custom shay_realtime event

        Args:
            event_type: Type of realtime event
            payload: Event payload
            **kwargs: Additional parameters (user_id, workspace_id, etc.)

        Returns:
            True if event was sent successfully
        """
        try:
            realtime_data = ShayRealtimeData(event_type=event_type, payload=payload, **kwargs)

            await self.emit(SOCKET_EVENTS["SHAY_REALTIME"], realtime_data.dict())
            return True

        except Exception as e:
            logger.error(f"Failed to send shay_realtime event: {e}")
            return False

    async def send_thread_created_event(self, channel_id: str, thread_id: str) -> bool:
        """
        Send thread created event with type 8

        Args:
            channel_id: Channel ID where thread was created
            thread_id: ID of the created thread

        Returns:
            True if event was sent successfully
        """
        try:
            thread_data = ThreadCreatedData(channelId=channel_id, threadId=thread_id)

            event_data = {"type": 8, "data": thread_data.dict()}

            await self.emit("shay_realtime", event_data)
            logger.info(f"Thread created event sent: channelId={channel_id}, threadId={thread_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send thread created event: {e}")
            return False

    async def send_message_created_event(self, channel_id: str, thread_id: str, message_id: str) -> bool:
        """
        Send message created event with type 11

        Args:
            channel_id: Channel ID where message was created
            thread_id: Thread ID where message was created
            message_id: ID of the created message

        Returns:
            True if event was sent successfully
        """
        try:
            message_data = MessageCreatedData(channelId=channel_id, threadId=thread_id, messageId=message_id)

            event_data = {"type": 11, "data": message_data.dict()}

            await self.emit("shay_realtime", event_data)
            logger.info(
                f"Message created event sent: channelId={channel_id}, threadId={thread_id}, messageId={message_id}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to send message created event: {e}")
            return False
