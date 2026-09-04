"""
Error-handler setup, event queue processing, and cleanup for
SocketEventHandler.

Split out of the former app/services/socket_event_handler.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a). This mixin owns
the background queue-processor task (for events queued while disconnected),
the default/connection/authentication/timeout error handlers, and resource
cleanup. Combined with SocketCallbacksMixin and ProcessingMixin by
SocketEventHandler in handler.py.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict

from app.schemas.socket_events import SocketError

logger = logging.getLogger(__name__)


class QueueMixin:
    """Event queue processor lifecycle, error handlers, and cleanup."""

    async def _setup_error_handlers(self) -> None:
        """Setup error handlers"""
        # Default error handler
        self._error_handlers["default"] = self._default_error_handler

        # Specific error handlers
        self._error_handlers["connection"] = self._connection_error_handler
        self._error_handlers["authentication"] = self._authentication_error_handler
        self._error_handlers["timeout"] = self._timeout_error_handler

        logger.debug("Error handlers setup completed")

    async def _start_queue_processor(self) -> None:
        """Start event queue processor"""
        if self._queue_processor_task and not self._queue_processor_task.done():
            return

        self._queue_processor_task = asyncio.create_task(self._queue_processor_loop())
        logger.debug("Started event queue processor")

    async def _stop_queue_processor(self) -> None:
        """Stop event queue processor"""
        if self._queue_processor_task and not self._queue_processor_task.done():
            self._queue_processor_task.cancel()
            try:
                await self._queue_processor_task
            except asyncio.CancelledError:
                pass
        self._queue_processor_task = None
        logger.debug("Stopped event queue processor")

    async def _queue_processor_loop(self) -> None:
        """Event queue processor loop"""
        while True:
            try:
                if self._event_queue and not self._is_processing:
                    self._is_processing = True
                    await self._process_queued_events()
                    self._is_processing = False

                await asyncio.sleep(0.1)  # Small delay to prevent busy waiting

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in queue processor: {e}")
                self._is_processing = False
                await asyncio.sleep(1)

    async def _process_queued_events(self) -> None:
        """Process queued events"""
        while self._event_queue:
            try:
                event = self._event_queue.pop(0)
                await self._process_event(event)
            except Exception as e:
                logger.error(f"Error processing queued event: {e}")

    async def _process_event(self, event: Dict[str, Any]) -> None:
        """Process individual event"""
        try:
            event_type = event.get("type")
            data = event.get("data")

            if event_type == "emit":
                await self.socket_service.emit(data.get("event"), data.get("payload"))
            elif event_type == "shay_realtime":
                await self.socket_service.send_shay_realtime_event(
                    data.get("event_type"), data.get("payload"), **data.get("kwargs", {})
                )

        except Exception as e:
            logger.error(f"Error processing event: {e}")

    def queue_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Queue event for processing when connected

        Args:
            event_type: Type of event
            data: Event data
        """
        self._event_queue.append(
            {"type": event_type, "data": data, "timestamp": datetime.utcnow().isoformat()}
        )
        logger.debug(f"Queued event: {event_type}")

    async def _default_error_handler(self, error: SocketError) -> None:
        """Default error handler"""
        logger.error(f"Socket error: {error.message}")

    async def _connection_error_handler(self, error: SocketError) -> None:
        """Connection error handler"""
        logger.error(f"Connection error: {error.message}")
        # Attempt reconnection
        await self.socket_service.ensure_connection()

    async def _authentication_error_handler(self, error: SocketError) -> None:
        """Authentication error handler"""
        logger.error(f"Authentication error: {error.message}")
        # Handle authentication failure

    async def _timeout_error_handler(self, error: SocketError) -> None:
        """Timeout error handler"""
        logger.error(f"Timeout error: {error.message}")
        # Handle timeout

    async def cleanup(self) -> None:
        """Cleanup event handler resources"""
        try:
            await self._stop_queue_processor()
            self._event_processors.clear()
            self._middleware.clear()
            self._error_handlers.clear()
            self._event_queue.clear()
            logger.info("Socket event handler cleaned up")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
