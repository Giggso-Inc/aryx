"""
Global exception handler registration for the FastAPI application.

Extracted from main.py during Raven Phase 5a file-size compliance work.
Called once from main.py via `register_exception_handlers(app)`.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the global unhandled-exception handler to `app`."""

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Global exception handler"""
        logger.exception("Unhandled exception on %s", request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "message": "An unexpected error occurred",
                "path": request.url.path
            }
        )
