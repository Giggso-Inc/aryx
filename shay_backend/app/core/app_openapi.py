"""
OpenAPI tag metadata and custom schema builder for the FastAPI application.

Extracted from main.py during Raven Phase 5a file-size compliance work.
`OPENAPI_TAGS` is passed to `FastAPI(openapi_tags=OPENAPI_TAGS, ...)` at
construction time in main.py; `register_openapi(app)` is called once,
after construction, to install the custom schema builder (equivalent to
the former `app.openapi = custom_openapi` line in main.py).
"""

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

OPENAPI_TAGS = [
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


def register_openapi(app: FastAPI) -> None:
    """Install the custom OpenAPI schema builder (adds BearerAuth security) on `app`."""

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
