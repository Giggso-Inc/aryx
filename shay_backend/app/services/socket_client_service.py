"""
Socket Client Service - Main implementation for WebSocket client functionality
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

import socketio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.config import settings
from app.core.socket_constants import SocketConnectionState, SocketErrorCodes, SOCKET_EVENTS
from app.schemas.socket_events import (
    ConnectionStatus, 
    SocketError, 
    SocketMessage, 
    ShayRealtimeData,
    HeartbeatData,
    ThreadCreatedData,
    MessageCreatedData
)

logger = logging.getLogger(__name__)


class SocketClientService:
    """
    Singleton Socket Client Service for managing WebSocket connections
    Provides connection management, event handling, and real-time communication
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.socket: Optional[socketio.AsyncClient] = None
            self.is_connected: bool = False
            self.connection_promise: Optional[asyncio.Future] = None
            self._lock = asyncio.Lock()
            self._event_handlers: Dict[str, List[Callable]] = {}
            self._connection_state = SocketConnectionState.DISCONNECTED
            self._connection_attempts = 0
            self._last_error: Optional[str] = None
            self._last_heartbeat: Optional[datetime] = None
            self._socket_id: Optional[str] = None
            # Use main config settings directly
            self._settings = settings
            self._heartbeat_task: Optional[asyncio.Task] = None
            self._reconnect_task: Optional[asyncio.Task] = None
            self._initialized = True
            logger.info("SocketClientService initialized")
    
    async def connect(self, server_url: Optional[str] = None) -> Optional[socketio.AsyncClient]:
        """
        Connect to socket server
        
        Args:
            server_url: Optional server URL override
            
        Returns:
            SocketIO client instance or None if connection failed
        """
        async with self._lock:
            if self.is_connected and self.socket:
                logger.info("Socket already connected")
                return self.socket
            
            try:
                self._connection_state = SocketConnectionState.CONNECTING
                self._connection_attempts += 1
                
                # Use provided URL or default from settings
                url = server_url or self._settings.SOCKET_SERVER_URL
                
                # Create socket client
                self.socket = socketio.AsyncClient(
                    logger=self._settings.SOCKET_DEBUG,
                    engineio_logger=self._settings.SOCKET_DEBUG
                )
                
                # Setup event handlers
                await self._setup_default_handlers()
                
                # Connection options
                connection_options = {
                    'transports': [t.strip() for t in self._settings.SOCKET_TRANSPORTS.split(",")]
                }
                
                # Add optional parameters
                if self._settings.SOCKET_NAMESPACE:
                    connection_options['namespace'] = self._settings.SOCKET_NAMESPACE
                
                if self._settings.SOCKET_AUTH_TOKEN:
                    connection_options['auth'] = {'token': self._settings.SOCKET_AUTH_TOKEN}
                
                # Note: headers and query_params not available in main config
                
                # Connect to server
                logger.info(f"Connecting to socket server: {url}")
                await self.socket.connect(url, **connection_options)
                
                # Wait for connection to be established
                await asyncio.sleep(0.1)  # Small delay to ensure connection is established
                
                if self.socket.connected:
                    self.is_connected = True
                    self._connection_state = SocketConnectionState.CONNECTED
                    self._socket_id = self.socket.sid
                    self._connection_attempts = 0
                    self._last_error = None
                    
                    # Start heartbeat if enabled
                    if self._settings.SOCKET_HEARTBEAT_INTERVAL > 0:
                        await self._start_heartbeat()
                    
                    logger.info(f"Successfully connected to socket server. Socket ID: {self._socket_id}")
                    return self.socket
                else:
                    raise Exception("Connection failed - socket not connected after connect call")
                    
            except Exception as e:
                self._connection_state = SocketConnectionState.ERROR
                self._last_error = str(e)
                self.is_connected = False
                logger.error(f"Failed to connect to socket server: {e}")
                
                # Cleanup on failure
                if self.socket:
                    await self.socket.disconnect()
                    self.socket = None
                
                return None
    
    async def disconnect(self) -> None:
        """Disconnect from socket server"""
        async with self._lock:
            if not self.is_connected or not self.socket:
                logger.info("Socket not connected, nothing to disconnect")
                return
            
            try:
                # Stop heartbeat
                await self._stop_heartbeat()
                
                # Disconnect socket
                await self.socket.disconnect()
                
                self.is_connected = False
                self._connection_state = SocketConnectionState.DISCONNECTED
                self._socket_id = None
                
                logger.info("Disconnected from socket server")
                
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
            finally:
                self.socket = None
    
    async def force_connect(self, server_url: Optional[str] = None) -> Optional[socketio.AsyncClient]:
        """
        Force connection by disconnecting first if connected
        
        Args:
            server_url: Optional server URL override
            
        Returns:
            SocketIO client instance or None if connection failed
        """
        if self.is_connected:
            await self.disconnect()
        
        return await self.connect(server_url)
    
    async def ensure_connection(self) -> bool:
        """
        Ensure socket is connected, attempt reconnection if needed
        
        Returns:
            True if connected, False otherwise
        """
        if self.is_connected and self.socket and self.socket.connected:
            return True
        
        if not self.is_connected:
            result = await self.connect()
            return result is not None
        
        return False
    
    def get_socket(self) -> Optional[socketio.AsyncClient]:
        """Get current socket instance"""
        return self.socket
    
    def is_socket_connected(self) -> bool:
        """Check if socket is connected"""
        return self.is_connected and self.socket is not None and self.socket.connected
    
    def get_connection_status(self) -> ConnectionStatus:
        """Get detailed connection status"""
        return ConnectionStatus(
            connected=self.is_connected,
            socket_id=self._socket_id,
            has_socket=self.socket is not None,
            state=self._connection_state.value,
            last_heartbeat=self._last_heartbeat,
            connection_attempts=self._connection_attempts,
            last_error=self._last_error
        )
    
    async def wait_for_connection(self, timeout: int = 5000) -> bool:
        """
        Wait for connection to be established
        
        Args:
            timeout: Timeout in milliseconds
            
        Returns:
            True if connected within timeout, False otherwise
        """
        start_time = datetime.utcnow()
        timeout_seconds = timeout / 1000
        
        while (datetime.utcnow() - start_time).total_seconds() < timeout_seconds:
            if self.is_socket_connected():
                return True
            await asyncio.sleep(0.1)
        
        return False
    
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
                event=event_data.get('event', 'message'),
                data=event_data.get('data'),
                room=event_data.get('room'),
                namespace=event_data.get('namespace'),
                id=str(uuid4())
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
            realtime_data = ShayRealtimeData(
                event_type=event_type,
                payload=payload,
                **kwargs
            )
            
            await self.emit(SOCKET_EVENTS['SHAY_REALTIME'], realtime_data.dict())
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
            thread_data = ThreadCreatedData(
                channelId=channel_id,
                threadId=thread_id
            )
            
            event_data = {
                "type": 8,
                "data": thread_data.dict()
            }
            
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
            message_data = MessageCreatedData(
                channelId=channel_id,
                threadId=thread_id,
                messageId=message_id
            )
            
            event_data = {
                "type": 11,
                "data": message_data.dict()
            }
            
            await self.emit("shay_realtime", event_data)
            logger.info(f"Message created event sent: channelId={channel_id}, threadId={thread_id}, messageId={message_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send message created event: {e}")
            return False
    
    async def _setup_default_handlers(self) -> None:
        """Setup default event handlers"""
        if not self.socket:
            return
        
        # Connection handlers
        self.socket.on('connect', self._on_connect)
        self.socket.on('disconnect', self._on_disconnect)
        self.socket.on('connect_error', self._on_connect_error)
        
        # Custom handlers
        self.socket.on(SOCKET_EVENTS['HEARTBEAT'], self._on_heartbeat)
        self.socket.on(SOCKET_EVENTS['ERROR'], self._on_error)
    
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
                heartbeat_data = HeartbeatData(
                    client_id=self._socket_id,
                    timestamp=datetime.utcnow()
                )
                
                # Convert datetime to ISO format for JSON serialization
                heartbeat_dict = heartbeat_data.dict()
                if 'timestamp' in heartbeat_dict and isinstance(heartbeat_dict['timestamp'], datetime):
                    heartbeat_dict['timestamp'] = heartbeat_dict['timestamp'].isoformat()
                
                await self.emit(SOCKET_EVENTS['HEARTBEAT'], heartbeat_dict)
                await asyncio.sleep(self._settings.SOCKET_HEARTBEAT_INTERVAL / 1000)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(5)  # Wait before retrying
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception)
    )
    async def _retry_operation(self, operation: Callable, *args, **kwargs) -> Any:
        """Retry operation with exponential backoff"""
        return await operation(*args, **kwargs)


# Global socket service instance
socket_service = SocketClientService()


def get_socket_service() -> SocketClientService:
    """Get global socket service instance"""
    return socket_service

