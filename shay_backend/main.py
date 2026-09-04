"""
Log Analyzer Backend - Main Application Entry Point

This module serves as the main entry point for the FastAPI application,
configuring routes, middleware, and OpenAPI documentation.

File: main.py
Version: 1.0.0
Author: Karthick Chandrasekar
Date: 18-08-2025

Features:
- FastAPI application configuration
- Route registration for all API endpoints
- OpenAPI documentation with custom tags
- CORS and middleware configuration
- Health check endpoints
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

from app.core.config import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper()),
    format=settings.LOG_FORMAT,
    force=True  # Force reconfiguration of logging
)

# Test logging configuration
logger = logging.getLogger(__name__)
logger.info("🔧 Logging configuration initialized - LOG_LEVEL: %s", settings.LOG_LEVEL)

# Reduce httpx logging verbosity
logging.getLogger("httpx").setLevel(logging.WARNING)
from app.core.migrations import run_migrations
from app.core.socket import initialize_socket_service, cleanup_socket_service

from app.core.app_middleware import register_middleware
from app.core.app_exception_handlers import register_exception_handlers
from app.core.app_openapi import OPENAPI_TAGS, register_openapi
from app.core.app_routers import register_routers

from app.services.daily_summary_scheduler import daily_summary_scheduler



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("Starting Log Analyzer Backend...")

    # Run database migrations
    if os.environ.get("SHAY_RUN_MIGRATIONS", "true").lower() == "true":
        try:
            migration_success = await run_migrations()
            if not migration_success:
                logger.warning("Database migrations failed, but continuing with application startup")
        except Exception as e:
            logger.error("Error during migration", exc_info=e)
            logger.warning("Continuing with application startup despite migration issues")
    elif os.environ.get("SHAY_INIT_DB", "false").lower() == "true":
        from app.core.database import init_db
        await init_db()
        logger.info("Oracle schema initialised via init_db()")
    else:
        logger.info("Skipping Shay migrations; shared schema is owned by Aryx migrations")

    # Initialize socket service
    socket_service = None
    event_handler = None
    try:
        socket_service, event_handler = await initialize_socket_service()
        if socket_service:
            logger.info("Socket service initialized")
        else:
            logger.warning("Socket service initialization failed, continuing without socket support")
    except Exception as e:
        logger.error("Error initializing socket service", exc_info=e)
        logger.warning("Continuing without socket support")

    # Initialize daily summary email scheduler
    try:
        # Get the current event loop for the scheduler
        import asyncio
        loop = asyncio.get_event_loop()
        daily_summary_scheduler.start()
        logger.info("Daily summary email scheduler initialized")

        # For first-time users, trigger immediately after a short delay
        # This ensures users with last_email_notify_time = NULL get their first email quickly
        async def trigger_first_run():
            await asyncio.sleep(30)  # Wait 30 seconds after startup
            logger.info("[SCHEDULER] Triggering first run check for new users...")
            try:
                await daily_summary_scheduler.process_daily_summaries()
            except Exception as e:
                logger.error("Error in first run", exc_info=e)

        # Schedule first run check
        asyncio.create_task(trigger_first_run())

    except Exception as e:
        logger.error("Error initializing daily summary scheduler", exc_info=e)
        logger.warning("Continuing without daily summary email scheduler")

    logger.info("Application startup complete")

    yield

    # Shutdown
    logger.info("Shutting down Log Analyzer Backend...")

    # Stop daily summary email scheduler
    try:
        daily_summary_scheduler.stop()
        logger.info("Daily summary email scheduler stopped")
    except Exception as e:
        logger.warning("Error stopping daily summary scheduler: %s", e)

    # Cleanup socket service
    if socket_service or event_handler:
        await cleanup_socket_service(socket_service, event_handler)
        logger.info("Socket service cleaned up")


# Create FastAPI application
app = FastAPI(
    title="Log Analyzer Backend",
    description="AI-powered log analysis platform with multi-tenant support",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
    openapi_version="3.0.2",
    openapi_tags=OPENAPI_TAGS,
)

# Middleware (CORS, trusted host, authentication) — see app/core/app_middleware.py
register_middleware(app)

# Global exception handler — see app/core/app_exception_handlers.py
register_exception_handlers(app)

# Custom OpenAPI schema (adds BearerAuth security) — see app/core/app_openapi.py
register_openapi(app)

# Health checks, static file routes, and every API router — see app/core/app_routers.py
register_routers(app)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=settings.DEBUG,
        log_level="info",
        loop="asyncio" if settings.is_oracle else "auto",  # uvloop's TCPTransport lacks setsockopt needed by oracledb thin mode
    ) 
