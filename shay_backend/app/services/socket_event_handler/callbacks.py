"""
Socket.io callback handlers (connect/disconnect/heartbeat/message/etc.) for
SocketEventHandler.

Split out of the former app/services/socket_event_handler.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a). This mixin owns
registering the low-level socket.io callbacks and translating them into
internal `_emit_event` calls. Combined with ProcessingMixin and QueueMixin
by SocketEventHandler in handler.py.
"""

import logging
from datetime import datetime
from typing import Any

from app.core.socket_constants import SOCKET_EVENTS, SocketErrorCodes, SocketEventType
from app.schemas.socket_events import HeartbeatData, ShayRealtimeData, SocketError

logger = logging.getLogger(__name__)


class SocketCallbacksMixin:
    """Registers and implements the socket.io-facing event callbacks."""

    async def _setup_connection_handlers(self) -> None:
        """Setup connection-related event handlers"""
        # Connect handler
        self.socket_service.on("connect", self.handle_connect)

        # Disconnect handler
        self.socket_service.on("disconnect", self.handle_disconnect)

        # Connection error handler
        self.socket_service.on("connect_error", self.handle_connect_error)

        # Reconnect handler
        self.socket_service.on("reconnect", self.handle_reconnect)

        logger.debug("Connection handlers setup completed")

    async def _setup_custom_handlers(self) -> None:
        """Setup custom event handlers"""
        # Heartbeat handler
        self.socket_service.on(SOCKET_EVENTS["HEARTBEAT"], self.handle_heartbeat)

        # Error handler
        self.socket_service.on(SOCKET_EVENTS["ERROR"], self.handle_error)

        # Shay realtime handler
        self.socket_service.on(SOCKET_EVENTS["SHAY_REALTIME"], self.handle_shay_realtime)

        # Message handler
        self.socket_service.on(SOCKET_EVENTS["MESSAGE"], self.handle_message)

        logger.debug("Custom handlers setup completed")

    async def handle_connect(self) -> None:
        """Handle connection established"""
        try:
            logger.info("Socket connection established")

            # Process any queued events
            await self._process_queued_events()

            # Emit connection event
            await self._emit_event(
                SocketEventType.CONNECT,
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "socket_id": self.socket_service._socket_id,
                },
            )

        except Exception as e:
            logger.error(f"Error in connect handler: {e}")

    async def handle_disconnect(self) -> None:
        """Handle disconnection"""
        try:
            logger.info("Socket disconnected")

            # Emit disconnect event
            await self._emit_event(
                SocketEventType.DISCONNECT,
                {"timestamp": datetime.utcnow().isoformat(), "reason": "disconnected"},
            )

        except Exception as e:
            logger.error(f"Error in disconnect handler: {e}")

    async def handle_connect_error(self, error: Any) -> None:
        """Handle connection error"""
        try:
            error_message = str(error) if error else "Unknown connection error"
            logger.error(f"Socket connection error: {error_message}")

            # Create socket error
            socket_error = SocketError(
                code=SocketErrorCodes.CONNECTION_FAILED,
                message=error_message,
                timestamp=datetime.utcnow(),
            )

            # Emit error event
            await self._emit_event(SocketEventType.CONNECTION_ERROR, socket_error.dict())

        except Exception as e:
            logger.error(f"Error in connect_error handler: {e}")

    async def handle_reconnect(self) -> None:
        """Handle reconnection"""
        try:
            logger.info("Socket reconnected")

            # Emit reconnect event
            await self._emit_event(
                SocketEventType.RECONNECT,
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "socket_id": self.socket_service._socket_id,
                },
            )

        except Exception as e:
            logger.error(f"Error in reconnect handler: {e}")

    async def handle_heartbeat(self, data: Any) -> None:
        """Handle heartbeat response"""
        try:
            logger.debug("Received heartbeat response")

            # Update last heartbeat
            self.socket_service._last_heartbeat = datetime.utcnow()

            # Process heartbeat data
            if isinstance(data, dict):
                heartbeat_data = HeartbeatData(**data)
            else:
                heartbeat_data = HeartbeatData()

            # Emit heartbeat event
            await self._emit_event(SocketEventType.HEARTBEAT, heartbeat_data.dict())

        except Exception as e:
            logger.error(f"Error in heartbeat handler: {e}")

    async def handle_error(self, error: Any) -> None:
        """Handle socket error"""
        try:
            error_message = str(error) if error else "Unknown socket error"
            logger.error(f"Socket error: {error_message}")

            # Create socket error
            socket_error = SocketError(
                code=SocketErrorCodes.UNKNOWN_ERROR,
                message=error_message,
                timestamp=datetime.utcnow(),
            )

            # Emit error event
            await self._emit_event(SocketEventType.ERROR, socket_error.dict())

        except Exception as e:
            logger.error(f"Error in error handler: {e}")

    async def handle_shay_realtime(self, data: Any) -> None:
        """Handle shay_realtime events"""
        try:
            logger.debug(f"Received shay_realtime event: {data}")

            # Process realtime data
            if isinstance(data, dict):
                realtime_data = ShayRealtimeData(**data)
            else:
                realtime_data = ShayRealtimeData(event_type="unknown", payload=data or {})

            # Emit realtime event
            await self._emit_event(SocketEventType.SHAY_REALTIME, realtime_data.dict())

        except Exception as e:
            logger.error(f"Error in shay_realtime handler: {e}")

    async def handle_message(self, data: Any) -> None:
        """Handle general messages"""
        try:
            logger.debug(f"Received message: {data}")

            # Emit message event
            await self._emit_event(
                SocketEventType.MESSAGE, {"data": data, "timestamp": datetime.utcnow().isoformat()}
            )

        except Exception as e:
            logger.error(f"Error in message handler: {e}")
