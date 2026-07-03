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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
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
from app.core.socket import initialize_socket_service, cleanup_socket_service, get_socket_health_status

from app.routes import auth_router, companies, users, workspaces_router, channels_router, messages_router, attachments_router, agent_router, apps_router, app_accounts_router, datasources, user_auth, tasks_router, checklists_router, approvals_router, subscription_plans, subscriptions, public_router, payment_gateway_router, notifications_router, support_router, template, token_details, shortener,  audit, threads_router, gg_datasources_router, gg_app_connections_router, gg_workspaces_router, gg_channels_router, sso_router
from app.routes.sso import router as sso_router
from app.routes.gmail_connect import router as gmail_connect_router
from app.routes.zoho_connect import router as zoho_connect_router
from app.routes.sf_connect import router as sf_connect_router
from app.routes.odoo_connect import router as odoo_connect_router

from app.middleware.auth_middleware import AuthMiddleware
from app.services.daily_summary_scheduler import daily_summary_scheduler



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    print("🚀 Starting Log Analyzer Backend...")
    
    # Run database migrations
    if os.environ.get("SHAY_RUN_MIGRATIONS", "true").lower() == "true":
        try:
            migration_success = await run_migrations()
            if not migration_success:
                print("⚠️ Database migrations failed, but continuing with application startup")
        except Exception as e:
            print(f"❌ Error during migration: {str(e)}")
            print("⚠️ Continuing with application startup despite migration issues")
    else:
        print("⏭️ Skipping Shay migrations; shared schema is owned by Aryx migrations")
    
    # Initialize socket service
    socket_service = None
    event_handler = None
    try:
        socket_service, event_handler = await initialize_socket_service()
        if socket_service:
            print("✅ Socket service initialized")
        else:
            print("⚠️ Socket service initialization failed, continuing without socket support")
    except Exception as e:
        print(f"❌ Error initializing socket service: {str(e)}")
        print("⚠️ Continuing without socket support")
    
    # Initialize daily summary email scheduler
    try:
        # Get the current event loop for the scheduler
        import asyncio
        loop = asyncio.get_event_loop()
        daily_summary_scheduler.start()
        print("✅ Daily summary email scheduler initialized")
        
        # For first-time users, trigger immediately after a short delay
        # This ensures users with last_email_notify_time = NULL get their first email quickly
        async def trigger_first_run():
            await asyncio.sleep(30)  # Wait 30 seconds after startup
            print("🔄 [SCHEDULER] Triggering first run check for new users...")
            try:
                await daily_summary_scheduler.process_daily_summaries()
            except Exception as e:
                print(f"❌ Error in first run: {e}")
        
        # Schedule first run check
        asyncio.create_task(trigger_first_run())
        
    except Exception as e:
        print(f"❌ Error initializing daily summary scheduler: {str(e)}")
        import traceback
        print(traceback.format_exc())
        print("⚠️ Continuing without daily summary email scheduler")

    print("✅ Application startup complete")
    
    yield
    
    # Shutdown
    print("🛑 Shutting down Log Analyzer Backend...")

    # Stop daily summary email scheduler
    try:
        daily_summary_scheduler.stop()
        print("✅ Daily summary email scheduler stopped")
    except Exception as e:
        print(f"⚠️ Error stopping daily summary scheduler: {str(e)}")

    # Cleanup socket service
    if socket_service or event_handler:
        await cleanup_socket_service(socket_service, event_handler)
        print("✅ Socket service cleaned up")


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
    openapi_tags=[
        {
            "name": "Authentication",
            "description": "OAuth2 authentication and JWT token management"
        },
        {
            "name": "SSO",
            "description": "Google and Microsoft SSO initiate/callback flows"
        },
        {
            "name": "Companies",
            "description": "Company management and user invitations"
        },
        {
            "name": "Users",
            "description": "User management within companies"
        },
        {
            "name": "Workspaces", 
            "description": "Multi-tenant workspace management"
        },
        {
            "name": "Channels",
            "description": "Channel management with automatic workspace creation"
        },
        {
            "name": "Messages",
            "description": "Thread-based messaging with AI integration"
        },
        {
            "name": "Attachments",
            "description": "File upload and management"
        },
        {
            "name": "AI Agent",
            "description": "AI processing and webhook management"
        },
        {
            "name": "Apps",
            "description": "Available applications management"
        },
        {
            "name": "App Accounts",
            "description": "App connections to channels"
        },
        {
            "name": "Data Sources",
            "description": "Datasource management and file uploads"
        },
        {
            "name": "GG Datasources",
            "description": "Unified datasource management across workspace, channel, thread, and message scopes"
        },
        {
            "name": "GG App Connections",
            "description": "Unified app connections across workspace, channel, and thread scopes (gg_app_connections table)"
        },
        {
            "name": "GG Workspaces",
            "description": "Workspace-level unified member and app-connection management"
        },
        {
            "name": "GG Channels",
            "description": "Channel-level unified member and app-connection management"
        },
        {
            "name": "Tasks",
            "description": "Task management and assignment"
        },
        {
            "name": "Checklists",
            "description": "Task checklist management"
        },
        {
            "name": "Approvals",
            "description": "Thread-level message approval management"
        },
        {
            "name": "Subscription Plans",
            "description": "Subscription plan management and configuration"
        },
        {
            "name": "Subscriptions",
            "description": "Company subscription management and billing"
        },
        {
            "name": "Public",
            "description": "Public endpoints for company signup and onboarding"
        },
        {
            "name": "Payment Gateway",
            "description": "Payment processing and Zoho integration"
        },
        {
            "name": "Templates",
            "description": "Email template management and file operations"
        }
    ]
)

