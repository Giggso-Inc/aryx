"""Shared constants and response-builder helper for the apps route package."""

from fastapi.security import HTTPBearer

from app.core.config import settings
from app.models.app import App
from app.schemas.app import AppResponse

security = HTTPBearer()

# Cloud Drive app keys (for sub_category filtering)
CLOUD_DRIVE_APP_KEYS = ['google_drive', 'googledrive', 'sharepoint', 'share_point',
                        'dropbox', 'onedrive', 'one_drive', 'box']

# App keys to exclude from list_apps API (kept in DB for foreign key integrity)
EXCLUDED_APP_KEYS = settings.EXCLUDED_APP_KEYS.split(",")


def to_app_response(app: App) -> AppResponse:
    """Build an AppResponse from an App ORM instance. Extracted from the
    original file's repeated (create/list/get/update/stats) inline
    construction — a pure refactor, no behavior change."""
    return AppResponse(
        id=str(app.id),
        app_name=app.app_name,
        app_key=app.app_key,
        app_description=app.app_description,
        app_image=app.app_image,
        is_active=app.is_active,
        is_public=app.is_public,
        version=app.version,
        category=app.category,
        sub_category=app.sub_category,
        tags=app.tags,
        created_at=app.created_at,
        updated_at=app.updated_at
    )
