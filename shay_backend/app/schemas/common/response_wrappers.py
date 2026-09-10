"""
Generic standardized API response wrappers.

Split out of the former app/schemas/common.py to keep each file under the
Raven 150-line style limit.
"""

from typing import Generic, TypeVar, Optional, Any
from pydantic import BaseModel, Field

DataT = TypeVar('DataT')


class StandardResponse(BaseModel, Generic[DataT]):
    """Standard API response wrapper."""
    success: bool = Field(..., description="Whether the request was successful")
    data: Optional[DataT] = Field(None, description="Response data")
    message: str = Field(..., description="Response message")
    code: int = Field(..., description="HTTP status code")


class SuccessResponse(StandardResponse[DataT]):
    """Success response wrapper."""
    success: bool = Field(True, description="Request was successful")
    code: int = Field(200, description="HTTP 200 status code")


class ErrorResponse(BaseModel):
    """Error response wrapper."""
    success: bool = Field(False, description="Request failed")
    data: Optional[Any] = Field(None, description="Error details")
    message: str = Field(..., description="Error message")
    code: int = Field(..., description="HTTP error status code")