def _cors_origins_for_credentials() -> list:
    """
    Starlette + allow_credentials=True cannot use wildcard Allow-Origin; SSO initiate uses Set-Cookie cross-origin.
    Strip entries, drop '*', and fall back to local dev origins if the env list is only '*'/empty.
    """
    cleaned = [o.strip() for o in settings.ALLOWED_ORIGINS if o and str(o).strip()]
    explicit = [o for o in cleaned if o != "*"]
    if explicit:
        return explicit
    return [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ]


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins_for_credentials(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add trusted host middleware
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.ALLOWED_HOSTS
)

# Add authentication middleware
app.add_middleware(AuthMiddleware)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": str(exc),
            "path": request.url.path
        }
    )


# Custom OpenAPI schema to include authentication
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        openapi_version="3.0.2",
    )
    
    # Ensure components section exists
    if "components" not in openapi_schema:
        openapi_schema["components"] = {}
    
    # Add security scheme
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }
    
    # Add security requirement to all protected endpoints
    for path in openapi_schema["paths"]:
        if not path.startswith("/health") and not path.startswith("/docs") and not path.startswith("/api/docs") and not path.startswith("/redoc") and not path.startswith("/openapi.json") and not path.startswith("/api/openapi"):
            for method in openapi_schema["paths"][path]:
                if method.lower() != "get" and not path.startswith("/api/v1/auth"):
                    if "security" not in openapi_schema["paths"][path][method]:
                        openapi_schema["paths"][path][method]["security"] = [{"BearerAuth": []}]
            # SSO endpoints are public OAuth redirect handlers.
            if path.startswith("/api/v1/sso"):
                for method in openapi_schema["paths"][path]:
                    openapi_schema["paths"][path][method]["security"] = [{"BearerAuth": []}]
    
    # Add global security requirement
    openapi_schema["security"] = [{"BearerAuth": []}]
    
    # Ensure the openapi version is explicitly set
    openapi_schema["openapi"] = "3.0.2"
    
    app.openapi_schema = openapi_schema
    return openapi_schema

# Enable custom OpenAPI schema with authentication
app.openapi = custom_openapi

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Log Analyzer Backend",
        "version": "1.0.0"
    }


# Socket health check endpoint
@app.get("/health/socket")
async def socket_health_check():
    """Socket service health check endpoint"""
    socket_health = get_socket_health_status()
    return {
        "status": "healthy" if socket_health["status"] == "healthy" else "unhealthy",
        "socket": socket_health
    }


# Scheduler health check endpoint
@app.get("/health/scheduler")
async def scheduler_health_check():
    """Daily summary email scheduler health check endpoint"""
    from app.services.daily_summary_scheduler import daily_summary_scheduler
    
    scheduler_status = {
        "is_running": daily_summary_scheduler.is_running,
        "status": "running" if daily_summary_scheduler.is_running else "stopped"
    }
    
    if daily_summary_scheduler.is_running and hasattr(daily_summary_scheduler, 'scheduler'):
        try:
            jobs = daily_summary_scheduler.scheduler.get_jobs()
            scheduler_status["jobs"] = [
                {
                    "id": job.id,
                    "next_run_time": str(job.next_run_time) if job.next_run_time else None,
                    "trigger": str(job.trigger)
                }
                for job in jobs
            ]
        except Exception as e:
            scheduler_status["error"] = str(e)
    
    return {
        "status": "healthy" if scheduler_status["is_running"] else "unhealthy",
        "scheduler": scheduler_status
    }


# Test endpoint to manually trigger scheduler (for testing only)
@app.post("/api/v1/test/scheduler/trigger")
async def trigger_scheduler_manually():
    """Manually trigger the daily summary scheduler for testing"""
    from app.services.daily_summary_scheduler import daily_summary_scheduler
    
    try:
        if not daily_summary_scheduler.is_running:
            return {
                "status": "error",
                "message": "Scheduler is not running"
            }
        
        # Manually trigger the process
        await daily_summary_scheduler.process_daily_summaries()
        
        return {
            "status": "success",
            "message": "Scheduler triggered manually - check logs for details"
        }
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "message": f"Error triggering scheduler: {str(e)}",
            "traceback": traceback.format_exc()
        }


