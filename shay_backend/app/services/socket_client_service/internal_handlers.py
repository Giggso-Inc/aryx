"""
Internal socket.io callback handlers and heartbeat/retry machinery for
SocketClientService.

Split out of the former app/services/socket_client_service.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a): this mixin owns
the private `_on_*` callbacks registered with the underlying socket.io
client, the heartbeat background task, and the generic retry helper.
Combined with ConnectionMixin and EventEmissionMixin by SocketClientService
in client.py.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.socket_constants import SOCKET_EVENTS, SocketConnectionState
from app.schemas.socket_events import HeartbeatData

logger = logging.getLogger(__name__)


class InternalHandlersMixin:
    """Private socket.io callbacks, heartbeat loop, and retry helper."""

    async def _setup_default_handlers(self) -> None:
        """Setup default event handlers"""
        if not self.socket:
            return

        # Connection handlers
        self.socket.on("connect", self._on_connect)
        self.socket.on("disconnect", self._on_disconnect)
        self.socket.on("connect_error", self._on_connect_error)

        # Custom handlers
        self.socket.on(SOCKET_EVENTS["HEARTBEAT"], self._on_heartbeat)
        self.socket.on(SOCKET_EVENTS["ERROR"], self._on_error)

    async def _on_connect(self) -> None:
        """Handle connection established"""
        logger.info("Socket connected")
        self.is_connected = True
        self._connection_state = SocketConnectionState.CONNECTED
        self._socket_id = self.socket.sid if self.socket else None
        self._connection_attempts = 0
        self._last_error = None

    async def _on_disconnect(self) -> None:
        """Handle disconnection"""
        logger.info("Socket disconnected")
        self.is_connected = False
        self._connection_state = SocketConnectionState.DISCONNECTED
        self._socket_id = None
        await self._stop_heartbeat()

    async def _on_connect_error(self, error) -> None:
        """Handle connection error"""
        logger.error(f"Socket connection error: {error}")
        self._connection_state = SocketConnectionState.ERROR
        self._last_error = str(error)
        self.is_connected = False

    async def _on_heartbeat(self, data) -> None:
        """Handle heartbeat response"""
        self._last_heartbeat = datetime.utcnow()
        logger.debug("Received heartbeat response")

    async def _on_error(self, error) -> None:
        """Handle socket error"""
        logger.error(f"Socket error: {error}")
        self._last_error = str(error)

    async def _start_heartbeat(self) -> None:
        """Start heartbeat task"""
        if self._heartbeat_task and not self._heartbeat_task.done():
            return

        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.debug("Started heartbeat task")

    async def _stop_heartbeat(self) -> None:
        """Stop heartbeat task"""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        self._heartbeat_task = None
        logger.debug("Stopped heartbeat task")

    async def _heartbeat_loop(self) -> None:
        """Heartbeat loop"""
        while self.is_connected and self.socket:
            try:
                heartbeat_data = HeartbeatData(client_id=self._socket_id, timestamp=datetime.utcnow())

                # Convert datetime to ISO format for JSON serialization
                heartbeat_dict = heartbeat_data.dict()
                if "timestamp" in heartbeat_dict and isinstance(heartbeat_dict["timestamp"], datetime):
                    heartbeat_dict["timestamp"] = heartbeat_dict["timestamp"].isoformat()

                await self.emit(SOCKET_EVENTS["HEARTBEAT"], heartbeat_dict)
                await asyncio.sleep(self._settings.SOCKET_HEARTBEAT_INTERVAL / 1000)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(5)  # Wait before retrying

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def _retry_operation(self, operation: Callable, *args, **kwargs) -> Any:
        """Retry operation with exponential backoff"""
        return await operation(*args, **kwargs)
