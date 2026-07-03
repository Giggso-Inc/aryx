"""
Pydantic schemas for socket events and data models
"""

from datetime import datetime
from typing import Any, Dict, Optional, Union
from pydantic import BaseModel, Field, validator
from app.core.socket_constants import SocketEventType, SocketConnectionState, SocketErrorCodes


class SocketEventData(BaseModel):
    """Base schema for socket event data"""
    type: int = Field(..., description="Event type from SocketEventType enum")
    data: Any = Field(None, description="Event payload data")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Event timestamp")
    correlation_id: Optional[str] = Field(None, description="Correlation ID for tracking")
    source: Optional[str] = Field(None, description="Event source identifier")
    
    @validator('type')
    def validate_event_type(cls, v):
        """Validate that type is a valid SocketEventType"""
        if v not in [event_type.value for event_type in SocketEventType]:
            raise ValueError(f"Invalid event type: {v}")
        return v


class ConnectionStatus(BaseModel):
    """Schema for socket connection status"""
    connected: bool = Field(..., description="Whether socket is connected")
    socket_id: Optional[str] = Field(None, description="Socket ID from server")
    has_socket: bool = Field(..., description="Whether socket instance exists")
    state: int = Field(..., description="Connection state from SocketConnectionState enum")
    last_heartbeat: Optional[datetime] = Field(None, description="Last heartbeat timestamp")
    connection_attempts: int = Field(0, description="Number of connection attempts")
    last_error: Optional[str] = Field(None, description="Last error message")
    
    @validator('state')
    def validate_state(cls, v):
        """Validate that state is a valid SocketConnectionState"""
        if v not in [state.value for state in SocketConnectionState]:
            raise ValueError(f"Invalid connection state: {v}")
        return v


class SocketError(BaseModel):
    """Schema for socket errors"""
    code: int = Field(..., description="Error code from SocketErrorCodes enum")
    message: str = Field(..., description="Error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Error timestamp")
    retry_count: int = Field(0, description="Number of retry attempts")
    
    @validator('code')
    def validate_error_code(cls, v):
        """Validate that code is a valid SocketErrorCodes"""
        if v not in [code.value for code in SocketErrorCodes]:
            raise ValueError(f"Invalid error code: {v}")
        return v


class HeartbeatData(BaseModel):
    """Schema for heartbeat data"""
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Heartbeat timestamp")
    client_id: Optional[str] = Field(None, description="Client identifier")
    server_time: Optional[datetime] = Field(None, description="Server timestamp")
    latency: Optional[int] = Field(None, description="Round-trip latency in milliseconds")


class ShayRealtimeData(BaseModel):
    """Schema for custom shay_realtime events"""
    event_type: str = Field(..., description="Type of realtime event")
    payload: Dict[str, Any] = Field(..., description="Event payload")
    user_id: Optional[str] = Field(None, description="User ID if applicable")
    workspace_id: Optional[str] = Field(None, description="Workspace ID if applicable")
    channel_id: Optional[str] = Field(None, description="Channel ID if applicable")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Event timestamp")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class SocketMessage(BaseModel):
    """Schema for general socket messages"""
    event: str = Field(..., description="Event name")
    data: Union[Dict[str, Any], list, str, int, float, bool] = Field(None, description="Message data")
    room: Optional[str] = Field(None, description="Room/channel identifier")
    namespace: Optional[str] = Field(None, description="Socket namespace")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Message timestamp")
    id: Optional[str] = Field(None, description="Message ID for tracking")


class ReconnectionConfig(BaseModel):
    """Schema for reconnection configuration"""
    enabled: bool = Field(True, description="Whether reconnection is enabled")
    max_attempts: int = Field(10, description="Maximum reconnection attempts")
    delay: int = Field(1000, description="Initial delay in milliseconds")
    max_delay: int = Field(5000, description="Maximum delay in milliseconds")
    backoff_factor: float = Field(2.0, description="Exponential backoff factor")
    timeout: int = Field(10000, description="Connection timeout in milliseconds")


class ThreadCreatedData(BaseModel):
    """Schema for thread creation event data"""
    channelId: str = Field(..., description="Channel ID where thread was created")
    threadId: str = Field(..., description="ID of the created thread")


class MessageCreatedData(BaseModel):
    """Schema for message creation event data"""
    channelId: str = Field(..., description="Channel ID where message was created")
    threadId: str = Field(..., description="Thread ID where message was created")
    messageId: str = Field(..., description="ID of the created message")


class MLAPIResponseData(BaseModel):
    """Schema for ML API response event data"""
    channelId: str = Field(..., description="Channel ID where datasource was processed")
    status: int = Field(..., description="Status code: 2 = success, 3 = failure")
    datasourceId: str = Field(..., description="ID of the processed datasource")


class SocketConfig(BaseModel):
    """Schema for socket configuration"""
    server_url: str = Field(..., description="Socket server URL")
    namespace: Optional[str] = Field(None, description="Socket namespace")
    transports: list[str] = Field(default=['websocket', 'polling'], description="Transport methods")
    timeout: int = Field(10000, description="Connection timeout")
    reconnection: ReconnectionConfig = Field(default_factory=ReconnectionConfig, description="Reconnection settings")
    heartbeat_interval: int = Field(30000, description="Heartbeat interval in milliseconds")
    heartbeat_timeout: int = Field(60000, description="Heartbeat timeout in milliseconds")
    auto_connect: bool = Field(True, description="Whether to auto-connect on initialization")
    auth_token: Optional[str] = Field(None, description="Authentication token")
    headers: Optional[Dict[str, str]] = Field(None, description="Additional headers")
    query_params: Optional[Dict[str, str]] = Field(None, description="Query parameters")

