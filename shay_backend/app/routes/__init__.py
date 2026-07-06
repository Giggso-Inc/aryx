"""
API routes for the Log Analyzer Backend
"""

from .auth import router as auth_router
from .workspaces import router as workspaces_router
from .messages import router as messages_router
from .attachments import router as attachments_router
from .agent import router as agent_router
from .channels import router as channels_router
from .apps import router as apps_router
from .app_accounts import router as app_accounts_router
from .tasks import router as tasks_router
from .checklists import router as checklists_router
from .approvals import router as approvals_router
from .public import router as public_router
from .payment_gateway import router as payment_gateway_router
from .notifications import router as notifications_router
from .support import router as support_router
from .threads import router as threads_router
from .gg_datasources import router as gg_datasources_router
from .gg_app_connections import router as gg_app_connections_router
from .gg_workspaces import router as gg_workspaces_router
from .gg_channels import router as gg_channels_router
from .sso import router as sso_router
from . import token_details  # Token details (module with router)

__all__ = [
    "auth_router",
    "workspaces_router",
    "messages_router",
    "attachments_router",
    "agent_router",
    "channels_router",
    "apps_router",
    "app_accounts_router",
    "tasks_router",
    "checklists_router",
    "approvals_router",
    "public_router",
    "payment_gateway_router",
    "notifications_router",
    "support_router",
    "threads_router",
    "gg_datasources_router",
    "gg_app_connections_router",
    "gg_workspaces_router",
    "gg_channels_router",
    "token_details",
]