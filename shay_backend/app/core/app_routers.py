"""
Route registration for the FastAPI application: health checks, static file
mounts, and every `app.include_router(...)` call.

Extracted from main.py during Raven Phase 5a file-size compliance work.
Called once from main.py via `register_routers(app)`, after middleware
and exception handlers are registered.
"""

import os
import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.socket import get_socket_health_status

from app.routes import (
    auth_router, companies, users, workspaces_router, channels_router,
    messages_router, attachments_router, agent_router, apps_router,
    app_accounts_router, datasources, user_auth, tasks_router,
    checklists_router, approvals_router, subscription_plans, subscriptions,
    public_router, payment_gateway_router, notifications_router,
    support_router, template, token_details, shortener, audit,
    threads_router, gg_datasources_router, gg_app_connections_router,
    gg_workspaces_router, gg_channels_router, sso_router, aryx_router,
)
from app.routes.sso import router as sso_router
from app.routes.gmail_connect import router as gmail_connect_router
from app.routes.zoho_connect import router as zoho_connect_router
from app.routes.sf_connect import router as sf_connect_router
from app.routes.odoo_connect import router as odoo_connect_router

logger = logging.getLogger(__name__)

# Serve email logo from repo for email templates.
_EMAIL_LOGO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "static", "email")


def _register_health_routes(app: FastAPI) -> None:
    """Health check endpoints."""

    @app.get("/health")
    async def health_check():
        """Health check endpoint"""
        return {
            "status": "healthy",
            "service": "Log Analyzer Backend",
            "version": "1.0.0"
        }

    @app.get("/health/socket")
    async def socket_health_check():
        """Socket service health check endpoint"""
        socket_health = get_socket_health_status()
        return {
            "status": "healthy" if socket_health["status"] == "healthy" else "unhealthy",
            "socket": socket_health
        }

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


def _register_static_routes(app: FastAPI) -> None:
    """Local upload file serving and static email logo endpoints."""
    # Serve local uploads so DataAI and other clients can GET files by URL (LOCAL_FILES_URL + path)
    # UPLOAD_DIR can be "uploads" or "app/uploads"; GET /app/uploads/<path> serves from that directory
    upload_dir = os.path.abspath(settings.UPLOAD_DIR) if not os.path.isabs(settings.UPLOAD_DIR) else settings.UPLOAD_DIR
    if os.path.isdir(upload_dir):
        app.mount("/app/uploads", StaticFiles(directory=upload_dir), name="uploads")
        logger.info("Mounted static files for uploads at /app/uploads -> %s", upload_dir)
    else:
        logger.warning("Upload directory %s not found; not mounting /app/uploads static files", upload_dir)

    @app.get("/static/email/logo.jpg", include_in_schema=False)
    def serve_email_logo_jpg():
        """Serve platform logo (JPG) for email templates."""
        path = os.path.join(_EMAIL_LOGO_DIR, "logo.jpg")
        if os.path.isfile(path):
            return FileResponse(path, media_type="image/jpeg")
        return Response(status_code=404)

    @app.get("/static/email/logo.png", include_in_schema=False)
    def serve_email_logo_png():
        """Serve platform logo (PNG) for email templates."""
        path = os.path.join(_EMAIL_LOGO_DIR, "logo.png")
        if os.path.isfile(path):
            return FileResponse(path, media_type="image/png")
        return Response(status_code=404)


def _register_api_routers(app: FastAPI) -> None:
    """All `app.include_router(...)` calls for the versioned API (excluding shortener, registered earlier)."""
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
    app.include_router(aryx_router, prefix="/api/v1/aryx", tags=["Aryx Bridge"])


def register_routers(app: FastAPI) -> None:
    """Attach health checks, static routes, and every API router to `app`, in the same order as the former main.py."""
    _register_health_routes(app)
    # Short link redirect and resolve (under /api/v1 so proxy forwards same as other APIs)
    app.include_router(shortener.router, prefix="/api/v1/redirect", tags=["Shortener"])
    _register_static_routes(app)
    _register_api_routers(app)