# Short link redirect and resolve (under /api/v1 so proxy forwards same as other APIs)
app.include_router(shortener.router, prefix="/api/v1/redirect", tags=["Shortener"])

# Serve local uploads so DataAI and other clients can GET files by URL (LOCAL_FILES_URL + path)
# UPLOAD_DIR can be "uploads" or "app/uploads"; GET /app/uploads/<path> serves from that directory
upload_dir = os.path.abspath(settings.UPLOAD_DIR) if not os.path.isabs(settings.UPLOAD_DIR) else settings.UPLOAD_DIR
if os.path.isdir(upload_dir):
    app.mount("/app/uploads", StaticFiles(directory=upload_dir), name="uploads")
    logger.info("Mounted static files for uploads at /app/uploads -> %s", upload_dir)
else:
    logger.warning("Upload directory %s not found; not mounting /app/uploads static files", upload_dir)

# Serve email logo from repo; support logo.png and logo.jpg (e.g. Gradient BM as logo.jpg)
_EMAIL_LOGO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "email")

@app.get("/static/email/logo.jpg", include_in_schema=False)
def serve_email_logo_jpg():
    """Serve platform logo (JPG) for email templates."""
    path = os.path.join(_EMAIL_LOGO_DIR, "logo.jpg")
    if os.path.isfile(path):
        return FileResponse(path, media_type="image/jpeg")
    return Response(status_code=404)

# Include API routes
app.include_router(auth_router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(user_auth.router, prefix="/api/v1/user-auth", tags=["User Authentication"])
app.include_router(sso_router, prefix="/api/v1/sso", tags=["SSO"])
app.include_router(gmail_connect_router, prefix="/api/v1/gmail", tags=["Gmail Connect"])
app.include_router(zoho_connect_router, prefix="/api/v1/zoho", tags=["Zoho Connect"])
app.include_router(sf_connect_router, prefix="/api/v1/sf", tags=["Salesforce Connect"])
app.include_router(odoo_connect_router, prefix="/api/v1/odoo", tags=["Odoo Connect"])
app.include_router(companies.router, prefix="/api/v1/companies", tags=["Companies"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(workspaces_router, prefix="/api/v1/workspaces", tags=["Workspaces"])
app.include_router(channels_router, prefix="/api/v1/channels", tags=["Channels"])
app.include_router(messages_router, prefix="/api/v1/messages", tags=["Messages"])
app.include_router(attachments_router, prefix="/api/v1/attachments", tags=["Attachments"])
app.include_router(agent_router, prefix="/api/v1/agent", tags=["AI Agent"])
app.include_router(apps_router, prefix="/api/v1/apps", tags=["Apps"])
app.include_router(app_accounts_router, prefix="/api/v1/app-accounts", tags=["App Accounts"])
app.include_router(threads_router, prefix="/api/v1/threads", tags=["Threads"])
app.include_router(datasources.router, prefix="/api/v1/datasources", tags=["Data Sources"])
app.include_router(gg_datasources_router, prefix="/api/v1/gg-datasources", tags=["GG Datasources"])
app.include_router(gg_app_connections_router, prefix="/api/v1/gg-app-connections", tags=["GG App Connections"])
app.include_router(gg_workspaces_router, prefix="/api/v1/gg-workspaces", tags=["GG Workspaces"])
app.include_router(gg_channels_router, prefix="/api/v1/gg-channels", tags=["GG Channels"])
app.include_router(tasks_router, prefix="/api/v1/tasks", tags=["Tasks"])
app.include_router(checklists_router, prefix="/api/v1/checklists", tags=["Checklists"])
app.include_router(approvals_router, prefix="/api/v1/approvals", tags=["Approvals"])
app.include_router(subscription_plans.router, prefix="/api/v1/subscription-plans", tags=["Subscription Plans"])
app.include_router(subscriptions.router, prefix="/api/v1/subscriptions", tags=["Subscriptions"])
app.include_router(token_details.router, prefix="/api/v1", tags=["Token Details"])
app.include_router(public_router, prefix="/api/v1/public", tags=["Public"])
app.include_router(payment_gateway_router, prefix="/api/v1/payment-gateway", tags=["Payment Gateway"])
app.include_router(template.router, prefix="/api/v1/template", tags=["Templates"])
app.include_router(notifications_router, prefix="/api/v1/notifications", tags=["Notifications"])
app.include_router(support_router, prefix="/api/v1/support", tags=["Customer Support"])
app.include_router(audit.router, prefix="/api/v1/audit-log", tags=["Audit Log"])


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=settings.DEBUG,
        log_level="info",
        loop="asyncio" if settings.is_oracle else "auto",  # uvloop's TCPTransport lacks setsockopt needed by oracledb thin mode
    ) 
