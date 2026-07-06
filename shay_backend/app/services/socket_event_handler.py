"""
Socket Event Handler - Manages socket events and provides event processing capabilities
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from app.core.socket_constants import SocketEventType, SocketErrorCodes, SOCKET_EVENTS
from app.schemas.socket_events import (
    SocketEventData, 
    SocketError, 
    ConnectionStatus,
    ShayRealtimeData,
    HeartbeatData
)
from app.services.socket_client_service import SocketClientService

logger = logging.getLogger(__name__)


class SocketEventHandler:
    """
    Handles socket events and provides event processing capabilities
    """
    
    def __init__(self, socket_service: SocketClientService):
        self.socket_service = socket_service
        self._event_processors: Dict[str, List[Callable]] = {}
        self._middleware: List[Callable] = []
        self._error_handlers: Dict[str, Callable] = {}
        self._event_queue: List[Dict[str, Any]] = []
        self._queue_processor_task: Optional[asyncio.Task] = None
        self._is_processing = False
        
    async def setup_event_handlers(self) -> None:
        """Setup all event handlers"""
        try:
            # Setup core event handlers
            await self._setup_connection_handlers()
            await self._setup_custom_handlers()
            await self._setup_error_handlers()
            
            # Start event queue processor
            await self._start_queue_processor()
            
            logger.info("Socket event handlers setup completed")
            
        except Exception as e:
            logger.error(f"Failed to setup event handlers: {e}")
            raise
    
    async def _setup_connection_handlers(self) -> None:
        """Setup connection-related event handlers"""
        # Connect handler
        self.socket_service.on('connect', self.handle_connect)
        
        # Disconnect handler
        self.socket_service.on('disconnect', self.handle_disconnect)
        
        # Connection error handler
        self.socket_service.on('connect_error', self.handle_connect_error)
        
        # Reconnect handler
        self.socket_service.on('reconnect', self.handle_reconnect)
        
        logger.debug("Connection handlers setup completed")
    
    async def _setup_custom_handlers(self) -> None:
        """Setup custom event handlers"""
        # Heartbeat handler
        self.socket_service.on(SOCKET_EVENTS['HEARTBEAT'], self.handle_heartbeat)
        
        # Error handler
        self.socket_service.on(SOCKET_EVENTS['ERROR'], self.handle_error)
        
        # Shay realtime handler
        self.socket_service.on(SOCKET_EVENTS['SHAY_REALTIME'], self.handle_shay_realtime)
        
        # Message handler
        self.socket_service.on(SOCKET_EVENTS['MESSAGE'], self.handle_message)
        
        logger.debug("Custom handlers setup completed")
    
    async def _setup_error_handlers(self) -> None:
        """Setup error handlers"""
        # Default error handler
        self._error_handlers['default'] = self._default_error_handler
        
        # Specific error handlers
        self._error_handlers['connection'] = self._connection_error_handler
        self._error_handlers['authentication'] = self._authentication_error_handler
        self._error_handlers['timeout'] = self._timeout_error_handler
        
        logger.debug("Error handlers setup completed")
    
    async def handle_connect(self) -> None:
        """Handle connection established"""
        try:
            logger.info("Socket connection established")
            
            # Process any queued events
            await self._process_queued_events()
            
            # Emit connection event
            await self._emit_event(SocketEventType.CONNECT, {
                'timestamp': datetime.utcnow().isoformat(),
                'socket_id': self.socket_service._socket_id
            })
            
        except Exception as e:
            logger.error(f"Error in connect handler: {e}")
    
    async def handle_disconnect(self) -> None:
        """Handle disconnection"""
        try:
            logger.info("Socket disconnected")
            
            # Emit disconnect event
            await self._emit_event(SocketEventType.DISCONNECT, {
                'timestamp': datetime.utcnow().isoformat(),
                'reason': 'disconnected'
            })
            
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
                timestamp=datetime.utcnow()
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
            await self._emit_event(SocketEventType.RECONNECT, {
                'timestamp': datetime.utcnow().isoformat(),
                'socket_id': self.socket_service._socket_id
            })
            
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
                timestamp=datetime.utcnow()
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
                realtime_data = ShayRealtimeData(
                    event_type="unknown",
                    payload=data or {}
                )
            
            # Emit realtime event
            await self._emit_event(SocketEventType.SHAY_REALTIME, realtime_data.dict())
            
        except Exception as e:
            logger.error(f"Error in shay_realtime handler: {e}")
    
    async def handle_message(self, data: Any) -> None:
        """Handle general messages"""
        try:
            logger.debug(f"Received message: {data}")
            
            # Emit message event
            await self._emit_event(SocketEventType.MESSAGE, {
                'data': data,
                'timestamp': datetime.utcnow().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error in message handler: {e}")
    
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
                correlation_id=str(uuid4())
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
            event_type = event.get('type')
            data = event.get('data')
            
            if event_type == 'emit':
                await self.socket_service.emit(data.get('event'), data.get('payload'))
            elif event_type == 'shay_realtime':
                await self.socket_service.send_shay_realtime_event(
                    data.get('event_type'),
                    data.get('payload'),
                    **data.get('kwargs', {})
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
        self._event_queue.append({
            'type': event_type,
            'data': data,
            'timestamp': datetime.utcnow().isoformat()
        })
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


# Global event handler instance
socket_event_handler: Optional[SocketEventHandler] = None


def get_socket_event_handler() -> Optional[SocketEventHandler]:
    """Get global socket event handler instance"""
    return socket_event_handler


async def initialize_socket_event_handler(socket_service: SocketClientService) -> SocketEventHandler:
    """Initialize socket event handler"""
    global socket_event_handler
    
    if socket_event_handler is None:
        socket_event_handler = SocketEventHandler(socket_service)
        await socket_event_handler.setup_event_handlers()
    
    return socket_event_handler

