"""
Processor/middleware registration and internal event dispatch for
SocketEventHandler.

Split out of the former app/services/socket_event_handler.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a). This mixin owns
the internal pub/sub layer: registering event processors and middleware,
and running `_emit_event` through the middleware chain before dispatching
to registered processors. Combined with SocketCallbacksMixin and QueueMixin
by SocketEventHandler in handler.py.
"""

import logging
from typing import Any, Callable
from uuid import uuid4
from datetime import datetime

from app.core.socket_constants import SocketEventType
from app.schemas.socket_events import SocketEventData

logger = logging.getLogger(__name__)


class ProcessingMixin:
    """Event-processor/middleware registration and internal dispatch."""

    def register_event_processor(self, event_type: str, processor: Callable) -> None:
        """
        Register event processor for specific event type

        Args:
            event_type: Event type to process
            processor: Processor function
        """
        if event_type not in self._event_processors:
            self._event_processors[event_type] = []

        self._event_processors[event_type].append(processor)
        logger.debug(f"Registered processor for event type: {event_type}")

    def unregister_event_processor(self, event_type: str, processor: Callable = None) -> None:
        """
        Unregister event processor

        Args:
            event_type: Event type
            processor: Specific processor to remove (None to remove all)
        """
        if event_type in self._event_processors:
            if processor:
                if processor in self._event_processors[event_type]:
                    self._event_processors[event_type].remove(processor)
            else:
                self._event_processors[event_type].clear()

        logger.debug(f"Unregistered processor for event type: {event_type}")

    def add_middleware(self, middleware: Callable) -> None:
        """
        Add middleware for event processing

        Args:
            middleware: Middleware function
        """
        self._middleware.append(middleware)
        logger.debug("Added event middleware")

    def remove_middleware(self, middleware: Callable) -> None:
        """
        Remove middleware

        Args:
            middleware: Middleware function to remove
        """
        if middleware in self._middleware:
            self._middleware.remove(middleware)
        logger.debug("Removed event middleware")

    def register_error_handler(self, error_type: str, handler: Callable) -> None:
        """
        Register error handler for specific error type

        Args:
            error_type: Error type
            handler: Error handler function
        """
        self._error_handlers[error_type] = handler
        logger.debug(f"Registered error handler for type: {error_type}")

    async def _emit_event(self, event_type: SocketEventType, data: Any) -> None:
        """
        Emit internal event

        Args:
            event_type: Event type
            data: Event data
        """
        try:
            # Create event data
            event_data = SocketEventData(
                type=event_type.value,
                data=data,
                timestamp=datetime.utcnow(),
                correlation_id=str(uuid4()),
            )

            # Process through middleware
            processed_data = await self._process_through_middleware(event_data)

            # Process with registered processors
            await self._process_with_processors(event_type.name.lower(), processed_data)

        except Exception as e:
            logger.error(f"Error emitting event: {e}")

    async def _process_through_middleware(self, event_data: SocketEventData) -> SocketEventData:
        """
        Process event through middleware

        Args:
            event_data: Event data to process

        Returns:
            Processed event data
        """
        processed_data = event_data

        for middleware in self._middleware:
            try:
                processed_data = await middleware(processed_data)
            except Exception as e:
                logger.error(f"Error in middleware: {e}")

        return processed_data

    async def _process_with_processors(self, event_type: str, event_data: SocketEventData) -> None:
        """
        Process event with registered processors

        Args:
            event_type: Event type
            event_data: Event data
        """
        if event_type in self._event_processors:
            for processor in self._event_processors[event_type]:
                try:
                    await processor(event_data)
                except Exception as e:
                    logger.error(f"Error in event processor: {e}")
